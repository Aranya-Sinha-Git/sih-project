from __future__ import annotations

import hashlib, heapq, json, os, sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .auth import AuthenticatedUser, reviewer_for_request, validate_configuration
from .services.classifier import analyze_with_classifier, classifier_metadata
from .services.engine import analyze_text
from .services.local_llm import get_local_llm_service
from .services.retrieval import get_retrieval_service
from .services.database import get_database, init_sqlite, sqlite_connection

ROOT = Path(__file__).resolve().parents[1]
REPORT_TYPES = {"Unsafe Act", "Unsafe Condition", "Near Miss", "Incident", "Unspecified"}
ACTIONABLE_REVIEW_STATUSES = ("Pending", "Escalated")
REVIEW_OUTCOME_ALIASES = {"Confirm SIF": "Confirm SIF", "Confirm Non-SIF": "Confirm Non-SIF", "Escalate / Unsure": "Escalated / Unsure", "Escalated / Unsure": "Escalated / Unsure"}

def con() -> sqlite3.Connection:
    """Compatibility handle for explicit SQLite legacy/test tooling only."""
    return sqlite_connection()

def init_db() -> None:
    if get_database().kind == "sqlite-test":
        init_sqlite()

init_db()

class AnalyzeInput(BaseModel):
    narrative: str = Field(min_length=1)
    site: Optional[str] = "Unspecified"
    activity: Optional[str] = None
    report_type: Optional[str] = "Unspecified"
    report_id: Optional[str] = None
    source: Optional[str] = None

    @field_validator("narrative")
    @classmethod
    def narrative_is_meaningful(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 12: raise ValueError("narrative must contain at least 12 non-whitespace characters")
        return value

    @field_validator("report_type")
    @classmethod
    def supported_report_type(cls, value: Optional[str]) -> Optional[str]:
        value = (value or "Unspecified").strip() or "Unspecified"
        if value not in REPORT_TYPES: raise ValueError("report_type must be Unsafe Act, Unsafe Condition, Near Miss, Incident, or Unspecified.")
        return value

class BatchInput(BaseModel): reports: list[AnalyzeInput]
class ReviewInput(BaseModel):
    outcome: str
    reviewer: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=2000)
class AlertUpdate(BaseModel): status: str
class IntelligenceInput(BaseModel): force: bool = False

def model_outcome(row: dict[str, Any]) -> Optional[str]:
    analysis = row.get("analysis") or {}
    decision = (analysis.get("screening") or {}).get("decision")
    if decision == "SIF_POTENTIAL": return "SIF Potential"
    if decision == "NON_SIF_POTENTIAL": return "Non-SIF Potential"
    if decision == "HUMAN_REVIEW": return "Needs Review"
    return None

def human_review_outcome(row: dict[str, Any]) -> Optional[str]:
    if row.get("review_status") == "Escalated": return "Escalated / Unsure"
    if row.get("review_status") == "Reviewed" and row.get("sif_potential") == 1: return "Confirm SIF"
    if row.get("review_status") == "Reviewed" and row.get("sif_potential") == 0: return "Confirm Non-SIF"
    return None

