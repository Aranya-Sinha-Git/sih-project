"""Create the one official v0.3 attestation after adjudication finalization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_blind_test_v0_3 import (
    FINALIZATION_POLICY, MANIFEST_NAME, OFFICIAL_ATTESTATION_NAME,
    OFFICIAL_FINALIZATION_MANIFEST_NAME, OFFICIAL_FINALIZED_PACKET_NAME, OUT,
    sha256,
)
from evaluate_human import (
    CANONICAL_MANIFEST_SHA256, EVALUATOR_SCHEMA_VERSION, EvaluationError,
    _git_resolved_commit, _read_csv, _read_json, _require_date,
    _require_finalization_manifest, canonical_manifest,
)


ATTESTATION_SCHEMA_VERSION = "blind-human-official-attestation-v0.3"


def attest(*, git_commit_sha: str, git_tag: str, attested_at_utc: str) -> dict:
    canonical = canonical_manifest()
    packet = OUT / OFFICIAL_FINALIZED_PACKET_NAME
    finalization = OUT / OFFICIAL_FINALIZATION_MANIFEST_NAME
    output = OUT / OFFICIAL_ATTESTATION_NAME
    if output.exists():
        raise FileExistsError("The official v0.3 attestation is immutable and already exists.")
    if not packet.is_file() or not finalization.is_file():
        raise EvaluationError("Official finalization artifacts are required before attestation.")
    finalization_doc = _read_json(finalization, "Official finalization manifest")
    if finalization_doc.get("status") != "adjudication_finalized" or finalization_doc.get("evaluator_schema_version") != EVALUATOR_SCHEMA_VERSION:
        raise EvaluationError("Official finalization manifest is not evaluator-compatible.")
    _require_finalization_manifest(finalization, packet, _read_csv(packet), canonical)
    _require_date(attested_at_utc, "attested_at_utc", "official attestation")
    commit = _git_resolved_commit(git_commit_sha.strip())
    import subprocess
    try:
        tag_result = subprocess.run(["git", "rev-parse", "--verify", f"{git_tag.strip()}^{{commit}}"], cwd=Path(__file__).resolve().parents[4], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise EvaluationError("Official Git tag cannot be verified locally.") from error
    if tag_result.stdout.strip() != commit:
        raise EvaluationError("Official Git tag does not resolve to the attested commit.")
    counts = finalization_doc.get("counts")
    if not isinstance(counts, dict):
        raise EvaluationError("Official finalization counts are missing.")
    result = {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "status": "official_attested",
        "release_version": canonical["release_version"],
        "canonical_release_manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "finalized_packet_sha256": sha256(packet),
        "finalization_manifest_sha256": sha256(finalization),
        "finalization_policy_sha256": sha256(FINALIZATION_POLICY),
        "counts": counts,
        "git_commit_sha": commit,
        "git_tag": git_tag.strip(),
        "attested_at_utc": attested_at_utc,
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Attest the designated official v0.3 human evaluation.")
    parser.add_argument("--git-commit-sha", required=True)
    parser.add_argument("--git-tag", required=True)
    parser.add_argument("--attested-at-utc", required=True)
    args = parser.parse_args()
    print(json.dumps(attest(git_commit_sha=args.git_commit_sha, git_tag=args.git_tag, attested_at_utc=args.attested_at_utc), indent=2))


if __name__ == "__main__":
    main()
