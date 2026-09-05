from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

from process_all import ROOT


SOURCES = [
    ("https://www.osha.gov/sites/default/files/January2015toNovember2025.zip", "04_OSHA/SEVERE_INJURY_RAW/osha_sir_jan2015_nov2025.zip"),
    ("https://www.data.bsee.gov/Other/Files/IncInvRawData.zip", "05_BSEE/RAW/bsee_incident_investigations_raw.zip"),
]


def download(url: str, relative: str, retries: int = 3) -> None:
    dest = ROOT / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print(f"SKIP {relative}")
        return
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                data = response.read()
            if not data:
                raise ValueError("zero-byte response")
            dest.write_bytes(data)
            print(f"OK {relative} {len(data)} bytes")
            return
        except Exception as exc:
            print(f"FAIL attempt={attempt+1} {url}: {exc}")
            time.sleep(2 ** attempt)
    raise RuntimeError(f"could not download {url}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Idempotent downloader for non-gated official sources.")
    ap.add_argument("--all", action="store_true", help="download the small verified source list")
    args = ap.parse_args()
    if not args.all:
        ap.error("pass --all; gated sources are intentionally excluded")
    for url, path in SOURCES:
        download(url, path)
