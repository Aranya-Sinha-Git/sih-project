from __future__ import annotations

import asyncio, hashlib, heapq, json, os, sqlite3, threading, time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from .auth import (MAX_DISPLAY_NAME_LENGTH, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, AuthProviderError,
                   AuthenticatedUser, create_auth_user, delete_auth_user, normalize_username,
                   reviewer_for_request, username_to_internal_email, validate_configuration)
from .services.classifier import analyze_with_classifier, classifier_metadata
from .services.domain_model import get_domain_model
from .services.engine import analyze_text
from .services.local_llm import get_local_llm_service
from .services.retrieval import get_retrieval_service
from .services.database import get_database, init_sqlite, sqlite_connection

ROOT = Path(__file__).resolve().parents[1]
REPORT_TYPES = {"Unsafe Act", "Unsafe Condition", "Near Miss", "Incident", "Unspecified"}
ACTIONABLE_REVIEW_STATUSES = ("Pending", "Escalated")
REVIEW_OUTCOME_ALIASES = {"Confirm SIF": "Confirm SIF", "Confirm Non-SIF": "Confirm Non-SIF", "Escalate / Unsure": "Escalated / Unsure", "Escalated / Unsure": "Escalated / Unsure"}
MAX_NARRATIVE_CHARS = 20_000
MAX_BATCH_REPORTS = 500
PUBLIC_HEALTH_PATHS = {"/live", "/health", "/ready"}
PUBLIC_UNAUTHENTICATED_PATHS = PUBLIC_HEALTH_PATHS | {"/auth/register"}
_registration_attempts: dict[str, list[float]] = {}
_registration_attempts_lock = threading.Lock()

def con() -> sqlite3.Connection:
    """Compatibility handle for explicit SQLite legacy/test tooling only."""
    return sqlite_connection()

def init_db() -> None:
    if get_database().kind == "sqlite-test":
        init_sqlite()

init_db()

class AnalyzeInput(BaseModel):
    narrative: str = Field(min_length=1, max_length=MAX_NARRATIVE_CHARS)
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

class BatchInput(BaseModel): reports: list[AnalyzeInput] = Field(min_length=1, max_length=MAX_BATCH_REPORTS)
class ReviewInput(BaseModel):
    outcome: str
    reviewer: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=2000)
class AlertUpdate(BaseModel): status: str
class IntelligenceInput(BaseModel): force: bool = False


class RegistrationInput(BaseModel):
    user_id: str = Field(validation_alias=AliasChoices("user_id", "username"), min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=MAX_DISPLAY_NAME_LENGTH)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    password_confirmation: str = Field(validation_alias=AliasChoices("password_confirmation", "confirm_password"), min_length=1, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: Any) -> str:
        return normalize_username(str(value or ""))

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value: Any) -> str:
        return " ".join(str(value or "").strip().split())

    @field_validator("password")
    @classmethod
    def require_strong_password(cls, value: str) -> str:
        categories = sum(bool(check) for check in (any(char.islower() for char in value), any(char.isupper() for char in value), any(char.isdigit() for char in value), any(not char.isalnum() for char in value)))
        if len(value) < MIN_PASSWORD_LENGTH or categories < 3:
            raise ValueError("Password must be at least 12 characters and include at least three of lowercase, uppercase, number, or symbol.")
        return value

    @model_validator(mode="after")
    def passwords_match(self) -> "RegistrationInput":
        if self.password != self.password_confirmation:
            raise ValueError("Password confirmation does not match.")
        return self

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

def requires_human_review(row: dict[str, Any]) -> bool:
    """Return the one queue predicate used by dashboard, API, and UI labels."""
    return row.get("review_status") in ACTIONABLE_REVIEW_STATUSES

