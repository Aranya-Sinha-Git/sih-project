import csv
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parents[3] / "04-data" / "demo-datasets" / "judge_demo_v0_1"
os.environ.setdefault("SIF_TEST_AUTH_BYPASS", "1")
os.environ.setdefault("SIF_ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(tempfile.mkdtemp(prefix='judge_demo_test_')) / 'test.db'}")


def test_judge_demo_upload_quotas_and_schema():
    rows = list(csv.DictReader((DEMO_DIR / "judge_demo_500.csv").open(encoding="utf-8")))
    assert len(rows) == 500
    assert list(rows[0]) == ["report_id", "report_date", "site", "activity", "report_type", "narrative", "source"]
    assert [row["report_id"] for row in rows] == [f"DEMO500-{index:04d}" for index in range(1, 501)]
    assert Counter(row["report_type"] for row in rows) == Counter({"Near Miss": 180, "Unsafe Condition": 130, "Incident": 100, "Unsafe Act": 90})
    assert Counter(row["site"] for row in rows) == Counter({"Aurora Basin": 100, "Blue Mesa Yard": 90, "Cedar Ridge Station": 85, "Delta Point Facility": 80, "Echo Valley Works": 75, "Frostline Depot": 70})
    assert Counter(row["activity"] for row in rows) == Counter({"Valve Maintenance": 90, "Mechanical Lifting": 75, "Drilling": 65, "Pressure Testing": 60, "Driving": 60, "Hot Work": 55, "Inspection": 50, "Electrical Maintenance": 45})
    assert all(70 <= len(re.findall(r"\b\w+[\w/-]*\b", row["narrative"])) <= 140 for row in rows)
    assert all(date.fromisoformat(row["report_date"]) <= date.today() for row in rows)
    assert len({(" ".join(row["narrative"].casefold().split()), row["site"].casefold()) for row in rows}) == 500
    assert all(row["source"] == "synthetic_judge_demo_v0_1" for row in rows)


def test_judge_demo_xlsx_preserves_typed_report_dates():
    from openpyxl import load_workbook

    workbook = load_workbook(DEMO_DIR / "judge_demo_500.xlsx", read_only=True, data_only=True)
    sheet = workbook.active
    first_date = sheet["B2"].value
    last_date = sheet["B501"].value
    workbook.close()
    assert first_date.date().isoformat() == "2026-08-12"
    assert last_date.date().isoformat() == "2026-08-07"


def test_judge_demo_runtime_profile_and_manifest_are_release_gated():
    profile = json.loads((DEMO_DIR / "judge_demo_runtime_profile.json").read_text(encoding="utf-8"))
    manifest = json.loads((DEMO_DIR / "judge_demo_500_manifest.json").read_text(encoding="utf-8"))
    assert profile["status"] == "PASS"
    assert manifest["status"] == "synthetic_non_validation"
    assert manifest["synthetic"] is True
    assert manifest["row_count"] == 500
    assert manifest["duplicate_checks"]["duplicate_normalized_narrative_site_pairs"] == 0
    assert all(value >= 10 for value in profile["observed"]["supported_lsr_assignments"].values())
    assert set(profile["observed"]["unavailable_lsr_rule_ids"]) == {"LSR01", "LSR02", "LSR08"}
    assert len(profile["observed"]["unavailable_lsr_examples"]) == 3
    assert len(profile["observed"]["recurring_precursor_clusters"]) >= 3
    assert all(value >= 8 for value in profile["observed"]["related_nonduplicate_cohorts"].values())
    assert profile["observed"]["meaningful_hazard_extraction_percentage"] >= 90
    for filename, details in manifest["files"].items():
        digest = hashlib.sha256((DEMO_DIR / filename).read_bytes()).hexdigest()
        assert digest == details["sha256"]


def test_report_date_validation_aliases_and_site_trends():
    from pydantic import ValidationError

    from app.main import AnalyzeInput, site_stats

    assert AnalyzeInput.model_validate({"narrative": "A valid date alias narrative.", "date": "2026-09-01"}).report_date == "2026-09-01"
    assert AnalyzeInput.model_validate({"narrative": "A valid report date narrative.", "ReportDate": "2026-09-01"}).report_date == "2026-09-01"
    for value in ("2026/09/01", "2026-02-30", "20260901", date.today().replace(year=date.today().year + 1).isoformat()):
        try:
            AnalyzeInput.model_validate({"narrative": "A date validation narrative.", "report_date": value})
        except ValidationError:
            pass
        else:
            raise AssertionError(f"invalid date accepted: {value}")

    rows = []
    for site, recent, prior, expected in (("Rising", 8, 2, "Rising"), ("Stable", 5, 5, "Stable"), ("Declining", 2, 8, "Declining")):
        rows.extend({"site": site, "report_date": f"2026-09-{10 - recent + index:02d}", "risk": "High", "sif_potential": 1, "sif_probability": 0.8, "model_outcome": "SIF Potential", "review_status": "Not required"} for index in range(1, recent + 1))
        rows.extend({"site": site, "report_date": f"2026-08-{index:02d}", "risk": "Low", "sif_potential": 0, "sif_probability": 0.2, "model_outcome": "Non-SIF Potential", "review_status": "Not required"} for index in range(1, prior + 1))
    trend_by_site = {row["site"]: row["trend"] for row in site_stats(rows)}
    assert trend_by_site == {"Rising": "Rising", "Stable": "Stable", "Declining": "Declining"}
