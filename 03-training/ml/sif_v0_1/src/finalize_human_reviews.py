"""Finalize a completed v0.2 reviewer packet without running model scoring.

This command is the only writer of finalization manifests.  It validates the
canonical release and adjudication structure, then writes a separately named,
canonicalized completed packet and immutable-content manifest.  It never
modifies the canonical blank packet or freeze manifest.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evaluate_human import (
    CANONICAL_MANIFEST_SHA256,
    EVALUATOR_SCHEMA_VERSION,
    FINALIZATION_POLICY,
    FINALIZATION_SCHEMA_VERSION,
    EvaluationError,
    _read_csv,
    canonical_packet_bytes,
    finalization_policy,
    finalized_packet_sha256,
    review_provenance,
    sha256,
    validate_completed_packet,
)


def build_finalization_manifest(
    rows: list[dict[str, str]], *, finalized_packet_name: str, finalized_by: str,
    finalized_at_utc: str, git_commit_sha: str | None = None, git_tag: str | None = None,
) -> dict[str, Any]:
    if not finalized_packet_name or not finalized_by.strip():
        raise EvaluationError("A finalized packet name and finalizer identity are required.")
    canonical, _, retained, exclusions = validate_completed_packet(rows)
    policy = finalization_policy()
    # Reuse the evaluator's ISO-8601 validation through the public validation
    # path rather than substituting a wall-clock timestamp.
    from evaluate_human import _require_date
    _require_date(finalized_at_utc, "finalized_at_utc", "finalization")
    return {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "status": "adjudication_finalized",
        "release_version": canonical["release_version"],
        "canonical_blind_release": {
            "dataset": canonical["dataset"],
            "release_version": canonical["release_version"],
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        },
        "finalized_reviewer_packet": {
            "filename": finalized_packet_name,
            "canonical_content_sha256": finalized_packet_sha256(rows),
            "canonical_serialization": "csv-utf8-lf-schema-v1-sorted-test-id",
        },
        "finalization_policy": {
            "filename": str(FINALIZATION_POLICY),
            "version": policy["version"],
            "sha256": sha256(FINALIZATION_POLICY),
            "minimum_retained_records": policy["minimum_retained_records"],
        },
        "counts": {
            "frozen_records": 75,
            "retained_records": len(retained),
            "excluded_records": len(exclusions),
            "evaluated_records": len(retained),
        },
        "exclusions": exclusions,
        "review_provenance": review_provenance(rows),
        "finalized_by": finalized_by.strip(),
        "finalized_at_utc": finalized_at_utc,
        "evaluator_schema_version": EVALUATOR_SCHEMA_VERSION,
        "external_attestation": {
            "git_commit_sha": git_commit_sha.strip() if git_commit_sha else None,
            "git_tag": git_tag.strip() if git_tag else None,
        },
    }


def finalize(
    completed_packet: Path, finalized_packet: Path, finalization_manifest: Path,
    *, finalized_by: str, finalized_at_utc: str, git_commit_sha: str | None = None,
    git_tag: str | None = None,
) -> dict[str, Any]:
    if finalized_packet.exists() or finalization_manifest.exists():
        raise FileExistsError("Finalized packet and finalization manifest paths must be new; finalizations are immutable.")
    if completed_packet.resolve() in {finalized_packet.resolve(), finalization_manifest.resolve()}:
        raise EvaluationError("Completed input packet must be distinct from finalization outputs.")
    rows = _read_csv(completed_packet)
    manifest = build_finalization_manifest(
        rows, finalized_packet_name=finalized_packet.name, finalized_by=finalized_by,
        finalized_at_utc=finalized_at_utc, git_commit_sha=git_commit_sha, git_tag=git_tag,
    )
    finalized_packet.parent.mkdir(parents=True, exist_ok=True)
    finalization_manifest.parent.mkdir(parents=True, exist_ok=True)
    finalized_packet.write_bytes(canonical_packet_bytes(rows))
    manifest["finalized_reviewer_packet"]["packet_file_sha256"] = sha256(finalized_packet)
    finalization_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize a completed v0.2 human-review packet without scoring it.")
    parser.add_argument("--completed-packet", type=Path, required=True)
    parser.add_argument("--finalized-packet", type=Path, required=True)
    parser.add_argument("--finalization-manifest", type=Path, required=True)
    parser.add_argument("--finalized-by", required=True)
    parser.add_argument("--finalized-at-utc", required=True, help="Explicit ISO-8601 timestamp; never inferred from scoring.")
    parser.add_argument("--git-commit-sha")
    parser.add_argument("--git-tag")
    args = parser.parse_args()
    print(json.dumps(finalize(
        args.completed_packet, args.finalized_packet, args.finalization_manifest,
        finalized_by=args.finalized_by, finalized_at_utc=args.finalized_at_utc,
        git_commit_sha=args.git_commit_sha, git_tag=args.git_tag,
    ), indent=2))


if __name__ == "__main__":
    main()