def _stored_provenance(analysis: dict[str, Any]) -> dict[str, Any]:
    screening = analysis.get("screening") or {}
    mapping = analysis.get("lsr_mapping") or {}
    mode = str(analysis.get("model_mode") or "").casefold()
    version = str(analysis.get("model_version") or "").casefold()
    legacy = mode in {"transparent rules engine", "unknown legacy analysis"} or version.startswith("rules-") or version.startswith("legacy") or screening.get("decision") == "LEGACY_RULES_ENGINE"
    has_sif_identity = bool(screening.get("model_identity") and screening.get("model_hash"))
    has_lsr_identity = bool(mapping.get("model_version") and mapping.get("artifact_hash") and mapping.get("reference_id"))
    record_class = "legacy" if legacy else "current_model" if has_sif_identity and has_lsr_identity else "partial"
    stored_sif = {key: screening.get(key) for key in ("model_identity", "model_hash", "configuration_hash", "calibration_status", "thresholds")}
    stored_lsr = {key: mapping.get(key) for key in ("model_version", "artifact_hash", "reference_id", "schema_version", "coverage_complete", "unavailable_rule_ids")}
    try:
        active = classifier_metadata()
        current_model_compatible = record_class == "current_model" and stored_sif["model_identity"] == active.get("model_identity") and stored_sif["model_hash"] == active.get("model_hash")
    except Exception:
        current_model_compatible = False
    intelligence = analysis.get("intelligence") or {}
    return {
        "record_class": record_class,
        "label": {"current_model": "Current-model provenance", "partial": "Partial provenance", "legacy": "Legacy / historical record"}[record_class],
        "current_model_compatible": current_model_compatible,
        "sif": stored_sif,
        "lsr": stored_lsr,
        "evidence_status": "unavailable" if intelligence.get("status") in {"retrieval_unavailable", "legacy_unavailable"} else "stored" if "intelligence" in analysis else "not_stored",
        "formal_evaluation_eligible": False,
    }

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
    item["review_requirement"] = "required" if requires_human_review(item) else "not_required"
    item["effective_outcome"] = item["human_outcome"] or ("Pending human review" if requires_human_review(item) else item["model_outcome"])
    item["provenance"] = _stored_provenance(item["analysis"])
    item["formal_evaluation_eligible"] = False
    item["human_review_provenance"] = "operational_human_review" if item["human_outcome"] else None
    return item

def disposition_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
    automatic_positive = sum(x.get("model_outcome") == "SIF Potential" and x.get("human_outcome") is None and not requires_human_review(x) for x in reports)
    return {"model_positive_cases": sum(x.get("model_outcome") == "SIF Potential" for x in reports), "confirmed_sif_cases": sum(x.get("human_outcome") == "Confirm SIF" for x in reports), "confirmed_non_sif_cases": sum(x.get("human_outcome") == "Confirm Non-SIF" for x in reports), "unresolved_escalated": sum(x.get("human_outcome") == "Escalated / Unsure" for x in reports), "unreviewed_model_positive": automatic_positive, "unreviewed_automatic_positive": automatic_positive, "awaiting_human_review": sum(requires_human_review(x) for x in reports)}

def _incident_id(narrative: str) -> str: return "ANL-" + hashlib.sha1((narrative + datetime.now().isoformat()).encode()).hexdigest()[:8].upper()