def out(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if isinstance(item.get("analysis"), str):
        raw_analysis = item["analysis"]
        try:
            item["analysis"] = json.loads(raw_analysis)
        except json.JSONDecodeError:
            item["analysis"] = {"model_mode": "Unknown legacy analysis", "legacy_raw_analysis": raw_analysis, "screening": {"decision": "UNKNOWN", "failure_reason": "analysis_json_invalid"}}
    if not isinstance(item.get("analysis"), dict):
        item["analysis"] = {"model_mode": "Unknown legacy analysis", "screening": {"decision": "UNKNOWN", "failure_reason": "analysis_missing"}}
    elif "screening" not in item["analysis"]:
        item["analysis"]["screening"] = {"decision": "LEGACY_RULES_ENGINE", "raw_score": item["analysis"].get("sif_probability"), "calibration_status": "not_applicable", "failure_reason": "legacy_analysis"}
    item["model_outcome"] = model_outcome(item)
    item["human_outcome"] = human_review_outcome(item)
    item["human_review_outcome"] = item["human_outcome"]
    item["effective_outcome"] = item["human_outcome"] or ("Pending human review" if item.get("review_status") in ACTIONABLE_REVIEW_STATUSES else item["model_outcome"])
    return item

def disposition_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
    return {"model_positive_cases": sum(x.get("model_outcome") == "SIF Potential" for x in reports), "confirmed_sif_cases": sum(x.get("human_outcome") == "Confirm SIF" for x in reports), "confirmed_non_sif_cases": sum(x.get("human_outcome") == "Confirm Non-SIF" for x in reports), "unresolved_escalated": sum(x.get("human_outcome") == "Escalated / Unsure" for x in reports), "unreviewed_model_positive": sum(x.get("model_outcome") == "SIF Potential" and x.get("human_outcome") is None for x in reports)}

def _incident_id(narrative: str) -> str: return "ANL-" + hashlib.sha1((narrative + datetime.now().isoformat()).encode()).hexdigest()[:8].upper()

def persist_incident(*, narrative: str, site: str, activity: Optional[str], report_type: Optional[str], analysis: dict[str, Any], report_id: Optional[str] = None, report_date: Optional[str] = None, source: str = "user_analysis", import_batch_id: Optional[str] = None, connection: Optional[sqlite3.Connection] = None, auth_user: AuthenticatedUser | None = None) -> dict[str, Any]:
    narrative = narrative.strip()
    if len(narrative) < 12: raise ValueError("narrative must contain at least 12 non-whitespace characters")
    resolved_site = (site or analysis.get("location") or "Unspecified").strip(); resolved_activity = (activity or analysis.get("activity") or "Unspecified").strip(); resolved_type = (report_type or "Unspecified").strip() or "Unspecified"
    if resolved_type not in REPORT_TYPES: raise ValueError("report_type must be Unsafe Act, Unsafe Condition, Near Miss, Incident, or Unspecified.")
    ident = report_id or _incident_id(narrative)
    record = {"id": ident, "report_date": report_date or str(date.today()), "site": resolved_site, "activity": resolved_activity, "narrative": narrative, "source": source, "source_id": (analysis.get("provenance") or {}).get("source_report_id"), "normalized_narrative": _normalized_narrative(narrative), "sif_probability": analysis["sif_probability"], "risk": analysis["risk"], "high_potential": analysis["high_potential"], "sif_potential": analysis["sif_potential"], "sif_label_status": analysis["sif_label_status"], "analysis": analysis, "review_status": "Pending" if analysis["review_required"] else "Not required", "reviewer": None, "review_comment": None, "created_at": datetime.now().isoformat(), "created_by_user_id": auth_user.id if auth_user else None, "report_type": resolved_type, "import_batch_id": import_batch_id}
    try:
        get_database().insert_incident(record, connection=connection)
        if connection is not None:
            connection.commit()
    except Exception:
        if connection is not None: connection.rollback()
        raise
    return {"id": ident, "narrative": narrative, "site": resolved_site, "activity": resolved_activity, "report_type": resolved_type, **analysis}

def rows() -> list[dict[str, Any]]:
    return [out(row) for row in get_database().list_incidents()]

def _tokens(text: str) -> set[str]: return {word.strip(".,;:()[]{}").lower() for word in text.split() if len(word) > 3}

def _normalized_narrative(text: str) -> str:
    return " ".join((text or "").casefold().split())

def _similar_incidents(item: dict[str, Any], limit: int = 5, corpus: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    current_narrative = _normalized_narrative(str(item.get("narrative") or ""))
    candidates = [x for x in (corpus if corpus is not None else rows()) if x["id"] != item.get("id") and _normalized_narrative(str(x.get("narrative") or "")) != current_narrative]
    candidate_by_id = {x["id"]: x for x in candidates}
    retrieved = get_retrieval_service().historical_evidence(item["narrative"], candidates, limit=limit, locked_ids={str(item.get("id"))}, current_source_id=item.get("source_id"))
    return [{"similarity": evidence["relevance_score"], "relevance_score": evidence["relevance_score"], "incident_id": evidence["incident_id"], "source_id": evidence["source_id"], "title": evidence["title"], "site": candidate_by_id[evidence["incident_id"]].get("site"), "activity": candidate_by_id[evidence["incident_id"]].get("activity"), "risk": candidate_by_id[evidence["incident_id"]].get("risk"), "life_saving_rule": (((candidate_by_id[evidence["incident_id"]].get("analysis") or {}).get("rules") or {}).get("primary") or {}).get("rule", "Unmapped"), "retrieval_method": evidence["retrieval_method"], "corpus_version": evidence["corpus_version"], "label_provenance": evidence["label_provenance"]} for evidence in retrieved]

def sim(item: dict[str, Any], limit: int = 5, corpus: Optional[list[dict[str, Any]]] = None) -> list[dict[str, Any]]:
    try:
        return _similar_incidents(item, limit=limit, corpus=corpus)
    except Exception:
        return []

def sim_with_status(item: dict[str, Any], limit: int = 5, corpus: Optional[list[dict[str, Any]]] = None) -> tuple[list[dict[str, Any]], str, Optional[str]]:
    try:
        return _similar_incidents(item, limit=limit, corpus=corpus), "available", None
    except Exception as error:
        return [], "retrieval_unavailable", type(error).__name__

def intelligence_snapshot(narrative: str, item_id: Optional[str] = None, corpus: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    try:
        service = get_retrieval_service(); candidates = corpus if corpus is not None else rows(); locked = {str(item_id)} if item_id else set()
        current_source_id = next((str(item.get("source_id")) for item in candidates if str(item.get("id")) == str(item_id) and item.get("source_id")), None)
        historical = service.historical_evidence(narrative, candidates, locked_ids=locked, current_source_id=current_source_id)
        return {"reference_evidence": service.reference_evidence(narrative), "historical_evidence": historical, "corpus_version": service.corpus_version}
    except Exception as error:
        return {"reference_evidence": [], "historical_evidence": [], "corpus_version": "unavailable", "status": "retrieval_unavailable", "failure_reason": type(error).__name__}

def _update_analysis_snapshot(incident_id: str, snapshot: dict[str, Any], connection: Optional[sqlite3.Connection] = None) -> None:
    row = get_database().get_incident(incident_id)
    if row:
        analysis = row.get("analysis") or {}
        if isinstance(analysis, str):
            try: analysis = json.loads(analysis)
            except json.JSONDecodeError: analysis = {"legacy_raw_analysis": analysis}
        analysis["intelligence"] = snapshot
        get_database().update_analysis(incident_id, analysis, connection=connection)

def report_anchor(reports: list[dict[str, Any]]) -> date: return max((date.fromisoformat(item["report_date"]) for item in reports), default=date.today())
def trends(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchor = report_anchor(reports); result = []
    for offset in range(5, -1, -1):
        end = anchor - timedelta(days=offset * 7); start = end - timedelta(days=6); period = [x for x in reports if start <= date.fromisoformat(x["report_date"]) <= end]
        result.append({"period": start.strftime("%d %b"), "high": sum(x["risk"] == "High" for x in period), "reviews": sum(x["review_status"] in ACTIONABLE_REVIEW_STATUSES for x in period)})
    return result

def site_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for site in sorted({x["site"] for x in reports if x["site"]}):
        group = [x for x in reports if x["site"] == site]; anchor = report_anchor(group); high = sum(x["risk"] == "High" for x in group); current_sif_cases = sum(x.get("sif_potential") == 1 for x in group); model_positive = sum(x.get("model_outcome") == "SIF Potential" for x in group); effective_positive = sum(x.get("effective_outcome") in {"SIF Potential", "Confirm SIF"} for x in group); pending = sum(x["review_status"] in ACTIONABLE_REVIEW_STATUSES for x in group); scores = [x["sif_probability"] for x in group if x["sif_probability"] is not None]; score_signal = sum(scores) / len(scores) if scores else 0; density = round(100 * model_positive / len(group), 1); index = min(100, round((high / len(group) * 55 + score_signal * 45) * 1.65 + pending * .7)); recent = sum(date.fromisoformat(x["report_date"]) >= anchor - timedelta(days=30) for x in group); prior = sum(anchor - timedelta(days=60) <= date.fromisoformat(x["report_date"]) < anchor - timedelta(days=30) for x in group); trend = "Rising" if recent > prior else "Declining" if recent < prior else "Stable"
        result.append({"site": site, "reports": len(group), "sif_cases": current_sif_cases, "model_positive_cases": model_positive, "effective_positive_cases": effective_positive, "sif_precursor_density": density, "pending_reviews": pending, "risk_index": index, "trend": trend, **disposition_counts(group)})
    return sorted(result, key=lambda x: (x["sif_precursor_density"], x["reports"]), reverse=True)

def activity_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for activity in sorted({x["activity"] for x in reports if x["activity"]}):
        group = [x for x in reports if x["activity"] == activity]; scores = [x["sif_probability"] for x in group if x["sif_probability"] is not None]; average = round(sum(scores) / len(scores), 2) if scores else None; current_sif_cases = sum(x.get("sif_potential") == 1 for x in group); model_positive = sum(x.get("model_outcome") == "SIF Potential" for x in group); effective_positive = sum(x.get("effective_outcome") in {"SIF Potential", "Confirm SIF"} for x in group)
        result.append({"activity": activity, "reports": len(group), "sif_cases": current_sif_cases, "model_positive_cases": model_positive, "effective_positive_cases": effective_positive, "sif_precursor_density": round(100 * model_positive / len(group), 1), "avg_model_score": average, "risk_index": min(100, round((average or 0) * 100)), **disposition_counts(group)})
    return sorted(result, key=lambda x: (x["sif_precursor_density"], x["reports"]), reverse=True)

def rule_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in reports:
        primary = ((item.get("analysis") or {}).get("rules") or {}).get("primary")
        if primary: counts[primary["rule"]] = counts.get(primary["rule"], 0) + 1
    return [{"rule": k, "count": v, "provenance": "unverified_keyword_candidate"} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

def cluster_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in reports:
        for precursor in item["analysis"].get("precursors", []):
            if precursor != "no strong precursor pattern": groups.setdefault(precursor, []).append(item)
    result = []
    for name, group in groups.items():
        anchor = report_anchor(group); primary = [(((x.get("analysis") or {}).get("rules") or {}).get("primary") or {}).get("rule") for x in group]; primary = [x for x in primary if x]; rule_candidate = max(set(primary), key=primary.count) if primary else None; recent = sum(date.fromisoformat(x["report_date"]) >= anchor - timedelta(days=30) for x in group); prior = sum(anchor - timedelta(days=60) <= date.fromisoformat(x["report_date"]) < anchor - timedelta(days=30) for x in group); trend = "Rising" if recent > prior else "Declining" if recent < prior else "Stable"; model_positive_count = sum(x.get("model_outcome") == "SIF Potential" for x in group); effective_positive_count = sum(x.get("effective_outcome") in {"SIF Potential", "Confirm SIF"} for x in group); model_positive_percentage = round(100 * model_positive_count / len(group)); effective_positive_percentage = round(100 * effective_positive_count / len(group))
        result.append({"name": name.title(), "count": len(group), "model_positive_count": model_positive_count, "model_positive_percentage": model_positive_percentage, "effective_positive_count": effective_positive_count, "effective_positive_percentage": effective_positive_percentage, "sif_percentage": model_positive_percentage, "sif_percentage_basis": "frozen classifier screening", "affected_sites": sorted({x["site"] for x in group}), "activities": sorted({x["activity"] for x in group})[:3], "rule": None, "unverified_rule_candidate": rule_candidate, "rule_provenance": "unverified_keyword_candidate" if rule_candidate else "none", "trend": trend, "representative_incidents": [x["id"] for x in group[:3]]})
    return sorted(result, key=lambda x: x["count"], reverse=True)

app = FastAPI(title="SIF Sentinel API", version="1.0.0")
_cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    if request.url.path != "/health":
        user = reviewer_for_request(request)
        if user is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        request.state.user = user
        request.state.reviewer = user.display_name or user.username
    return await call_next(request)

@app.on_event("startup")
def start() -> None: validate_configuration(); init_db()

@app.get("/health")
def health():
    metadata = classifier_metadata()
    return {"status": "ok", "model_mode": "Frozen supervised classifier", "model_status": metadata["status"], "model_version": metadata["model_version"], "llm_configured": get_local_llm_service().configured, "database": get_database().kind}
def analyzed_result(report: AnalyzeInput) -> dict[str, Any]:
    analysis = analyze_with_classifier(report.narrative, analyze_text(report.narrative))
    analysis["intelligence"] = intelligence_snapshot(report.narrative)
    mappings = [{"rule": item["rule"], "evidence_id": item["evidence_id"],
                 "provenance": "grounded_iogp_reference"}
                for item in analysis["intelligence"]["reference_evidence"]
                if item.get("reference_type") == "iogp_reference" and item.get("rule")]
    analysis["rules"] = {"primary": mappings[0] if mappings else None, "secondary": mappings[1:]}
    return analysis

@app.post("/analyze")
def analyze(report: AnalyzeInput, request: Request):
    duplicate = next((x for x in rows() if _normalized_narrative(x.get("narrative", "")) == _normalized_narrative(report.narrative) and str(x.get("site") or "").casefold() == str(report.site or "Unspecified").casefold()), None)
    if duplicate:
        return incident(duplicate["id"])
    try: result = persist_incident(narrative=report.narrative, site=report.site or "Unspecified", activity=report.activity, report_type=report.report_type, analysis=analyzed_result(report), auth_user=getattr(request.state, "user", None))
    except ValueError as error: raise HTTPException(422, str(error)) from error
    result["intelligence"] = intelligence_snapshot(report.narrative, result["id"]); result["similar_incidents"], result["similar_incidents_status"], result["similar_incidents_failure_reason"] = sim_with_status(result); _update_analysis_snapshot(result["id"], result["intelligence"]); return result

@app.post("/analyze/batch")
def batch(batch_input: BatchInput, request: Request):
    if len(batch_input.reports) > 500: raise HTTPException(422, "Batch limit is 500 reports.")
    analyses = [analyzed_result(report) for report in batch_input.reports]; batch_id = "BATCH-" + hashlib.sha1(datetime.now().isoformat().encode()).hexdigest()[:12].upper(); connection = con() if get_database().kind == "sqlite-test" else None; working_corpus = rows(); results = []; skipped_duplicates = []; seen_keys: dict[tuple[str, str], str] = {}; seen_ids: dict[str, str] = {}
    try:
        for report, analysis in zip(batch_input.reports, analyses):
            site = (report.site or "Unspecified").strip() or "Unspecified"; normalized = _normalized_narrative(report.narrative); report_id = (report.report_id or "").strip() or None; duplicate = next((x for x in working_corpus if (report_id and str(x.get("id")) == report_id) or (_normalized_narrative(str(x.get("narrative") or "")) == normalized and str(x.get("site") or "Unspecified").casefold() == site.casefold())), None)
            if duplicate:
                skipped_duplicates.append({"report_id": report_id, "existing_id": duplicate.get("id"), "reason": "duplicate narrative/site or report ID"}); continue
            key = (normalized, site.casefold())
            if key in seen_keys or (report_id and report_id in seen_ids):
                skipped_duplicates.append({"report_id": report_id, "existing_id": seen_keys.get(key) or seen_ids.get(report_id or ""), "reason": "duplicate within upload"}); continue
            result = persist_incident(narrative=report.narrative, site=site, activity=report.activity, report_type=report.report_type, analysis=analysis, report_id=report_id, source=report.source or "user_analysis", import_batch_id=batch_id, connection=connection, auth_user=getattr(request.state, "user", None)); result["intelligence"] = intelligence_snapshot(report.narrative, result["id"], working_corpus); analysis["intelligence"] = result["intelligence"]; _update_analysis_snapshot(result["id"], result["intelligence"], connection); result["similar_incidents"], result["similar_incidents_status"], result["similar_incidents_failure_reason"] = sim_with_status(result, corpus=working_corpus); working_corpus.append({**result, "analysis": analysis, "review_status": "Pending" if analysis["review_required"] else "Not required"}); seen_keys[key] = result["id"]; seen_ids[result["id"]] = result["id"]; results.append(result)
        if connection is not None: connection.commit()
    except Exception as error:
        if connection is not None: connection.rollback()
        raise HTTPException(500, "Batch persistence failed; no reports were saved.") from error
    finally:
        if connection is not None: connection.close()
    scored = [x for x in results if x["sif_probability"] is not None]
    return {"processed_count": len(results), "skipped_duplicate_count": len(skipped_duplicates), "skipped_duplicates": skipped_duplicates, "sif_potential_count": sum(x["sif_potential"] is True for x in results), "review_count": sum(x["review_required"] for x in results), "highest_risk_site": max(scored, key=lambda x: x["sif_probability"])["site"] if scored else None, "highest_risk_activity": max(scored, key=lambda x: x["sif_probability"])["activity"] if scored else None, "top_lsr": next((x["rules"]["primary"]["rule"] for x in results if x["rules"]["primary"]), None), "results": results}

@app.get("/incidents")
def incidents(search: str = "", site: Optional[str] = None, activity: Optional[str] = None, risk: Optional[str] = None, review: Optional[str] = None, source: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)):
    result, total = get_database().list_incidents_page(search=search, site=site, activity=activity, risk=risk, review=review, source=source, page=page, page_size=page_size)
    return {"items": [out(row) for row in result], "total": total, "page": page, "page_size": page_size}

@app.get("/incidents/{incident_id}")
def incident(incident_id: str):
    row = get_database().get_incident(incident_id); history = get_database().review_history(incident_id)
    if not row: raise HTTPException(404, "Report not found")
    result = out(row); result["review_history"] = history; result["similar_incidents"], result["similar_incidents_status"], result["similar_incidents_failure_reason"] = sim_with_status(result); return result

@app.get("/incidents/{incident_id}/similar")
def similar(incident_id: str): return incident(incident_id)["similar_incidents"]

@app.post("/incidents/{incident_id}/intelligence")
def intelligence(incident_id: str, intelligence_input: IntelligenceInput):
    row = get_database().get_incident(incident_id)
    if not row: raise HTTPException(404, "Report not found")
    try:
        analysis = json.loads(row["analysis"]) if isinstance(row.get("analysis"), str) else (row.get("analysis") or {})
        if not isinstance(analysis, dict): raise ValueError("legacy analysis is not an object")
    except (TypeError, ValueError, json.JSONDecodeError):
        result = incident(incident_id)
        unavailable = {"reference_evidence": [], "historical_evidence": [], "corpus_version": "unavailable", "status": "legacy_unavailable", "failure_reason": "analysis_json_invalid", "explanation": {"status": "unavailable", "completion_status": "unavailable", "text": "Intelligence is unavailable for this legacy analysis record."}}
        result["analysis"]["intelligence"] = unavailable
        result["intelligence"] = unavailable
        return result
    snapshot = analysis.get("intelligence") or {}; screening = analysis.get("screening") or {}
    explanation = get_local_llm_service().explain(row["narrative"], screening, snapshot.get("reference_evidence", []), snapshot.get("historical_evidence", []), force=intelligence_input.force)
    snapshot["explanation"] = explanation; analysis["intelligence"] = snapshot
    get_database().update_analysis(incident_id, analysis)
    return incident(incident_id)

@app.get("/dashboard/summary")
def dashboard():
    report_rows = rows(); site_rows = site_stats(report_rows); alert_rows = alerts(); model_positive = sum(x["model_outcome"] == "SIF Potential" for x in report_rows); confirmed_sif = sum(x["human_outcome"] == "Confirm SIF" for x in report_rows); confirmed_non_sif = sum(x["human_outcome"] == "Confirm Non-SIF" for x in report_rows); unresolved = sum(x["human_outcome"] == "Escalated / Unsure" for x in report_rows); unreviewed_model_positive = sum(x["model_outcome"] == "SIF Potential" and x["human_outcome"] is None for x in report_rows)
    return {"reports_analyzed": len(report_rows), "potential_sif_cases": model_positive, "sif_case_basis": "frozen classifier screening", "confirmed_sif_cases": confirmed_sif, "confirmed_non_sif_cases": confirmed_non_sif, "unresolved_escalated": unresolved, "unreviewed_model_positive": unreviewed_model_positive, "high_risk_sites": sum(x["risk_index"] >= 58 for x in site_rows), "pending_reviews": sum(x["review_status"] in ACTIONABLE_REVIEW_STATUSES for x in report_rows), "operational_risk_index": round(sum(x["risk_index"] for x in site_rows) / len(site_rows)) if site_rows else None, "emerging_alert": alert_rows[0]["title"] if alert_rows else None, "trend": trends(report_rows), "risk_distribution": [{"name": x, "value": sum(a["risk"] == x for a in report_rows)} for x in ["High", "Medium", "Low"]], "rules": rule_stats(report_rows)[:5], "sites": site_rows[:5], "activities": activity_stats(report_rows)[:5], "clusters": cluster_stats(report_rows)[:4]}

@app.get("/analytics/sites")
def sites(): return site_stats(rows())
@app.get("/analytics/sites/{site}")
def site_detail(site: str):
    all_rows = rows(); filtered = [x for x in all_rows if x["site"].lower() == site.lower()]
    if not filtered: raise HTTPException(404, "Site not found")
    return {"summary": next(x for x in site_stats(all_rows) if x["site"].lower() == site.lower()), "incidents": filtered[:20], "rules": rule_stats(filtered), "activities": activity_stats(filtered), "trend": trends(filtered), "emerging_pattern": next((x for x in cluster_stats(all_rows) if site in x["affected_sites"]), None)}
@app.get("/analytics/activities")
def activities(): return activity_stats(rows())
@app.get("/analytics/activities/{activity}")
def activity_detail(activity: str):
    all_rows = rows(); filtered = [x for x in all_rows if x["activity"].lower() == activity.lower()]
    if not filtered: raise HTTPException(404, "Activity not found")
    return {"summary": next(x for x in activity_stats(all_rows) if x["activity"].lower() == activity.lower()), "incidents": filtered[:20], "sites": site_stats(filtered), "rules": rule_stats(filtered), "trend": trends(filtered)}
@app.get("/analytics/rules")
def rules(): return rule_stats(rows())
@app.get("/analytics/trends")
def analytics_trends(): return trends(rows())
@app.get("/analytics/clusters")
def clusters(): return cluster_stats(rows())

@app.get("/reviews")
def reviews(): return [x for x in rows() if x["review_status"] in ACTIONABLE_REVIEW_STATUSES]

@app.post("/reviews/{incident_id}")
def review(incident_id: str, review_input: ReviewInput, request: Request):
    outcome = REVIEW_OUTCOME_ALIASES.get(review_input.outcome.strip())
    if outcome is None: raise HTTPException(422, "Use Confirm SIF, Confirm Non-SIF, or Escalated / Unsure.")
    user = getattr(request.state, "user", None)
    reviewer = (user.display_name if user else None) or review_input.reviewer.strip()
    if len(reviewer) < 2: raise HTTPException(422, "Reviewer identity is required.")
    current = get_database().get_incident(incident_id)
    if not current: raise HTTPException(404, "Report not found")
    previous = human_review_outcome(current)
    status = "Escalated" if outcome == "Escalated / Unsure" else "Reviewed"; sif_value = 1 if outcome == "Confirm SIF" else 0 if outcome == "Confirm Non-SIF" else None; label_status = "manual_reviewed" if sif_value is not None else "unresolved"; analysis = current.get("analysis") or {}; analysis = json.loads(analysis) if isinstance(analysis, str) else analysis; screening_version = analysis.get("model_version") or (analysis.get("screening") or {}).get("model_identity")
    try:
        get_database().apply_review(incident_id, {"status": status, "reviewer": reviewer, "reviewer_user_id": user.id if user else None, "comment": review_input.comment, "sif_potential": sif_value, "label_status": label_status, "outcome": outcome, "timestamp": datetime.now().isoformat(), "previous_outcome": previous, "screening_version": screening_version})
    except Exception:
        raise
    result = incident(incident_id); result["ok"] = True; return result

@app.get("/alerts")
def alerts():
    return get_database().list_alerts()
@app.patch("/alerts/{alert_id}")
def alert_update(alert_id: str, update: AlertUpdate):
    if update.status not in ["New", "Acknowledged", "Resolved"]: raise HTTPException(422, "Use New, Acknowledged, or Resolved.")
    if not get_database().update_alert(alert_id, update.status): raise HTTPException(404, "Alert not found")
    return {"ok": True, "status": update.status}
@app.get("/model")
def model():
    metadata = classifier_metadata()
    return {"mode": "Frozen supervised classifier", "version": metadata["model_version"], "model_identity": metadata["model_identity"], "model_hash": metadata["model_hash"], "configuration_hash": metadata["configuration_hash"], "status": metadata["status"], "thresholds": metadata["thresholds"], "calibration_status": metadata["calibration_status"], "calibration": {"status": "incomplete", "evidence_population": None, "requirement": "independent human-labelled development data; never the final blind test", "metrics": None}, "llm_configured": get_local_llm_service().configured, "provenance": "Frozen predictor selected by threshold configuration; raw score is not calibrated as a probability.", "external_evaluation": "Human blind validation is pending locked adjudications.", "metrics": None, "ai_assisted_internal": {"status": "not_published", "sample_size": None, "metrics": None}, "human_blind_test": {"status": "pending_locked_adjudications", "sample_size": None, "unresolved_exclusions": None, "metrics": None}, "fallback": "Inference failures are explicitly routed to human review with no score."}
