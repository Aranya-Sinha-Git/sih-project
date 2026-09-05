"""Shared, conservative text and CSV helpers for SIF NLP v0.1."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path


def normalize_text(value: object) -> str:
    """Normalize only formatting for duplicate detection; retain technical content."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", " ").lower()
    return re.sub(r"\s+", " ", text).strip()


def clean_narrative(value: object) -> str:
    """Return whitespace-normalized triage text without deleting negation, units, or numbers."""
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def text_hash(value: object) -> str:
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]