def build_incident_record(*, narrative: str, site: str, activity: Optional[str], report_type: Optional[str], analysis: dict[str, Any], report_id: Optional[str] = None, report_date: Optional[str] = None, source: str = "user_analysis", import_batch_id: Optional[str] = None, auth_user: AuthenticatedUser | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    narrative = narrative.strip()
    if len(narrative) < 12: raise ValueError("narrative must contain at least 12 non-whitespace characters")
    resolved_site = (site or analysis.get("location") or "Unspecified").strip(); resolved_activity = (activity or analysis.get("activity") or "Unspecified").strip(); resolved_type = (report_type or "Unspecified").strip() or "Unspecified"
    if resolved_type not in REPORT_TYPES: raise ValueError("report_type must be Unsafe Act, Unsafe Condition, Near Miss, Incident, or Unspecified.")
    ident = report_id or _incident_id(narrative)
    record = {"id": ident, "report_date": report_date or str(date.today()), "site": resolved_site, "activity": resolved_activity, "narrative": narrative, "source": source, "source_id": (analysis.get("provenance") or {}).get("source_report_id"), "normalized_narrative": _normalized_narrative(narrative), "sif_probability": analysis["sif_probability"], "risk": analysis["risk"], "high_potential": analysis["high_potential"], "sif_potential": analysis["sif_potential"], "sif_label_status": analysis["sif_label_status"], "analysis": analysis, "review_status": "Pending" if analysis["review_required"] else "Not required", "reviewer": None, "review_comment": None, "created_at": datetime.now().isoformat(), "created_by_user_id": auth_user.id if auth_user else None, "report_type": resolved_type, "import_batch_id": import_batch_id}
    result = {"id": ident, "narrative": narrative, "site": resolved_site, "activity": resolved_activity, "report_type": resolved_type, **analysis}
    return record, result

def persist_incident(*, narrative: str, site: str, activity: Optional[str], report_type: Optional[str], analysis: dict[str, Any], report_id: Optional[str] = None, report_date: Optional[str] = None, source: str = "user_analysis", import_batch_id: Optional[str] = None, connection: Optional[sqlite3.Connection] = None, auth_user: AuthenticatedUser | None = None) -> dict[str, Any]:
    record, result = build_incident_record(narrative=narrative, site=site, activity=activity, report_type=report_type, analysis=analysis, report_id=report_id, report_date=report_date, source=source, import_batch_id=import_batch_id, auth_user=auth_user)
    try:
        get_database().insert_incident(record, connection=connection)
        if connection is not None:
            connection.commit()
    except Exception:
        if connection is not None: connection.rollback()
        raise
    return result

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
    result = []
    for evidence in retrieved:
        candidate = candidate_by_id[evidence["incident_id"]]; analysis = candidate.get("analysis") or {}
        assigned = [rule for rule in (analysis.get("lsr_mapping") or {}).get("rules", []) if rule.get("assignment_status") == "ASSIGNED"]
        rule_name = assigned[0]["name"] if assigned else (((analysis.get("rules") or {}).get("primary") or {}).get("rule", "Unmapped"))
        result.append({"similarity": evidence["relevance_score"], "relevance_score": evidence["relevance_score"], "incident_id": evidence["incident_id"], "source_id": evidence["source_id"], "title": evidence["title"], "site": candidate.get("site"), "activity": candidate.get("activity"), "risk": candidate.get("risk"), "life_saving_rule": rule_name, "retrieval_method": evidence["retrieval_method"], "corpus_version": evidence["corpus_version"], "label_provenance": evidence["label_provenance"]})
    return result

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
        result.append({"period": start.strftime("%d %b"), "high": sum(x["risk"] == "High" for x in period), "reviews": sum(requires_human_review(x) for x in period)})
    return result

def site_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for site in sorted({x["site"] for x in reports if x["site"]}):
        group = [x for x in reports if x["site"] == site]; anchor = report_anchor(group); high = sum(x["risk"] == "High" for x in group); current_sif_cases = sum(x.get("sif_potential") == 1 for x in group); model_positive = sum(x.get("model_outcome") == "SIF Potential" for x in group); effective_positive = sum(x.get("effective_outcome") in {"SIF Potential", "Confirm SIF"} for x in group); pending = sum(requires_human_review(x) for x in group); scores = [x["sif_probability"] for x in group if x["sif_probability"] is not None]; score_signal = sum(scores) / len(scores) if scores else 0; density = round(100 * model_positive / len(group), 1); index = min(100, round((high / len(group) * 55 + score_signal * 45) * 1.65 + pending * .7)); recent = sum(date.fromisoformat(x["report_date"]) >= anchor - timedelta(days=30) for x in group); prior = sum(anchor - timedelta(days=60) <= date.fromisoformat(x["report_date"]) < anchor - timedelta(days=30) for x in group); trend = "Rising" if recent > prior else "Declining" if recent < prior else "Stable"
        average = round(sum(scores) / len(scores), 2) if scores else None
        result.append({"site": site, "reports": len(group), "sif_cases": current_sif_cases, "model_positive_cases": model_positive, "effective_positive_cases": effective_positive, "sif_precursor_density": density, "avg_model_score": average, "pending_reviews": pending, "risk_index": index, "trend": trend, **disposition_counts(group)})
    return sorted(result, key=lambda x: (x["sif_precursor_density"], x["reports"]), reverse=True)

def activity_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for activity in sorted({x["activity"] for x in reports if x["activity"]}):
        group = [x for x in reports if x["activity"] == activity]; scores = [x["sif_probability"] for x in group if x["sif_probability"] is not None]; average = round(sum(scores) / len(scores), 2) if scores else None; current_sif_cases = sum(x.get("sif_potential") == 1 for x in group); model_positive = sum(x.get("model_outcome") == "SIF Potential" for x in group); effective_positive = sum(x.get("effective_outcome") in {"SIF Potential", "Confirm SIF"} for x in group)
        result.append({"activity": activity, "reports": len(group), "sif_cases": current_sif_cases, "model_positive_cases": model_positive, "effective_positive_cases": effective_positive, "sif_precursor_density": round(100 * model_positive / len(group), 1), "avg_model_score": average, "risk_index": min(100, round((average or 0) * 100)), **disposition_counts(group)})
    return sorted(result, key=lambda x: (x["sif_precursor_density"], x["reports"]), reverse=True)

def rule_stats(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}; provenance: dict[str, str] = {}
    for item in reports:
        analysis = item.get("analysis") or {}
        mapped = [rule for rule in (analysis.get("lsr_mapping") or {}).get("rules", []) if rule.get("assignment_status") == "ASSIGNED"]
        if mapped:
            for rule in mapped:
                counts[rule["name"]] = counts.get(rule["name"], 0) + 1
                provenance[rule["name"]] = "offline_multilabel_model"
        else:
            primary = (analysis.get("rules") or {}).get("primary")
            if primary:
                counts[primary["rule"]] = counts.get(primary["rule"], 0) + 1
                provenance.setdefault(primary["rule"], "unverified_keyword_candidate")
    return [{"rule": k, "count": v, "provenance": provenance[k]} for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)]

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
_cors_origins = []
for _cors_value in (os.getenv("CORS_ORIGINS", ""), os.getenv("FRONTEND_URL", "http://localhost:3000")):
    for _origin in _cors_value.split(","):
        _origin = _origin.strip().rstrip("/")
        _parsed_origin = urlsplit(_origin)
        if (_parsed_origin.scheme in {"http", "https"} and _parsed_origin.netloc
                and not _parsed_origin.path and not _parsed_origin.query and not _parsed_origin.fragment):
            _cors_origins.append(_origin)
