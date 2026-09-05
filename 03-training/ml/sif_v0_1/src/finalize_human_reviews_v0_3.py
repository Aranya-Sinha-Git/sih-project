"""Finalize the single designated v0.3 official packet location.

This step writes only the canonical finalized packet and finalization manifest.
It does not write the official attestation; that is a separate post-finalization
step and evaluation remains unavailable until that attestation exists.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_blind_test_v0_3 import (
    OFFICIAL_FINALIZATION_MANIFEST_NAME, OFFICIAL_FINALIZED_PACKET_NAME, OUT,
)
from finalize_human_reviews import finalize


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize the designated v0.3 official reviewer packet.")
    parser.add_argument("--completed-packet", type=Path, required=True)
    parser.add_argument("--finalized-by", required=True)
    parser.add_argument("--finalized-at-utc", required=True)
    parser.add_argument("--git-commit-sha", required=True)
    parser.add_argument("--git-tag", required=True)
    args = parser.parse_args()
    manifest = finalize(
        args.completed_packet,
        OUT / OFFICIAL_FINALIZED_PACKET_NAME,
        OUT / OFFICIAL_FINALIZATION_MANIFEST_NAME,
        finalized_by=args.finalized_by,
        finalized_at_utc=args.finalized_at_utc,
        git_commit_sha=args.git_commit_sha,
        git_tag=args.git_tag,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
