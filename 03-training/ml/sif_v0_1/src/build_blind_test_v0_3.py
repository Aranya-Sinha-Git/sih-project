"""Create the immutable v0.3 freeze from the unchanged v0.2 release.

v0.3 deliberately reuses the v0.2 75-record packet byte-for-byte.  It adds
the immutable finalization policy anchor and fixed official artifact names;
the v0.2 directory is never modified.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from build_blind_test_v0_2 import CANDIDATES, DATA, ML_ROOT, ROOT, ARTIFACTS, PREPROCESSING


RELEASE_VERSION = "v0.3"
DATASET = "blind_test_v0_3"
TARGET_COUNT = 75
OUT = DATA / DATASET
V2_OUT = DATA / "blind_test_v0_2"
V2_PACKET = V2_OUT / "blind_test_v0_2_reviewer_packet.csv"
V2_MANIFEST = V2_OUT / "blind_test_v0_2_freeze_manifest.json"
PACKET_NAME = "blind_test_v0_3_reviewer_packet.csv"
MANIFEST_NAME = "blind_test_v0_3_freeze_manifest.json"
EXCLUSION_AUDIT_NAME = "blind_test_v0_3_exclusion_audit.json"
OFFICIAL_FINALIZED_PACKET_NAME = "blind_test_v0_3_finalized_reviewer_packet.csv"
OFFICIAL_FINALIZATION_MANIFEST_NAME = "blind_test_v0_3_finalization_manifest.json"
OFFICIAL_ATTESTATION_NAME = "blind_test_v0_3_official_attestation.json"
FINALIZATION_POLICY = ROOT / "01-app" / "backend" / "app" / "reference" / "human_review_finalization_policy.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_release() -> dict:
    if OUT.exists():
        raise FileExistsError(f"Release directory already exists and is immutable: {OUT}")
    if not V2_PACKET.is_file() or not V2_MANIFEST.is_file():
        raise FileNotFoundError("The frozen v0.2 packet and manifest are required.")
    v2 = json.loads(V2_MANIFEST.read_text(encoding="utf-8"))
    policy = json.loads(FINALIZATION_POLICY.read_text(encoding="utf-8"))
    if v2.get("release_version") != "v0.2" or v2.get("dataset") != "blind_test_v0_2":
        raise ValueError("Unexpected v0.2 source release.")
    if len(v2.get("records", [])) != TARGET_COUNT:
        raise ValueError("The v0.2 source release does not contain 75 records.")
    if int(policy.get("minimum_retained_records", 0)) < 1:
        raise ValueError("Finalization policy has no positive retained-record floor.")
    OUT.mkdir(parents=True, exist_ok=False)
    packet_path = OUT / PACKET_NAME
    packet_path.write_bytes(V2_PACKET.read_bytes())
    exclusion_audit = json.loads((V2_OUT / "blind_test_v0_2_exclusion_audit.json").read_text(encoding="utf-8"))
    exclusion_audit["dataset"] = DATASET
    (OUT / EXCLUSION_AUDIT_NAME).write_text(json.dumps(exclusion_audit, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "blind-human-freeze-v0.3",
        "release_version": RELEASE_VERSION,
        "dataset": DATASET,
        "release_status": "frozen_unscored",
        "created_at_utc": "2026-09-05T00:00:00+00:00",
        "source_release": {"release_version": "v0.2", "manifest_sha256": sha256(V2_MANIFEST), "packet_sha256": sha256(V2_PACKET)},
        "canonical_packet": {"filename": PACKET_NAME, "sha256": sha256(packet_path)},
        "finalization_policy": {
            "filename": str(FINALIZATION_POLICY.relative_to(ROOT)).replace("\\", "/"),
            "version": policy["version"],
            "sha256": sha256(FINALIZATION_POLICY),
            "minimum_retained_records": int(policy["minimum_retained_records"]),
            "approved_exclusion_reasons": policy["approved_exclusion_reasons"],
        },
        "official_artifacts": {
            "finalized_packet": OFFICIAL_FINALIZED_PACKET_NAME,
            "finalization_manifest": OFFICIAL_FINALIZATION_MANIFEST_NAME,
            "attestation": OFFICIAL_ATTESTATION_NAME,
        },
        "candidate_pool": v2["candidate_pool"],
        "validation_policy": v2["validation_policy"],
        "frozen_model": v2["frozen_model"],
        "records": v2["records"],
        "integrity": v2["integrity"],
    }
    (OUT / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build_release(), indent=2))