_cors_origins = list(dict.fromkeys(_cors_origins))

@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    # Browsers send unauthenticated OPTIONS requests before cross-origin
    # requests. Let CORSMiddleware answer the preflight; actual application
    # requests remain protected below.
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path not in PUBLIC_UNAUTHENTICATED_PATHS:
        # Token verification currently uses the synchronous httpx client;
        # keep that network call off the event loop until the auth adapter is
        # migrated to a fully async client.
        user = await asyncio.to_thread(reviewer_for_request, request)
        if user is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        request.state.user = user
        request.state.reviewer = user.display_name or user.username
    return await call_next(request)

# Keep CORS outermost so allowed-origin headers are present on auth and
# application error responses as well as successful responses.
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

@app.on_event("startup")
def start() -> None: validate_configuration(); init_db(); get_domain_model().load(); get_retrieval_service()

def readiness_payload() -> tuple[dict[str, Any], bool]:
    metadata = classifier_metadata()
    domain = get_domain_model().metadata()
    try:
        database_status = get_database().healthcheck()
    except Exception as error:
        database_status = {"status": "UNAVAILABLE", "reason": type(error).__name__}
    checks = {"classifier": metadata["status"], "lsr_artifact": domain["lsr_status"], "database": database_status.get("status", "UNAVAILABLE")}
    ready = metadata["status"] == "READY" and domain["lsr_status"] == "READY" and database_status.get("status") == "READY"
    payload = {"status": "ready" if ready else "not_ready", "model_mode": "Frozen supervised classifier", "model_status": metadata["status"], "model_version": metadata["model_version"], "lsr_model_status": domain["lsr_status"], "lsr_model_version": domain["lsr_version"], "lsr_supported_rule_ids": domain.get("supported_rule_ids", []), "lsr_unavailable_rule_ids": domain.get("unavailable_rule_ids", []), "checks": checks, "llm_configured": False, "runtime_generative_llm_calls": False, "database": get_database().kind}
    return payload, ready

