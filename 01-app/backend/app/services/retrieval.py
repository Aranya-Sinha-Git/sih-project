"""Grounded TF-IDF retrieval for public references and historical reports."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


CATALOG_PATH = Path(__file__).resolve().parents[1] / "reference" / "knowledge_catalog.json"
VALIDATION_POLICY_PATH = Path(__file__).resolve().parents[1] / "reference" / "validation_policy.json"
DEFAULT_CORPUS_VERSION = "unknown"


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def _spans(query: str, text: str) -> list[str]:
    terms = {token.casefold() for token in re.findall(r"[a-z0-9]{4,}", query.casefold())}
    return [sentence for sentence in _sentences(text) if terms & set(re.findall(r"[a-z0-9]{4,}", sentence.casefold()))] or _sentences(text)[:1]


def _rank(query: str, documents: list[str], limit: int, minimum: float) -> list[tuple[int, float]]:
    if not query.strip() or not documents:
        return []
    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    try:
        matrix = vectorizer.fit_transform([query, *documents])
    except ValueError:
        return []
    scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
    return [(index, float(score)) for index, score in sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)[:limit] if score >= minimum]


class RetrievalService:
    def __init__(self, catalog_path: Path = CATALOG_PATH) -> None:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.corpus_version = payload.get("corpus_version", DEFAULT_CORPUS_VERSION)
        self.references = payload.get("references", [])
        self.glossary = payload.get("glossary", [])
        policy = json.loads(VALIDATION_POLICY_PATH.read_text(encoding="utf-8"))
        self.locked_sources = {str(value).strip().casefold() for value in policy["locked_sources"] if str(value).strip()}
        self.locked_record_flags = {str(value).strip() for value in policy["locked_record_flags"] if str(value).strip()}

    def reference_evidence(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        documents = [f"{item.get('title','')} {' '.join(item.get('aliases', []))} {item.get('text','')}" for item in self.references]
        documents += [f"{item.get('term','')} {item.get('meaning','')}" for item in self.glossary]
        ranked = _rank(query, documents, limit, 0.08)
        evidence = []
        for index, score in ranked:
            item = self.references[index] if index < len(self.references) else self.glossary[index - len(self.references)]
            is_glossary = index >= len(self.references)
            evidence.append({"evidence_id": item.get("evidence_id") or f"OIL-GLOSSARY-{str(item.get('term','unknown')).upper().replace(' ', '-')}", "rule": item.get("rule"), "title": item.get("title") or item.get("term"), "excerpt": item.get("text") or item.get("meaning"), "narrative_spans": _spans(query, item.get("text") or item.get("meaning", "")), "relevance_score": round(score, 4), "retrieval_method": "tfidf_cosine", "corpus_version": self.corpus_version, "reference_type": "oil_glossary" if is_glossary else "iogp_reference", "citation": {"publisher": item.get("publisher"), "source_url": item.get("source_url"), "document_version": item.get("document_version"), "page_section": item.get("page_section")}})
        return evidence

    def historical_evidence(self, query: str, incidents: Iterable[dict[str, Any]], limit: int = 5, locked_ids: set[str] | None = None, current_source_id: str | None = None) -> list[dict[str, Any]]:
        locked_ids = locked_ids or set()
        candidates: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        seen_narratives: set[str] = set()
        for incident in incidents:
            incident_id = str(incident.get("id") or incident.get("incident_id") or "")
            source_id = str(incident.get("source_id") or incident_id)
            locked_by_flag = any(bool(incident.get(flag)) for flag in self.locked_record_flags)
            locked_by_source = str(incident.get("source") or "").strip().casefold() in self.locked_sources
            if not incident_id or incident_id in locked_ids or source_id == str(current_source_id or "") or locked_by_flag or locked_by_source:
                continue
            if source_id in seen_sources:
                continue
            normalized = " ".join(str(incident.get("narrative") or "").casefold().split())
            if normalized and normalized in seen_narratives:
                continue
            seen_sources.add(source_id)
            seen_narratives.add(normalized)
            candidates.append(incident)
        ranked = _rank(query, [str(item.get("narrative") or "") for item in candidates], limit, 0.12)
        return [{"incident_id": item.get("id") or item.get("incident_id"), "source_id": item.get("source_id") or item.get("id") or item.get("incident_id"), "title": str(item.get("narrative") or "")[:115], "excerpt": str(item.get("narrative") or "")[:400], "narrative_spans": _spans(query, str(item.get("narrative") or "")), "relevance_score": round(score, 4), "retrieval_method": "tfidf_cosine", "corpus_version": self.corpus_version, "label_provenance": item.get("sif_label_status") or "unavailable"} for index, score in ranked for item in [candidates[index]]]


def get_retrieval_service() -> RetrievalService:
    return RetrievalService()