@app.get("/live")
def live():
    return {"status": "alive"}

@app.get("/ready")
@app.get("/health")
def health():
    payload, ready = readiness_payload()
    return JSONResponse(payload, status_code=200 if ready else 503)


def _registration_rate_limited(request: Request) -> bool:
    """Apply a conservative per-source limit until an edge limiter is configured."""
    try:
        limit = max(1, int(os.getenv("REGISTRATION_RATE_LIMIT", "5")))
        window = max(60, int(os.getenv("REGISTRATION_RATE_WINDOW_SECONDS", "3600")))
    except ValueError:
        limit, window = 5, 3600
    source = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _registration_attempts_lock:
        attempts = [timestamp for timestamp in _registration_attempts.get(source, []) if now - timestamp < window]
        limited = len(attempts) >= limit
        attempts.append(now)
        _registration_attempts[source] = attempts
    return limited


@app.post("/auth/register", status_code=201)
def register(registration: RegistrationInput, request: Request):
    if _registration_rate_limited(request):
        raise HTTPException(429, "Too many registration attempts. Please try again later.")
    try:
        email = username_to_internal_email(registration.user_id)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    database = get_database()
    try:
        if database.get_profile_by_username(registration.user_id):
            raise HTTPException(409, "That User ID is already registered.")
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, "Registration could not be completed.") from error
    auth_user: dict[str, str] | None = None
    try:
        auth_user = create_auth_user(email=email, password=registration.password, username=registration.user_id, display_name=registration.display_name)
        database.create_profile({"id": auth_user["id"], "username": registration.user_id, "display_name": registration.display_name, "role": "member"})
    except AuthProviderError as error:
        if auth_user:
            delete_auth_user(auth_user["id"])
        if error.conflict:
            raise HTTPException(409, "That User ID is already registered.") from error
        raise HTTPException(500, "Registration could not be completed.") from error
    except Exception as error:
        if auth_user:
            delete_auth_user(auth_user["id"])
        raise HTTPException(500, "Registration could not be completed.") from error
    return {"user_id": registration.user_id, "display_name": registration.display_name, "role": "member"}


def analyzed_result(report: AnalyzeInput, lsr_mapping: Optional[dict[str, Any]] = None, screening: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    analysis = analyze_with_classifier(report.narrative, analyze_text(report.narrative), screening_result=screening)
    analysis["lsr_mapping"] = lsr_mapping or get_domain_model().map_rules(report.narrative)
    analysis["intelligence"] = intelligence_snapshot(report.narrative)
    assigned = [{"rule": item.get("name", item.get("rule_id")), "rule_id": item.get("rule_id"), "name": item.get("name"), "evidence": item.get("evidence", []), "score": item.get("score"), "score_type": item.get("score_type"), "assignment_status": item.get("assignment_status"), "provenance": "active_lsr_classifier_and_narrative_evidence"}
                for item in analysis["lsr_mapping"].get("rules", []) if item.get("assignment_status") == "ASSIGNED"]
    reference_concepts = [{"rule": item["rule"], "evidence_id": item["evidence_id"],
                 "provenance": "grounded_iogp_reference", "mapping_basis": item.get("mapping_basis", "curated concept match; not an assignment")}
                for item in analysis["intelligence"]["reference_evidence"]
                if item.get("reference_type") == "iogp_reference" and item.get("rule")]
    analysis["rules"] = {"primary": assigned[0] if assigned else None, "secondary": assigned[1:], "assigned": assigned, "reference_concepts": reference_concepts, "assignment_contract": "assigned fields require active LSR score and submitted-narrative evidence; reference concepts are separate and are not assignments"}
    analysis["artifact_versions"] = {
        "sif_model": analysis.get("model_version"),
        "lsr_model": analysis["lsr_mapping"].get("model_version"),
        "lsr_reference": analysis["lsr_mapping"].get("reference_id"),
        "runtime_schema": analysis["lsr_mapping"].get("schema_version"),
    }
    return analysis

def analyzed_results(reports: list[AnalyzeInput]) -> list[dict[str, Any]]:
    service = get_domain_model(); narratives = [report.narrative for report in reports]
    screenings = service.classifier.screen_batch(narratives)
    mappings = service.map_rules_batch(narratives)
    return [analyzed_result(report, mapping, screening) for report, mapping, screening in zip(reports, mappings, screenings)]

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
    if len(batch_input.reports) > MAX_BATCH_REPORTS: raise HTTPException(422, f"Batch limit is {MAX_BATCH_REPORTS} reports.")
    database = get_database(); analyses = analyzed_results(batch_input.reports); batch_id = "BATCH-" + hashlib.sha1(datetime.now().isoformat().encode()).hexdigest()[:12].upper(); connection = con() if database.kind == "sqlite-test" else None; working_corpus = rows(); results = []; pending_records: list[dict[str, Any]] = []; skipped_duplicates = []; seen_keys: dict[tuple[str, str], str] = {}; seen_ids: dict[str, str] = {}
    try:
        for report, analysis in zip(batch_input.reports, analyses):
            site = (report.site or "Unspecified").strip() or "Unspecified"; normalized = _normalized_narrative(report.narrative); report_id = (report.report_id or "").strip() or None; duplicate = next((x for x in working_corpus if (report_id and str(x.get("id")) == report_id) or (_normalized_narrative(str(x.get("narrative") or "")) == normalized and str(x.get("site") or "Unspecified").casefold() == site.casefold())), None)
            if duplicate:
                skipped_duplicates.append({"report_id": report_id, "existing_id": duplicate.get("id"), "reason": "duplicate narrative/site or report ID"}); continue
            key = (normalized, site.casefold())
            if key in seen_keys or (report_id and report_id in seen_ids):
                skipped_duplicates.append({"report_id": report_id, "existing_id": seen_keys.get(key) or seen_ids.get(report_id or ""), "reason": "duplicate within upload"}); continue
            if database.kind == "supabase-postgres":
                record, result = build_incident_record(narrative=report.narrative, site=site, activity=report.activity, report_type=report.report_type, analysis=analysis, report_id=report_id, source=report.source or "user_analysis", import_batch_id=batch_id, auth_user=getattr(request.state, "user", None))
            else:
                record = None
                result = persist_incident(narrative=report.narrative, site=site, activity=report.activity, report_type=report.report_type, analysis=analysis, report_id=report_id, source=report.source or "user_analysis", import_batch_id=batch_id, connection=connection, auth_user=getattr(request.state, "user", None))
            result["intelligence"] = intelligence_snapshot(report.narrative, result["id"], working_corpus); analysis["intelligence"] = result["intelligence"]
            if record is not None:
                pending_records.append(record)
            else:
                _update_analysis_snapshot(result["id"], result["intelligence"], connection)
            result["similar_incidents"], result["similar_incidents_status"], result["similar_incidents_failure_reason"] = sim_with_status(result, corpus=working_corpus); working_corpus.append({**result, "analysis": analysis, "review_status": "Pending" if analysis["review_required"] else "Not required"}); seen_keys[key] = result["id"]; seen_ids[result["id"]] = result["id"]; results.append(result)
        if pending_records:
            database.insert_incidents_batch(pending_records)
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
    report_rows = rows(); site_rows = site_stats(report_rows); alert_rows = alerts(); counts = disposition_counts(report_rows); model_positive = counts["model_positive_cases"]; confirmed_sif = counts["confirmed_sif_cases"]; confirmed_non_sif = counts["confirmed_non_sif_cases"]; unresolved = counts["unresolved_escalated"]
    return {"reports_analyzed": len(report_rows), "potential_sif_cases": model_positive, "sif_case_basis": "frozen classifier screening; raw uncalibrated score", "confirmed_sif_cases": confirmed_sif, "confirmed_non_sif_cases": confirmed_non_sif, "unresolved_escalated": unresolved, "unreviewed_model_positive": counts["unreviewed_automatic_positive"], "unreviewed_automatic_positive": counts["unreviewed_automatic_positive"], "awaiting_human_review": counts["awaiting_human_review"], "high_risk_sites": sum(x["risk_index"] >= 58 for x in site_rows), "pending_reviews": counts["awaiting_human_review"], "operational_totals_include_legacy": True, "legacy_or_partial_records": sum(not x["provenance"]["current_model_compatible"] for x in report_rows), "current_model_compatible_records": sum(x["provenance"]["current_model_compatible"] for x in report_rows), "operational_risk_index": round(sum(x["risk_index"] for x in site_rows) / len(site_rows)) if site_rows else None, "emerging_alert": alert_rows[0]["title"] if alert_rows else None, "trend": trends(report_rows), "risk_distribution": [{"name": x, "value": sum(a["risk"] == x for a in report_rows)} for x in ["High", "Medium", "Low"]], "rules": rule_stats(report_rows)[:5], "sites": site_rows[:5], "activities": activity_stats(report_rows)[:5], "clusters": cluster_stats(report_rows)[:4]}

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
def reviews(): return [x for x in rows() if requires_human_review(x)]

@app.post("/reviews/{incident_id}")
def review(incident_id: str, review_input: ReviewInput, request: Request):
    outcome = REVIEW_OUTCOME_ALIASES.get(review_input.outcome.strip())
    if outcome is None: raise HTTPException(422, "Use Confirm SIF, Confirm Non-SIF, or Escalated / Unsure.")
    user = getattr(request.state, "user", None)
    if user is not None and user.role not in {"reviewer", "admin"}:
        raise HTTPException(403, "Reviewer permission is required.")
    reviewer = (user.display_name if user else None) or review_input.reviewer.strip()
    if len(reviewer) < 2: raise HTTPException(422, "Reviewer identity is required.")
    current = get_database().get_incident(incident_id)
    if not current: raise HTTPException(404, "Report not found")
    previous = human_review_outcome(current)
    status = "Escalated" if outcome == "Escalated / Unsure" else "Reviewed"; sif_value = 1 if outcome == "Confirm SIF" else 0 if outcome == "Confirm Non-SIF" else None; label_status = "operational_human_reviewed" if sif_value is not None else "operational_unresolved"; analysis = current.get("analysis") or {}; analysis = json.loads(analysis) if isinstance(analysis, str) else analysis; screening_version = (analysis.get("screening") or {}).get("model_identity") or analysis.get("model_version")
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
    domain = get_domain_model().metadata()
    return {"mode": "Supervised screening classifier plus offline multilabel IOGP mapper", "version": metadata["model_version"], "model_identity": metadata["model_identity"], "model_hash": metadata["model_hash"], "configuration_hash": metadata["configuration_hash"], "status": metadata["status"], "thresholds": metadata["thresholds"], "calibration_status": metadata["calibration_status"], "calibration": {"status": "incomplete", "evidence_population": None, "requirement": "independent human-labelled development data; never the final blind test", "metrics": None}, "llm_configured": False, "runtime_generative_llm_calls": False, "lsr_model": domain, "authorization_scope": "authenticated workspace access; profiles are not tenant-isolated", "screening_claim": "uncalibrated screening score; not an accident probability; automatic positives may be false alarms", "provenance": "Active screening classifier and deterministic evidence templates.", "external_evaluation": "Human blind validation is pending locked adjudications.", "metrics": None, "human_blind_test": {"status": "pending_locked_adjudications", "sample_size": None, "unresolved_exclusions": None, "metrics": None}, "fallback": "Inference or unsupported-rule failures are explicit and never converted to a negative result."}
