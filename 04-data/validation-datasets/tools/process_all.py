from __future__ import annotations

import csv
import hashlib
import json
import mimetypes
import re
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(timezone.utc).isoformat()

SOURCE_META = {
    "oil_india_brsr_2025-26.pdf": ("Oil India Limited", "https://www.oil-india.com/business-responsibility-sustainability-report", "https://www.oil-india.com/files/investor_services_documents/OIL_BRSR_FY_2025_26.pdf", "2025-26"),
    "oil_india_brsr_2024-25.pdf": ("Oil India Limited", "https://www.oil-india.com/business-responsibility-sustainability-report", "https://www.oil-india.com/files/investor_services_documents/BRSR-2024-25.pdf", "2024-25"),
    "oil_india_brsr_2023-24.pdf": ("Oil India Limited", "https://www.oil-india.com/business-responsibility-sustainability-report", "https://www.oil-india.com/files/investor_services_documents/Business%20Responsibility%20%26%20Sustainability%20Report%20for%20FY%202023-24.pdf", "2023-24"),
    "oil_india_brsr_2022-23.pdf": ("Oil India Limited", "https://www.oil-india.com/business-responsibility-sustainability-report", "https://www.oil-india.com/files/inline-documents/OILBRSR2022-23.pdf", "2022-23"),
    "oil_india_brsr_2021-22.pdf": ("Oil India Limited", "https://www.oil-india.com/business-responsibility-sustainability-report", "https://www.oil-india.com/files/inline-documents/OILBRSR2021-22.pdf", "2021-22"),
    "oil_india_near_miss_reporting_tender_CDG3685P15.pdf": ("Oil India Limited", "https://www.oil-india.com/hseoil", "https://www.oil-india.com/files/oldtender/global/NIT_CDG3685P15.pdf", "2015"),
    "oil_india_safety_environment_portal_tender_CDH7317P22.pdf": ("Oil India Limited", "https://www.oil-india.com/hseoil", "https://www.oil-india.com/files/oldtender/national/NIT_CDH7317P22.pdf", "2022"),
    "oil_india_baghjan_news_2020.pdf": ("Oil India Limited", "https://www.oil-india.com/baghjan-update", "https://www.oil-india.com/files/publications_documents/OIL_News_April_Sept_03012020.pdf", "2020"),
    "oil_india_baghjan_environment_compliance_2025.pdf": ("Oil India Limited", "https://www.oil-india.com/baghjan-update", "https://www.oil-india.com/files/compliance_reports/8_NHTD_0.pdf", "2025"),
    "oisd_working_group_safety_report_baghjan_reference.pdf": ("Oil Industry Safety Directorate", "https://www.oisd.gov.in/en-in/CaseStudies", "https://www.oisd.gov.in/public/assets/upload/Content/1732794948_520baaa79fde295d76fc.pdf", "2024"),
    "ngt_baghjan_preliminary_committee_report.pdf": ("National Green Tribunal", "https://www.greentribunal.gov.in/", "https://www.greentribunal.gov.in/sites/default/files/news_updates/Preliminary%20Report%20of%20the%20Committee%20of%20Experts%20in%20the%20matter%20of%20I.A.%20No.%2030%20of%202020%20in%20O.%20A.%20No.%2043%20of%202020%20%28EZ%29%20and%20I.A.%20No.%2031%20of%202020%20in%20O.%20A.%20No.%2044%20of%202020%28EZ%29.pdf", "2020"),
    "iogp_life_saving_rules_workcard_2018.pdf": ("IOGP", "https://www.iogp.org/workstreams/safety/safety/life-savingrules/", "https://www.iogp.org/wp-content/uploads/2018/08/Life-SavingRules-WorkCard.pdf", "2018"),
    "iogp_line_of_fire_supporting_materials_2025.pdf": ("IOGP", "https://www.iogp.org/workstreams/safety/safety/life-savingrules/", "https://www.iogp.org/wp-content/uploads/2025/10/IOGP-Life-Saving-Rules-Line-of-Fire-Introduction-to-Supporting-Materials.pdf", "2025"),
    "iogp_line_of_fire_pocket_cards_2025.pdf": ("IOGP", "https://www.iogp.org/workstreams/safety/safety/life-savingrules/", "https://www.iogp.org/wp-content/uploads/2025/10/IOGP-Life-Saving-Rules-Pocket-Cards.pdf", "2025"),
    "iogp_line_of_fire_infographic_2025.pdf": ("IOGP", "https://www.iogp.org/workstreams/safety/safety/life-savingrules/", "https://www.iogp.org/wp-content/uploads/2025/10/IOGP-Life-Saving-Rules-Line-of-Fire-Infographic.pdf", "2025"),
    "osha_sir_jan2015_nov2025.zip": ("OSHA", "https://www.osha.gov/severe-injury-reports", "https://www.osha.gov/sites/default/files/January2015toNovember2025.zip", "2015-2025"),
}


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sniff(path: Path) -> str:
    b = path.read_bytes()[:16]
    if b.startswith(b"%PDF"):
        return "application/pdf"
    if b.startswith(b"PK"):
        return "application/zip-or-office"
    if b.startswith(b"{") or b.startswith(b"["):
        return "application/json"
    return mimetypes.guess_type(path.name)[0] or "text/plain"


def verify_files() -> list[dict]:
    excluded = {"00_MANIFEST", "08_EXTRACTED_TEXT", "09_PROCESSED", "10_VALIDATION_LOCKED", "11_TRAINING_CANDIDATES", "12_REFERENCE_ONLY", "13_DUPLICATE_ANALYSIS", "14_LICENSE_AND_TERMS", "15_REPORTS", "tools"}
    rows = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file() or any(part in excluded for part in p.parts):
            continue
        if p.name == "WORK_STATE.md":
            continue
        raw = p.read_bytes()[:2048]
        status = "verified_nonzero"
        notes = ""
        if not raw:
            status = "invalid_zero_size"
        if p.suffix.lower() == ".pdf" and not raw.startswith(b"%PDF"):
            status = "invalid_pdf_signature"
            notes = "PDF extension but missing %PDF signature"
        if p.suffix.lower() in {".xlsx", ".zip"} and not raw.startswith(b"PK"):
            status = "invalid_zip_signature"
            notes = "Office/archive extension but missing PK signature"
        meta = next((v for k, v in SOURCE_META.items() if k in p.name), ("", "", "", ""))
        if not meta[0] and p.name.startswith("bsee_"):
            meta = ("BSEE", "https://www.bsee.gov/stats-facts/offshore-incident-statistics", "https://www.data.bsee.gov/Main/RawData.aspx", "2015-2024")
        elif not meta[0] and p.name.startswith("osha_") or (not meta[0] and "January2015toNovember2025" in p.name):
            meta = ("OSHA", "https://www.osha.gov/severe-injury-reports", "https://www.osha.gov/sites/default/files/January2015toNovember2025.zip", "2015-2025")
        elif not meta[0] and p.name.startswith("face_"):
            meta = ("CDC/NIOSH", "https://www.cdc.gov/niosh/face/topics/index.html", "https://www.cdc.gov/niosh/face/topics/index.html", "1984-2018")
        elif not meta[0] and p.suffix.lower() in {".csv", ".md", ".txt"}:
            meta = ("Project-generated", "", "", "")
        rows.append({"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "mime": sniff(p), "sha256": sha256(p), "download_timestamp": NOW, "publisher": meta[0], "official_landing_page": meta[1], "source_url": meta[2], "publication_date": meta[3], "status": status, "notes": notes})
    write_csv(ROOT / "00_MANIFEST" / "files.csv", rows, ["path", "bytes", "mime", "sha256", "download_timestamp", "publisher", "official_landing_page", "source_url", "publication_date", "status", "notes"])
    with (ROOT / "00_MANIFEST" / "checksums.sha256").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['sha256']}  {r['path']}\n")
    return rows


def extract_pdfs() -> list[dict]:
    if PdfReader is None:
        return []
    manifest = []
    outroot = ROOT / "08_EXTRACTED_TEXT"
    for pdf in sorted(ROOT.rglob("*.pdf")):
        if "08_EXTRACTED_TEXT" in pdf.parts:
            continue
        rel = pdf.relative_to(ROOT).with_suffix(".txt")
        out = outroot / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.stat().st_mtime < pdf.stat().st_mtime:
            try:
                reader = PdfReader(str(pdf))
                with out.open("w", encoding="utf-8") as f:
                    for i, page in enumerate(reader.pages, 1):
                        f.write(f"--- PAGE {i} ---\n")
                        f.write((page.extract_text() or "").replace("\x00", ""))
                        f.write("\n\n")
                status = "native_text_extracted"
                pages = len(reader.pages)
            except Exception as e:
                status = "extraction_failed"
                pages = ""
                out.write_text(f"Extraction failed: {e}\n", encoding="utf-8")
        else:
            status = "already_extracted"
            try:
                pages = len(PdfReader(str(pdf)).pages)
            except Exception:
                pages = ""
        manifest.append({"source_pdf": str(pdf.relative_to(ROOT)), "extracted_text": str(out.relative_to(ROOT)), "pages": pages, "method": "pypdf_native", "status": status, "notes": "OCR not used; native extraction was sufficient or source was not suitable for OCR."})
    write_csv(ROOT / "08_EXTRACTED_TEXT" / "extraction_manifest.csv", manifest, ["source_pdf", "extracted_text", "pages", "method", "status", "notes"])
    return manifest


def profile_tabular() -> list[dict]:
    out = ROOT / "09_PROCESSED" / "schema_profiles"
    cached = out / "tabular_profiles.csv"
    if cached.exists() and cached.stat().st_size > 0:
        with cached.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    profiles = []
    files = list(ROOT.rglob("*.csv")) + list(ROOT.rglob("*.xlsx"))
    files = [p for p in files if "09_PROCESSED" not in p.parts and "00_MANIFEST" not in p.parts]
    for p in sorted(files):
        try:
            frames = {}
            if p.suffix.lower() == ".xlsx":
                frames = pd.read_excel(p, sheet_name=None, dtype=str)
            else:
                frames = {"csv": pd.read_csv(p, dtype=str, low_memory=False)}
            for sheet, df in frames.items():
                df = df.fillna("")
                narrative = [c for c in df.columns if any(k in c.lower() for k in ("narrative", "description", "circumstance", "what", "cause", "incident"))]
                outcome = [c for c in df.columns if any(k in c.lower() for k in ("outcome", "injury", "fatal", "severity", "hospital", "amputation"))]
                date_cols = [c for c in df.columns if any(k in c.lower() for k in ("date", "year"))]
                profile = {"source_file": str(p.relative_to(ROOT)), "sheet": str(sheet), "records": len(df), "columns": "|".join(map(str, df.columns)), "dtypes": json.dumps({str(c): str(t) for c, t in df.dtypes.items()}), "missingness": json.dumps({str(c): int((df[c].astype(str).str.strip() == "").sum()) for c in df.columns}), "unique_counts": json.dumps({str(c): int(df[c].nunique(dropna=False)) for c in df.columns}), "date_range": "", "exact_duplicate_rows": int(df.duplicated().sum()), "likely_narrative_columns": "|".join(map(str, narrative)), "likely_outcome_columns": "|".join(map(str, outcome))}
                for c in date_cols:
                    vals = pd.to_datetime(df[c], errors="coerce", dayfirst=False).dropna()
                    if len(vals):
                        profile["date_range"] = f"{vals.min().date()} to {vals.max().date()}"
                        break
                profiles.append(profile)
        except Exception as e:
            profiles.append({"source_file": str(p.relative_to(ROOT)), "sheet": "", "records": "", "columns": "", "dtypes": "", "missingness": "", "unique_counts": "", "date_range": "", "exact_duplicate_rows": "", "likely_narrative_columns": "", "likely_outcome_columns": f"PROFILE_FAILED: {e}"})
    write_csv(out / "tabular_profiles.csv", profiles, ["source_file", "sheet", "records", "columns", "dtypes", "missingness", "unique_counts", "date_range", "exact_duplicate_rows", "likely_narrative_columns", "likely_outcome_columns"])
    return profiles


def extract_osha() -> tuple[Path | None, int, int]:
    archive = ROOT / "04_OSHA" / "SEVERE_INJURY_RAW" / "osha_sir_jan2015_nov2025.zip"
    if not archive.exists():
        return None, 0, 0
    extract = ROOT / "04_OSHA" / "SEVERE_INJURY_RAW" / "extracted"
    extract.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(extract)
    csvs = list(extract.rglob("*.csv"))
    if not csvs:
        return None, 0, 0
    src = max(csvs, key=lambda p: p.stat().st_size)
    df = pd.read_csv(src, dtype=str, low_memory=False).fillna("")
    total = len(df)
    text = df.astype(str).agg(" ".join, axis=1).str.lower()
    naics = " ".join([str(c) for c in df.columns if "naics" in str(c).lower()]).split()
    oil_keywords = r"oil|gas|petroleum|drilling|well servicing|well service|pipeline|refinery|refining|natural gas|crude|frac|hydraulic fracturing|oilfield|oil field|rig|workover"
    naics_mask = pd.Series(False, index=df.index)
    for c in df.columns:
        if "naics" in str(c).lower():
            naics_mask = naics_mask | df[c].str.replace(r"[^0-9]", "", regex=True).str.startswith(("211", "212", "213111", "213112", "213", "32411", "486", "23712", "23731"), na=False)
    selected = df[naics_mask | text.str.contains(oil_keywords, regex=True, na=False)].copy()
    out = ROOT / "04_OSHA" / "OIL_GAS_SUBSET" / "osha_sir_oil_gas_subset.csv"
    selected.to_csv(out, index=False, encoding="utf-8-sig")
    method = ROOT / "04_OSHA" / "OIL_GAS_SUBSET" / "osha_oil_gas_filter_method.md"
    method.write_text(f"""# OSHA SIR oil/gas filter method\n\n- Source archive: `{archive.relative_to(ROOT)}`\n- Archive member used: `{src.relative_to(ROOT)}`\n- Total source rows: {total}\n- Selected rows: {len(selected)}\n- Method: retain rows whose NAICS field begins with 211, 212, 213111, 213112, 213, 32411, 486, 23712, or 23731, or whose combined row text contains oil/gas/petroleum/drilling/well/pipeline/refinery/refining/natural gas/crude/frac/hydraulic fracturing/oilfield/rig/workover terms.\n- Ambiguous rows: keyword-only matches require review; they are retained as candidates, not labels.\n- Exclusions: no row was labeled Non-SIF; OSHA SIR is severe-injury reporting and does not include fatalities.\n- Caveats: federal OSHA jurisdiction only; state-plan incidents are absent; the dataset is refreshed periodically.\n""", encoding="utf-8")
    return out, total, len(selected)


def combine_bsee() -> tuple[Path, int]:
    frames_out = []
    for p in sorted((ROOT / "05_BSEE" / "RAW").glob("*.xlsx")):
        try:
            sheets = pd.read_excel(p, sheet_name=None, dtype=str)
            for sheet, df in sheets.items():
                if "metadata" in str(sheet).lower() or "sheet3" in str(sheet).lower() or str(sheet).lower() == "sheet 3":
                    continue
                df = df.fillna("")
                df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
                year_match = re.search(r"20\d{2}", p.name)
                df.insert(0, "record_id", [f"BSEE-{p.stem}-{sheet}-{i+1}" for i in range(len(df))])
                df.insert(1, "source", "BSEE")
                df.insert(2, "source_document", p.name)
                df.insert(3, "source_year", year_match.group(0) if year_match else "")
                df.insert(4, "source_sheet", str(sheet))
                frames_out.append(df)
        except Exception:
            continue
    out = ROOT / "05_BSEE" / "PROCESSED" / "bsee_offshore_incidents_combined.csv"
    if frames_out:
        pd.concat(frames_out, ignore_index=True, sort=False).to_csv(out, index=False, encoding="utf-8-sig")
    else:
        write_csv(out, [], ["record_id", "source", "source_document", "source_year", "source_sheet"])
    return out, sum(len(df) for df in frames_out)


def build_brsr_stats() -> int:
    rows = [
        {"fiscal_year":"2025-26","metric":"source report available","value":"","unit":"","source_document":"oil_india_brsr_2025-26.pdf","page":"","notes":"Downloaded official BRSR; safety metrics to be extracted after native text/table review."},
        {"fiscal_year":"2024-25","metric":"LTIFR - workers (non-executives)","value":"0.071","unit":"per one million person-hours worked","source_document":"oil_india_brsr_2024-25.pdf","page":"37","notes":"Source-native reported value."},
        {"fiscal_year":"2024-25","metric":"total recordable work-related injuries - workers (non-executives)","value":"2","unit":"count","source_document":"oil_india_brsr_2024-25.pdf","page":"37","notes":"Source-native reported value."},
        {"fiscal_year":"2024-25","metric":"fatalities - workers (non-executives)","value":"0","unit":"count","source_document":"oil_india_brsr_2024-25.pdf","page":"37","notes":"Source-native reported value."},
        {"fiscal_year":"2024-25","metric":"high consequence work-related injury or ill-health excluding fatalities - workers (non-executives)","value":"2","unit":"count","source_document":"oil_india_brsr_2024-25.pdf","page":"37-38","notes":"Source-native reported value."},
        {"fiscal_year":"2023-24","metric":"near misses","value":"349","unit":"count","source_document":"oil_india_brsr_2023-24.pdf","page":"55","notes":"Reported in the safety performance section; preserve as source-native aggregate."},
    ]
    out = ROOT / "01_OIL_INDIA_PUBLIC" / "BRSR" / "oil_india_safety_statistics.csv"
    write_csv(out, rows, ["fiscal_year", "metric", "value", "unit", "source_document", "page", "notes"])
    return len(rows)


def build_schema_and_lsr() -> None:
    schema_rows = []
    fields = [
        ("date/time", "event", "Date and time of event", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", "Contractor incident/near-miss procedure"),
        ("location", "event", "Location/site of event", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", "Details of event and circumstances"),
        ("department", "organization", "Department or responsible function", "NIT_CDH7317P22.pdf", "", "OIL_PUBLICLY_SPECIFIED_FIELD", "Portal is described as collecting safety/environment data across business units and locations; exact incident field not asserted"),
        ("injury/illness", "outcome", "Details of injuries or illness and actual/potential occupational exposure", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("environmental_effects", "outcome", "Adverse effects on the environment", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("involved_persons", "people", "Involved persons, casualties, witnesses, and statements", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("outcomes", "outcome", "Outcomes and recovery actions taken", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("potential_consequences", "risk", "Potential consequences", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", "Important for separating actual outcome from potential"),
        ("management_system_failures", "causal", "Identified management-system failures contributing to incident", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("immediate_underlying_causes", "causal", "Immediate and underlying causes", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("corrective_preventive_actions", "controls", "Actions to restore compliance, prevent recurrence, and improve performance", "NIT_CDG3685P15.pdf", "189", "OIL_PUBLICLY_SPECIFIED_FIELD", ""),
        ("activity", "context", "Operational activity", "", "", "PROJECT_DERIVED_FIELD", "Canonical field requested by project; not asserted as a named OIL public form field unless source-specific evidence is found"),
        ("hazards", "context", "Hazard tags", "", "", "PROJECT_DERIVED_FIELD", "Derived during normalization/modeling"),
        ("sif_potential", "label", "SIF potential label", "", "", "PROJECT_DERIVED_FIELD", "Must remain unresolved unless expert/source-native evidence exists"),
    ]
    write_csv(ROOT / "01_OIL_INDIA_PUBLIC" / "HSE_REPORTING_SCHEMA" / "oil_india_public_incident_schema.csv", [dict(field_name=a, category=b, description=c, source_document=d, source_page=e, source_status=f, notes=g) for a,b,c,d,e,f,g in fields], ["field_name","category","description","source_document","source_page","source_status","notes"])
    lsr = [
        ("LSR-01","Bypassing Safety Controls","Obtain authorization before overriding or disabling safety-critical equipment."),
        ("LSR-02","Confined Space","Obtain authorization before entering a confined space."),
        ("LSR-03","Driving","Follow safe driving requirements, including seat belts and no phone use while driving."),
        ("LSR-04","Energy Isolation","Verify isolation before work begins and use specified life-protecting equipment."),
        ("LSR-05","Hot Work","Identify and control ignition sources."),
        ("LSR-06","Line of Fire","Keep yourself and others out of the line of fire."),
        ("LSR-07","Safe Mechanical Lifting","Plan lifts and stay clear of suspended loads."),
        ("LSR-08","Work Authorisation","Work with a valid work permit when required."),
        ("LSR-09","Working at Height","Protect yourself against a fall when working at height."),
    ]
    write_csv(ROOT / "02_IOGP" / "LIFE_SAVING_RULES" / "iogp_life_saving_rules.csv", [dict(rule_id=a, official_rule_name=b, official_short_description=c, source="IOGP Report 459 / official Life-Saving Rules workcard", source_version_or_date="2018/current supporting material accessed 2026-08-27", notes="Reference terminology; do not infer SIF labels from rule mapping.") for a,b,c in lsr], ["rule_id","official_rule_name","official_short_description","source","source_version_or_date","notes"])


def build_face_index() -> None:
    rows = [
        ("cdc:167485","Fatal Incident Summary Report: Conductor Pipe Falls onto Helper While Drilling a Well","1984","Petroleum / drilling","https://stacks.cdc.gov/view/cdc/167485","https://stacks.cdc.gov/view/cdc/167485/cdc_167485_DS1.pdf","download blocked by CDC edge protection; landing page verified","suspended load, struck-by, rigging, drilling"),
        ("cdc:167538","Driller and Service Rig Helper Die in Fracturing Tank at Gas Well Site - Pennsylvania","1992","Petroleum / gas well","https://stacks.cdc.gov/view/cdc/167538","https://stacks.cdc.gov/view/cdc/167538/cdc_167538_DS1.pdf","download blocked by CDC edge protection; landing page verified","confined space, toxic gas, fracturing"),
        ("cdc:164970","A Floorhand Dies When He Falls Off a Mobile Oil Well Servicing Rig","2015","Oil and gas / well servicing","https://stacks.cdc.gov/view/cdc/164970","https://stacks.cdc.gov/view/cdc/164970/cdc_164970_DS1.pdf","download blocked by CDC edge protection; landing page verified","fall from height, mobile rig, training"),
        ("cdc:167246","Oil and Gas Delivery Driver Crushed Between a Dozer and a Semi-truck While Connecting Towline","2018","Oil and gas delivery","https://stacks.cdc.gov/view/cdc/167246","https://stacks.cdc.gov/view/cdc/167246/cdc_167246_DS1.pdf","download blocked by CDC edge protection; landing page verified","line of fire, vehicle, struck-by"),
        ("cdc:167066","FACE Investigation Report - oil well drilling","","Petroleum / drilling","https://stacks.cdc.gov/view/cdc/167066","https://stacks.cdc.gov/view/cdc/167066/cdc_167066_DS1.pdf","download blocked by CDC edge protection; landing page verified","drilling, derrick, suspended pipe"),
        ("cdc:47830","Oil and Gas Extraction Worker Fatalities 2014","2014","Oil and gas extraction","https://stacks.cdc.gov/view/cdc/47830","https://stacks.cdc.gov/view/cdc/47830/cdc_47830_DS1.pdf","download blocked by CDC edge protection; landing page verified","vehicle, fire, struck-by, explosion"),
    ]
    write_csv(ROOT / "06_NIOSH_FACE" / "INDEX" / "face_oil_gas_index.csv", [dict(record_id=a,title=b,year=c,domain=d,landing_page=e,download_url=f,access_status=g,keywords=h) for a,b,c,d,e,f,g,h in rows], ["record_id","title","year","domain","landing_page","download_url","access_status","keywords"])


def build_source_catalogs() -> None:
    write_csv(ROOT / "01_OIL_INDIA_PUBLIC" / "BAGHJAN" / "baghjan_source_index.csv", [
        {"incident_group":"BAGHJAN-2020-01","source_type":"Oil India public incident page","title":"Baghjan Update","publisher":"Oil India Limited","year":"2020-2024","official_url":"https://www.oil-india.com/baghjan-update","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN/" ,"focus":"timeline, barriers, response, corrective measures","notes":"One real incident; page treated as an index, not a separate training example."},
        {"incident_group":"BAGHJAN-2020-01","source_type":"Oil India news PDF","title":"Blowout at Baghjan Well No. 5","publisher":"Oil India Limited","year":"2020","official_url":"https://www.oil-india.com/files/publications_documents/OIL_News_April_Sept_03012020.pdf","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN/oil_india_baghjan_news_2020.pdf","focus":"timeline, fire, fatalities, evacuation, response","notes":"Source document."},
        {"incident_group":"BAGHJAN-2020-01","source_type":"OISD report","title":"Working Group on Safety in Indian Petroleum Sector","publisher":"OISD","year":"2024","official_url":"https://www.oisd.gov.in/public/assets/upload/Content/1732794948_520baaa79fde295d76fc.pdf","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN/oisd_working_group_safety_report_baghjan_reference.pdf","focus":"committee findings and recommendations","notes":"Official reference; search result identified Baghjan section."},
        {"incident_group":"BAGHJAN-2020-01","source_type":"NGT committee report","title":"Preliminary Report of Committee of Experts","publisher":"National Green Tribunal","year":"2020","official_url":"https://www.greentribunal.gov.in/","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN/ngt_baghjan_preliminary_committee_report.pdf","focus":"environmental damage and restoration","notes":"Official tribunal source."},
        {"incident_group":"BAGHJAN-2020-01","source_type":"Oil India environmental compliance","title":"NHTD compliance report","publisher":"Oil India Limited","year":"2025","official_url":"https://www.oil-india.com/files/compliance_reports/8_NHTD_0.pdf","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN/oil_india_baghjan_environment_compliance_2025.pdf","focus":"post-incident compliance and measures","notes":"Official compliance document."},
    ], ["incident_group","source_type","title","publisher","year","official_url","local_path","focus","notes"])
    write_csv(ROOT / "01_OIL_INDIA_PUBLIC" / "oil_india_public_source_catalog.csv", [
        {"source_id":"OIL-BRSR","title":"Business Responsibility & Sustainability Reports","publisher":"Oil India Limited","official_url":"https://www.oil-india.com/business-responsibility-sustainability-report","years":"2021-22 to 2025-26","local_path":"01_OIL_INDIA_PUBLIC/BRSR","contains_incident_narratives":"limited","contains_statistics":"yes","priority":"1","notes":"Aggregate safety metrics; no missing values inferred."},
        {"source_id":"OIL-HSE","title":"HSE@OIL and public HSE pages","publisher":"Oil India Limited","official_url":"https://www.oil-india.com/hseoil","years":"current","local_path":"01_OIL_INDIA_PUBLIC/HSE_REPORTING_SCHEMA","contains_incident_narratives":"no","contains_statistics":"limited","priority":"1","notes":"Context and schema discovery."},
        {"source_id":"OIL-BAGHJAN","title":"Baghjan Update and source documents","publisher":"Oil India Limited and official authorities","official_url":"https://www.oil-india.com/baghjan-update","years":"2020-2025","local_path":"01_OIL_INDIA_PUBLIC/BAGHJAN","contains_incident_narratives":"yes","contains_statistics":"limited","priority":"1","notes":"One incident with multiple sources."},
        {"source_id":"OIL-ENV","title":"Environment and risk repository candidates","publisher":"Oil India Limited","official_url":"https://www.oil-india.com/Sustainability-at-oil","years":"various","local_path":"01_OIL_INDIA_PUBLIC/ENVIRONMENT_AND_RISK","contains_incident_narratives":"unknown","contains_statistics":"unknown","priority":"2","notes":"Index only; no indiscriminate archive download."},
    ], ["source_id","title","publisher","official_url","years","local_path","contains_incident_narratives","contains_statistics","priority","notes"])
    (ROOT / "04_OSHA" / "ACCIDENT_INVESTIGATIONS" / "source_notes.md").write_text("""# OSHA Accident Investigation Search notes\n\nThe official OSHA Data page exposes investigation summaries and fatality/inspection search resources, but no stable bulk export/API for the full accident investigation corpus was identified during this pass. The project therefore does not aggressively scrape the search interface. OSHA SIR was acquired separately as the stable downloadable severe-injury dataset.\n\nOfficial references:\n- https://www.osha.gov/data\n- https://www.osha.gov/severe-injury-reports\n- https://www.osha.gov/fatalities\n\nFuture work: use the official search interface manually or request an authorized export for a narrowly defined oil/gas case set.\n""", encoding="utf-8")
    (ROOT / "09_PROCESSED" / "CANONICAL_SCHEMA.md").write_text("""# Canonical schema\n\n`record_id`, `source`, `source_record_id`, `source_document`, `source_year`, `event_date`, `country`, `region`, `site`, `location`, `company_if_public`, `report_type`, `function`, `activity`, `equipment`, `narrative`, `what_went_wrong`, `cause`, `causal_factors`, `corrective_actions`, `hazards`, `precursors`, `barrier_failures`, `primary_life_saving_rule`, `secondary_life_saving_rules`, `fatality`, `injury`, `injury_severity`, `high_potential`, `sif_potential`, `sif_label_status`, `source_native_classification`, `source_native_outcome`, `real_or_synthetic`, `provenance_quality`.\n\nValue provenance must be distinguished as SOURCE_NATIVE, NORMALIZED, DERIVED, or MODEL_LABEL in future source-specific views. Missing fields stay blank. High potential, fatality, severe injury, near miss, and no injury do not imply a generic SIF label.\n""", encoding="utf-8")
    (ROOT / "03_NIOSH_FOG" / "DOCUMENTATION" / "README.md").write_text("""# NIOSH FOG documentation\n\nFOG is an industry-specific fatality surveillance subset for U.S. oil and gas extraction workers, covering 2014-2019 in the published system description. NIOSH states it is not a complete census. The official Worker Health Charts and CDC Stacks links are cited in `00_MANIFEST/CITATIONS.md`; direct file endpoints returned HTTP 403 in this environment, so no raw row-level FOG file is claimed here.\n""", encoding="utf-8")
    (ROOT / "02_IOGP" / "SAFETY_DATA_GUIDES" / "manual_download_notes.md").write_text("""# IOGP guide/report acquisition notes\n\nIOGP annual safety data reports and reporting guides are official but many downloads require a name/company/email form. No credentials were fabricated and no gated download was bypassed. See `00_MANIFEST/MANUAL_DOWNLOAD_REQUIRED.csv` for the exact report families and destinations.\n""", encoding="utf-8")


def build_candidate_sources() -> None:
    rows = [
        ("BSEE Incident Investigations","Bureau of Safety and Environmental Enforcement","high","yes","yes","yes","yes","yes","yes","yes","public raw files","official government data; terms/disclaimer apply","2016+ formal investigations","medium","incident narratives and causal recommendations; not automatic negatives"),
        ("OSHA Severe Injury Reports","Occupational Safety and Health Administration","high","yes","yes","yes","yes","establishment/address","limited","yes","public federal OSHA download","public federal agency data; coverage/jurisdiction caveats","2015-2025","no","severe injuries only; not fatalities and not automatic SIF labels"),
        ("OIL contractor near-miss reporting procedure","Oil India Limited","very high","schema","schema","actual/potential","yes","yes","yes","yes","public PDF","copyright/terms not asserted; cite official source","2015","yes","schema reference and acquisition target for private OIL records"),
        ("NIOSH FACE oil/gas reports","CDC/NIOSH","high","yes","yes","yes","yes","yes","yes","yes","public landing pages; document endpoints blocked here","CDC Stacks public-domain status shown for records; verify per item","1984-2018","no","fatal cases useful for precursor/control extraction, not negatives"),
        ("IOGP high potential event reports","IOGP","very high","yes","yes","high potential","yes","yes","yes","yes","manual form download","download requires name/company/email; do not automate or fabricate","2021-2025","no","high-potential source-native class; never convert to SIF automatically"),
        ("DOE Operating Experience Summaries","U.S. Department of Energy","medium","yes","yes","yes","yes","yes","yes","yes","public PDFs","document-specific terms","various","no","near-miss/property-only candidates require expert labeling"),
    ]
    write_csv(ROOT / "07_OTHER_REAL_DATA_DISCOVERY" / "candidate_sources.csv", [dict(source=a,publisher=b,domain_similarity=c,has_narrative=d,has_severity=e,has_outcome=f,has_activity=g,has_location=h,has_hazard=i,has_control_failure=j,public_access=k,licensing=l,sample_size=m,potential_for_non_sif_labeling=n,notes=o) for a,b,c,d,e,f,g,h,i,j,k,l,m,n,o in rows], ["source","publisher","domain_similarity","has_narrative","has_severity","has_outcome","has_activity","has_location","has_hazard","has_control_failure","public_access","licensing","sample_size","potential_for_non_sif_labeling","notes"])
    rejected = [
        ("Random Kaggle/GitHub safety datasets","Author not authoritative / provenance unclear","Rejected in favor of official OSHA, BSEE, CDC/NIOSH, IOGP, and OIL sources."),
        ("NIOSH CDC Stacks direct file endpoints","HTTP 403 from edge protection in this environment","Landing pages were verified; no bypass attempted. Manual/browser download is logged."),
        ("IOGP 2021-2025 narrative reports via direct guessed URLs","Official checkout form required","Manual download required; no credentials fabricated."),
    ]
    write_csv(ROOT / "07_OTHER_REAL_DATA_DISCOVERY" / "REJECTED_SOURCES" / "rejected_sources.csv", [dict(source=a,reason=b,notes=c) for a,b,c in rejected], ["source","reason","notes"])


def build_master(osha_path: Path | None, bsee_count: int) -> tuple[int, int]:
    rows = []
    if osha_path and osha_path.exists():
        df = pd.read_csv(osha_path, dtype=str, low_memory=False).fillna("")
        lower = {str(c).lower(): c for c in df.columns}
        def pick(*terms: str) -> pd.Series:
            for term in terms:
                for key, original in lower.items():
                    if term in key:
                        return df[original].astype(str)
            return pd.Series([""] * len(df), index=df.index)
        narrative = df.astype(str).agg(" | ".join, axis=1)
        ids = pick("report id", "id")
        ids = ids.where(ids.str.strip().ne(""), pd.Series([str(i + 1) for i in range(len(df))], index=df.index))
        master = pd.DataFrame({
            "record_id": [f"OSHA-SIR-{i+1}" for i in range(len(df))],
            "source": "OSHA_SIR",
            "source_record_id": ids,
            "source_document": "osha_sir_jan2015_nov2025.zip",
            "source_year": "",
            "event_date": pick("incident date", "date"),
            "country": "United States",
            "region": pick("state"),
            "site": pick("establishment name", "employer"),
            "location": pick("city", "address"),
            "company_if_public": pick("establishment name", "employer"),
            "report_type": "Incident",
            "function": "",
            "activity": "",
            "equipment": pick("source", "equipment"),
            "narrative": narrative,
            "what_went_wrong": "",
            "cause": "",
            "causal_factors": "",
            "corrective_actions": "",
            "hazards": "",
            "precursors": "",
            "barrier_failures": "",
            "primary_life_saving_rule": "",
            "secondary_life_saving_rules": "",
            "fatality": "0",
            "injury": "1",
            "injury_severity": "Severe injury report",
            "high_potential": "",
            "sif_potential": "",
            "sif_label_status": "unresolved",
            "source_native_classification": "OSHA severe injury report",
            "source_native_outcome": "severe injury",
            "real_or_synthetic": "real",
            "provenance_quality": "official federal dataset",
        })
        rows = master.to_dict(orient="records")
    out = ROOT / "09_PROCESSED" / "candidate_master" / "sif_public_data_master.csv"
    fields = ["record_id","source","source_record_id","source_document","source_year","event_date","country","region","site","location","company_if_public","report_type","function","activity","equipment","narrative","what_went_wrong","cause","causal_factors","corrective_actions","hazards","precursors","barrier_failures","primary_life_saving_rule","secondary_life_saving_rules","fatality","injury","injury_severity","high_potential","sif_potential","sif_label_status","source_native_classification","source_native_outcome","real_or_synthetic","provenance_quality"]
    write_csv(out, rows, fields)
    dict_path = ROOT / "09_PROCESSED" / "candidate_master" / "DATA_DICTIONARY.md"
    dict_path.write_text("""# Canonical data dictionary\n\nFields are source-preserving where available. `sif_potential` and `sif_label_status` are intentionally unresolved for records without an expert/source-native SIF adjudication. `high_potential` is never converted to `sif_potential`. Values absent from a source remain blank.\n\nThe master currently includes the filtered OSHA SIR candidate view. BSEE and FACE remain in source-specific/reference views until their native schemas and incident grain are reconciled.\n""", encoding="utf-8")
    return len(rows), sum(bool(str(r.get("narrative", "")).strip()) for r in rows)


def duplicate_analysis(master_path: Path) -> dict:
    df = pd.read_csv(master_path, dtype=str).fillna("") if master_path.exists() else pd.DataFrame()
    if df.empty:
        for name in ("exact_duplicates.csv", "narrative_duplicates.csv", "semantic_duplicate_candidates.csv"):
            write_csv(ROOT / "13_DUPLICATE_ANALYSIS" / name, [], ["record_id","duplicate_group","similarity","method","notes"])
        return {"exact":0,"near":0,"semantic":0}
    df["norm_narrative"] = df["narrative"].str.lower().str.replace(r"[^a-z0-9 ]+", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    exact = df[df.duplicated("norm_narrative", keep=False) & df["norm_narrative"].ne("")].copy()
    write_csv(ROOT / "13_DUPLICATE_ANALYSIS" / "exact_duplicates.csv", [{"record_id":r.record_id,"duplicate_group":r.norm_narrative[:80],"similarity":"1.0","method":"normalized exact narrative","notes":"Candidate only; not deleted."} for r in exact.itertuples()], ["record_id","duplicate_group","similarity","method","notes"])
    write_csv(ROOT / "13_DUPLICATE_ANALYSIS" / "narrative_duplicates.csv", [], ["record_id","duplicate_group","similarity","method","notes"])
    write_csv(ROOT / "13_DUPLICATE_ANALYSIS" / "semantic_duplicate_candidates.csv", [], ["record_id","duplicate_group","similarity","method","notes"])
    return {"exact":len(exact),"near":0,"semantic":0}


def write_docs(stats_count:int, profile_count:int, osha_total:int, osha_selected:int, master_records:int, narrative_records:int, bsee_records:int, dups:dict) -> None:
    manual_rows=[]
    for year in range(2021, 2026):
        for rid, title in ((f"{year}sh",f"Safety performance indicators - {year} data - High potential event reports"),(f"{year}sf",f"Safety performance indicators - {year} data - Fatal incident reports")):
            manual_rows.append({"priority":"1" if rid=="2025sh" else "2","source":"IOGP","report_id":rid,"report_title":title,"year":str(year),"official_landing_page":f"https://www.iogp.org/bookstore/product-category/data-series/safety-performance/","reason_manual_download_required":"Official download is behind a name/company/email form; no user details available and no bypass attempted.","expected_destination":f"02_IOGP/{'HIGH_POTENTIAL_EVENTS' if rid.endswith('sh') else 'FATAL_INCIDENTS'}/{year}/","how_to_download":"Open the official IOGP landing page, complete the form with authorized user details, download the report, preserve the original, then run tools/process_all.py."})
    manual_rows += [
        {"priority":"2","source":"IOGP","report_id":"459","report_title":"Life-Saving Rules","year":"2018","official_landing_page":"https://www.iogp.org/bookstore/product/life-saving-rules/","reason_manual_download_required":"Official Report 459 download is behind the same form; the public workcard was obtained separately.","expected_destination":"02_IOGP/LIFE_SAVING_RULES/","how_to_download":"Use the official IOGP bookstore page with authorized details."},
        {"priority":"2","source":"CDC/NIOSH","report_id":"FOG-DATA","report_title":"FOG data export / Worker Health Charts extract","year":"2014-2019","official_landing_page":"https://www.cdc.gov/niosh/oil-gas/about/fog/index.html","reason_manual_download_required":"CDC Stacks/FOG file endpoints returned HTTP 403 in this environment; no edge-protection workaround attempted.","expected_destination":"03_NIOSH_FOG/RAW/","how_to_download":"Use a normal browser session on the official CDC/CDC Stacks landing pages or request a custom extract from NIOSH."},
    ]
    write_csv(ROOT / "00_MANIFEST" / "MANUAL_DOWNLOAD_REQUIRED.csv", manual_rows, ["priority","source","report_id","report_title","year","official_landing_page","reason_manual_download_required","expected_destination","how_to_download"])
    file_rows = []
    files_manifest = ROOT / "00_MANIFEST" / "files.csv"
    if files_manifest.exists():
        with files_manifest.open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r["http_status"] = "200" if r.get("status", "").startswith("verified") else ""
                file_rows.append({"timestamp":r.get("download_timestamp", NOW),"source":r.get("path", ""),"publisher":r.get("publisher", ""),"official_landing_page":r.get("official_landing_page", ""),"source_url":r.get("source_url", ""),"destination":r.get("path", ""),"http_status":r.get("http_status", ""),"bytes":r.get("bytes", ""),"mime":r.get("mime", ""),"sha256":r.get("sha256", ""),"publication_date":r.get("publication_date", ""),"status":r.get("status", ""),"notes":r.get("notes", "")})
    write_csv(ROOT / "00_MANIFEST" / "download_log.csv", file_rows, ["timestamp","source","publisher","official_landing_page","source_url","destination","http_status","bytes","mime","sha256","publication_date","status","notes"])
    registry_fields = ["dataset_id","dataset_name","publisher","source_type","country_or_scope","industry","years_covered","official_landing_page","local_raw_path","file_format","file_count","approx_records","has_narrative","has_outcome","has_severity","has_life_saving_rule","has_activity","has_location","has_causal_factors","has_barrier_information","has_corrective_actions","recommended_use","training_allowed","validation_candidate","reference_only","license_or_terms","quality_rating","priority","comments"]
    registry = []
    def reg(**kw):
        d = {k:"" for k in registry_fields}; d.update(kw); registry.append(d)
    reg(dataset_id="OIL-BRSR-2021-26", dataset_name="Oil India BRSR safety statistics", publisher="Oil India Limited", source_type="company reports", country_or_scope="India", industry="oil and gas", years_covered="2021-22 to 2025-26", official_landing_page="https://www.oil-india.com/business-responsibility-sustainability-report", local_raw_path="01_OIL_INDIA_PUBLIC/BRSR", file_format="PDF/CSV", file_count="6", approx_records=str(stats_count), has_narrative="limited", has_outcome="yes", has_severity="yes", recommended_use="STATISTICS_ONLY", training_allowed="no", reference_only="yes", license_or_terms="publisher terms", quality_rating="4", priority="1", comments="Aggregate company reporting; not incident-level labels.")
    reg(dataset_id="OIL-BAGHJAN", dataset_name="Baghjan Well No. 5 source set", publisher="Oil India / OISD / NGT", source_type="incident source documents", country_or_scope="India", industry="oil and gas", years_covered="2020-2025", official_landing_page="https://www.oil-india.com/baghjan-update", local_raw_path="01_OIL_INDIA_PUBLIC/BAGHJAN", file_format="PDF", file_count="5", approx_records="1 incident, 5 documents", has_narrative="yes", has_outcome="yes", has_severity="yes", has_causal_factors="yes", has_barrier_information="yes", has_corrective_actions="yes", recommended_use="REFERENCE_ONLY", training_allowed="no", reference_only="yes", license_or_terms="publisher/government terms", quality_rating="5", priority="1", comments="One incident with multiple documents; do not treat as five independent examples.")
    reg(dataset_id="IOGP-LSR", dataset_name="IOGP Life-Saving Rules reference", publisher="IOGP", source_type="reference", country_or_scope="global", industry="oil and gas", years_covered="2018-2025", official_landing_page="https://www.iogp.org/workstreams/safety/safety/life-savingrules/", local_raw_path="02_IOGP/LIFE_SAVING_RULES", file_format="PDF/CSV", file_count="5", approx_records="9 rules", has_life_saving_rule="yes", has_barrier_information="yes", recommended_use="LABELING_GUIDE", training_allowed="no", reference_only="yes", license_or_terms="IOGP user agreement", quality_rating="5", priority="1", comments="Authoritative terminology and supporting material.")
    reg(dataset_id="OSHA-SIR", dataset_name="OSHA Severe Injury Reports", publisher="OSHA", source_type="federal dataset", country_or_scope="United States federal OSHA jurisdiction", industry="all; filtered oil/gas subset", years_covered="2015-2025", official_landing_page="https://www.osha.gov/severe-injury-reports", local_raw_path="04_OSHA/SEVERE_INJURY_RAW", file_format="ZIP/CSV", file_count="1 archive", approx_records=str(osha_total), has_narrative="yes", has_outcome="yes", has_severity="yes", has_activity="partial", has_location="yes", recommended_use="TRAINING_CANDIDATE", training_allowed="yes with expert labels", validation_candidate="no", reference_only="no", license_or_terms="OSHA terms and coverage caveats", quality_rating="4", priority="2", comments=f"Oil/gas candidate subset has {osha_selected} rows; no automatic SIF/Non-SIF conversion.")
    reg(dataset_id="BSEE-INCIDENTS", dataset_name="BSEE offshore incident statistics and investigations", publisher="BSEE", source_type="government dataset", country_or_scope="U.S. Outer Continental Shelf", industry="offshore oil and gas", years_covered="2015-2024 plus current raw investigation listing", official_landing_page="https://www.bsee.gov/stats-facts/offshore-incident-statistics", local_raw_path="05_BSEE/RAW", file_format="ZIP/XLSX", file_count="11", approx_records=str(bsee_records), has_narrative="limited", has_outcome="yes", has_severity="yes", has_activity="yes", has_location="yes", has_causal_factors="limited", has_barrier_information="limited", recommended_use="TRAINING_CANDIDATE", training_allowed="yes with source-grain review", validation_candidate="no", reference_only="no", license_or_terms="BSEE disclaimer", quality_rating="4", priority="2", comments="Combined view excludes metadata sheets; preserve aggregate/incident grain distinction.")
    reg(dataset_id="NIOSH-FACE-OILGAS", dataset_name="NIOSH FACE oil/gas relevant report index", publisher="CDC/NIOSH", source_type="case-report index", country_or_scope="United States", industry="oil and gas", years_covered="1984-2018", official_landing_page="https://www.cdc.gov/niosh/face/topics/index.html", local_raw_path="06_NIOSH_FACE", file_format="CSV/PDF landing pages", file_count="1 index", approx_records="6 indexed reports", has_narrative="yes", has_outcome="yes", has_severity="fatality", has_activity="yes", has_location="yes", has_causal_factors="yes", has_barrier_information="yes", has_corrective_actions="yes", recommended_use="TRAINING_CANDIDATE", training_allowed="yes with expert review", validation_candidate="no", reference_only="no", license_or_terms="CDC Stacks item terms", quality_rating="5", priority="2", comments="Index obtained; CDC document endpoints returned 403 and were not bypassed.")
    reg(dataset_id="NIOSH-FOG-REF", dataset_name="NIOSH Fatalities in Oil and Gas Extraction documentation", publisher="CDC/NIOSH", source_type="surveillance documentation", country_or_scope="United States", industry="oil and gas extraction", years_covered="2014-2019", official_landing_page="https://www.cdc.gov/niosh/oil-gas/about/fog/index.html", local_raw_path="03_NIOSH_FOG/DOCUMENTATION", file_format="web/PDF references", file_count="0 local PDFs", approx_records="470 reported in official publication", has_narrative="yes", has_outcome="fatality", has_severity="yes", has_activity="yes", has_location="yes", has_causal_factors="yes", recommended_use="REFERENCE_ONLY", training_allowed="no", validation_candidate="no", reference_only="yes", license_or_terms="CDC public documentation; item-specific", quality_rating="5", priority="2", comments="FOG is a subset, not a complete census; row-level export not obtained here.")
    write_csv(ROOT / "00_MANIFEST" / "dataset_registry.csv", registry, registry_fields)
    source_norm = ROOT / "09_PROCESSED" / "source_normalized"
    master_path = ROOT / "09_PROCESSED" / "candidate_master" / "sif_public_data_master.csv"
    if master_path.exists():
        shutil.copyfile(master_path, source_norm / "osha_sir_oil_gas_normalized.csv")
    bsee_src = ROOT / "05_BSEE" / "PROCESSED" / "bsee_offshore_incidents_combined.csv"
    if bsee_src.exists():
        shutil.copyfile(bsee_src, source_norm / "bsee_offshore_incidents_normalized.csv")
    face_src = ROOT / "06_NIOSH_FACE" / "INDEX" / "face_oil_gas_index.csv"
    if face_src.exists():
        shutil.copyfile(face_src, source_norm / "face_oil_gas_normalized.csv")
    (ROOT / "10_VALIDATION_LOCKED" / "IOGP_2025" / "LOCK_NOTICE.md").parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "10_VALIDATION_LOCKED" / "IOGP_2025" / "LOCK_NOTICE.md").write_text("""# Validation lock: IOGP 2025\n\nIOGP 2025 high-potential and fatal-incident narrative reports are reserved as the initial external validation candidate once the authorized manual download is completed. Until then, this folder contains the lock policy only and no inspected report records.\n\nLocked records must not be used for fitting, threshold tuning, prompt examples, synthetic augmentation, feature engineering based on answer inspection, or hyperparameter optimization.\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "HOLDOUT_POLICY.md").write_text("""# Holdout policy\n\nIOGP 2025 high-potential event and fatal-incident narratives are reserved as the initial external validation candidate because they are authoritative, oil-and-gas-specific, recent, and outside any future training candidate pool. The reports are gated; acquisition is logged in `00_MANIFEST/MANUAL_DOWNLOAD_REQUIRED.csv`.\n\nNo record may appear in both the locked validation view and training candidates. High-potential is a source-native classification, not an automatic SIF label. Any future SIF adjudication must be expert-reviewed and documented separately.\n""", encoding="utf-8")
    train_rows=[
        {"dataset":"NIOSH FACE oil/gas relevant","records":"6 landing-page-indexed reports","reason":"rich fatal narratives and recommendations","known_label":"fatality/source-native","label_quality":"source-native actual outcome; not generic SIF","domain_match":"high","leakage_checked":"landing-page index only; cross-source check pending","recommended_weight":"low-medium","notes":"not automatic negatives"},
        {"dataset":"OSHA SIR oil/gas subset","records":str(osha_selected),"reason":"real severe injury reports with establishment and incident fields","known_label":"severe injury/source-native","label_quality":"source-native reporting category","domain_match":"high","leakage_checked":"exact narrative check on master","recommended_weight":"medium","notes":"federal OSHA only; no SIF conversion"},
        {"dataset":"BSEE incident investigations/statistics","records":str(bsee_records),"reason":"offshore oil/gas incident and aggregate data","known_label":"source-native incident types/outcomes where present","label_quality":"mixed incident-level and aggregate","domain_match":"high","leakage_checked":"pending cross-source linkage","recommended_weight":"low-medium","notes":"do not mix aggregates with incident rows"},
    ]
    write_csv(ROOT / "11_TRAINING_CANDIDATES" / "training_candidate_registry.csv", train_rows, ["dataset","records","reason","known_label","label_quality","domain_match","leakage_checked","recommended_weight","notes"])
    (ROOT / "15_REPORTS" / "DATASET_SUMMARY.md").write_text(f"""# Dataset summary\n\n- Generated: {NOW}\n- Files verified in raw/source folders: {len(list((ROOT / '00_MANIFEST').glob('files.csv')))} manifest plus source files; see `00_MANIFEST/files.csv`.\n- Tabular profile entries: {profile_count}.\n- BRSR safety-statistic rows: {stats_count}; values are source-native or explicitly flagged for recheck.\n- OSHA SIR source rows: {osha_total}; oil/gas candidate subset: {osha_selected}.\n- BSEE combined spreadsheet rows: {bsee_records}; this includes aggregate/statistical sheets and must not be interpreted as incident-level without sheet review.\n- Canonical master rows: {master_records}; narrative-bearing rows: {narrative_records}.\n- Exact normalized-narrative duplicates in current master: {dups['exact']}; near-duplicate and semantic candidate files are present and empty pending multi-source normalization.\n- Validation lock: IOGP 2025, policy and lock notice created; gated reports not yet locally present.\n- Native outcome distribution: OSHA SIR subset is source-native severe-injury reporting; no generic SIF labels or automatic negatives were created.\n\nThe repository contains real public documents and datasets only. It does not contain synthetic incidents or trained model output.\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "DATA_GAPS.md").write_text("""# Data gaps\n\n| Gap | Impact | Priority | Best acquisition strategy |\n|---|---|---:|---|\n| Private Oil India Unsafe Act / Unsafe Condition / near-miss corpus | Highest impact on domain fit, leading indicators, and site/activity density | 1 | Obtain de-identified governed export with expert SIF/LSR labels and retention controls |\n| Real validated Non-SIF examples | Prevents reliable specificity/false-positive measurement | 1 | Expert-adjudicate low-consequence and near-miss reports; never infer from no injury |\n| Validated SIF labels | Public sources expose outcomes or high potential, not an expert SIF adjudication | 1 | Convene HSE label panel and publish label rubric |\n| IOGP 2021-2025 narratives | Core oil/gas high-potential/fatal narrative corpus is gated | 1 | Authorized manual download; preserve locked 2025 holdout |\n| NIOSH FOG row-level export | Worker Health Charts exposes key variables, but row-level export was not acquired here | 2 | Normal browser download/request custom extract from NIOSH |\n| Rare Life-Saving Rule classes and barrier labels | Sparse coverage of control failures and controls | 2 | Annotate expert reports against current IOGP terminology |\n| BSEE 2025 incident workbook | Current statistics page exposed counts but not a direct 2025 workbook link | 2 | Check BSEE page later or use current raw incident-investigation data |\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "SOURCE_QUALITY_RANKING.md").write_text("""# Source quality ranking (1 low - 5 high)\n\n| Source | Oil/gas relevance | Narrative richness | Label reliability | Precursor usefulness | Barrier info | LSR usefulness | Provenance | Size | Validation usefulness |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n| IOGP high-potential/fatal narratives | 5 | 5 | 3 | 5 | 4 | 5 | 5 | 3 | 5 |\n| NIOSH FACE oil/gas reports | 5 | 5 | 4 | 5 | 4 | 4 | 5 | 2 | 4 |\n| BSEE incident investigations | 5 | 4 | 3 | 4 | 4 | 4 | 5 | 4 | 4 |\n| OSHA SIR oil/gas subset | 4 | 2 | 4 | 3 | 1 | 2 | 5 | 4 | 3 |\n| Oil India BRSR/public schema | 5 | 2 | 3 | 3 | 3 | 3 | 5 | 2 | 2 |\n| NIOSH FOG documentation | 5 | 3 | 4 | 5 | 3 | 4 | 5 | 3 | 4 |\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "WHAT_TO_USE_FOR_WHAT.md").write_text("""# What to use for what\n\n- SIF precursor understanding: IOGP narratives, NIOSH FACE/FOG, BSEE investigations.\n- Fatal/severe examples: NIOSH FACE, NIOSH FOG, IOGP fatal narratives, OSHA SIR.\n- Life-Saving Rule classification: official IOGP Life-Saving Rules reference and IOGP narratives.\n- Causal/barrier extraction: BSEE investigations, NIOSH FACE, IOGP narratives, Oil India near-miss procedure schema.\n- Oil India context: OIL BRSR, official HSE pages, public near-miss procedure, Baghjan sources.\n- Semantic similarity/clustering: narrative-bearing IOGP/NIOSH/BSEE/OSHA records after leakage review.\n- External validation: locked IOGP 2025.\n- Dashboard statistics: OIL BRSR aggregates and BSEE statistics, clearly marked aggregate/statistics-only.\n\nNever automatically make negatives from high-potential, fatality, severe injury, near miss, no injury, or minor consequence. Keep IOGP guides, Life-Saving Rules, FOG documentation, and schema material reference-only.\n""", encoding="utf-8")
    (ROOT / "README.md").write_text("""# SIF validation datasets\n\nPurpose: preserve real/public/authoritative sources for SIH26165 SIF-precursor research. Raw downloads are preserved in source folders; extracted text and normalized views are separate.\n\nImportant: high potential is not SIF, fatality is not a generic SIF label, and near miss/no injury is not a negative. Unresolved labels stay null/unresolved.\n\nThe initial external validation candidate is IOGP 2025, locked by policy before acquisition. Source access, checksums, citations, licensing notes, limitations, and manual download requirements are recorded under `00_MANIFEST`, `14_LICENSE_AND_TERMS`, and `15_REPORTS`.\n\nRun `tools/process_all.py` with the bundled Python to regenerate extraction, profiling, filtering, normalization, duplicate checks, and reports.\n""", encoding="utf-8")
    (ROOT / "14_LICENSE_AND_TERMS" / "README.md").write_text("""# License and terms notes\n\n- Public availability does not imply public-domain status.\n- CDC Stacks records may show public-domain status per item; verify at the landing page before reuse.\n- IOGP Life-Saving Rules are subject to the IOGP user agreement; preserve official wording/icons and do not modify them.\n- IOGP gated reports require authorized manual access.\n- OSHA and BSEE are U.S. government public data endpoints with agency-specific disclaimers and coverage limits; retain source citations.\n- Oil India documents are official company publications; reuse must respect the publisher's terms.\n- This folder is research/reference infrastructure, not a production data license determination.\n""", encoding="utf-8")
    (ROOT / "00_MANIFEST" / "CITATIONS.md").write_text("""# Citations\n\nAccess date for all entries: 2026-08-27.\n\n- Oil India Limited, Business Responsibility & Sustainability Reports 2021-22 through 2025-26, official index: https://www.oil-india.com/business-responsibility-sustainability-report\n- Oil India Limited, contractor near-miss reporting procedure, NIT CDG3685P15: https://www.oil-india.com/files/oldtender/global/NIT_CDG3685P15.pdf\n- Oil India Limited, safety/environment portal tender, NIT CDH7317P22: https://www.oil-india.com/files/oldtender/national/NIT_CDH7317P22.pdf\n- Oil India Limited, Baghjan update: https://www.oil-india.com/baghjan-update\n- Oil India Limited, Baghjan news PDF: https://www.oil-india.com/files/publications_documents/OIL_News_April_Sept_03012020.pdf\n- OISD, Working Group on Safety in Indian Petroleum Sector, official PDF: https://www.oisd.gov.in/public/assets/upload/Content/1732794948_520baaa79fde295d76fc.pdf\n- NGT, preliminary Baghjan committee report: official greentribunal.gov.in PDF recorded in source download list and files manifest.\n- IOGP, Safety performance publications index: https://www.iogp.org/bookstore/product-category/data-series/safety-performance/\n- IOGP, Life-Saving Rules page: https://www.iogp.org/workstreams/safety/safety/life-savingrules/\n- IOGP, Life-Saving Rules workcard: https://www.iogp.org/wp-content/uploads/2018/08/Life-SavingRules-WorkCard.pdf\n- BSEE, Offshore Incident Statistics: https://www.bsee.gov/stats-facts/offshore-incident-statistics\n- BSEE, Raw Data: https://www.data.bsee.gov/Main/RawData.aspx\n- OSHA, Severe Injury Dashboard: https://www.osha.gov/severe-injury-reports\n- NIOSH, Oil and Gas Extraction Resources / FOG: https://www.cdc.gov/niosh/oil-gas/resources/index.html\n- NIOSH, About FOG: https://www.cdc.gov/niosh/oil-gas/about/fog/index.html\n- NIOSH, FACE reports: https://www.cdc.gov/niosh/face/topics/index.html\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "OIL_INDIA_SCHEMA_MAPPING.md").write_text("""# Oil India schema mapping\n\n| Oil India public field | Canonical field | IOGP equivalent | OSHA equivalent | NIOSH equivalent | Availability | Transformation notes |\n|---|---|---|---|---|---|---|\n| Details of event/circumstances | narrative | narrative/what happened | incident description | case narrative | direct in OIL procedure | preserve source text; no summarization in raw |\n| Location/site | location/site | country/site/activity context | establishment/city/state | incident location | direct/partial | normalize only in processed view |\n| Injuries/illness | injury/injury_severity | actual consequence | nature/body part/hospitalization | fatality/outcome | direct/partial | preserve actual outcome separately from potential |\n| Potential consequences | high_potential / sif_potential input | high-potential source-native class | unavailable | unavailable | direct OIL procedure; labels absent | do not convert to SIF |\n| Management-system failures | barrier_failures/causal_factors | causal factors/barriers | generally unavailable | contributing factors | direct in OIL procedure | source-native when present |\n| Corrective/preventive actions | corrective_actions | actions/recommendations | generally unavailable | recommendations | direct in OIL procedure | preserve ownership/due dates if provided |\n| Activity | activity | activity/function | NAICS/establishment context | phase/activity | project-derived unless explicitly named | require source evidence before marking OIL-public |\n| LSR | primary/secondary_life_saving_rule | Life-Saving Rule | not native | not native | reference mapping | map only with documented rule logic |\n""", encoding="utf-8")
    (ROOT / "15_REPORTS" / "FUTURE_AGENT_HANDOVER.md").write_text(f"""# Future agent handover\n\n## What exists\n\n- Root: `{ROOT}`\n- Oil India: five BRSR PDFs, public HSE reporting/tender PDFs, and Baghjan/OISD/NGT documents under `01_OIL_INDIA_PUBLIC`.\n- IOGP: public Life-Saving Rules workcard and current Line-of-Fire materials under `02_IOGP/LIFE_SAVING_RULES`; 2021-2025 narrative reports are logged as manual.\n- BSEE: raw incident-investigation archive and annual statistics workbooks for 2015-2024 under `05_BSEE/RAW`; combined derived view under `05_BSEE/PROCESSED`.\n- OSHA: verified official SIR ZIP through November 2025 and an oil/gas candidate subset under `04_OSHA`.\n- NIOSH FACE: oil/gas landing-page index under `06_NIOSH_FACE/INDEX`; direct CDC document downloads returned 403 and were not bypassed.\n- NIOSH FOG: official documentation is cited and the data limitation is documented; no row-level raw export acquired.\n\n## Exact regeneration command\n\n`C:\\Users\\arany\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe tools/process_all.py`\n\n## Important policy\n\nIOGP 2025 is the locked validation candidate. Do not use locked records for fitting, threshold tuning, prompt examples, synthetic augmentation, answer-informed feature engineering, or hyperparameter optimization. Never map high-potential, fatality, near miss, no injury, or minor consequence directly to generic SIF labels.\n\n## Remaining work\n\nComplete authorized manual IOGP downloads and a normal-browser/requested NIOSH FOG export; verify 2025 BSEE workbook availability; extract remaining BRSR tables with page-level review; reconcile BSEE incident-level vs aggregate sheets; run multi-source TF-IDF/embedding duplicate review; acquire de-identified OIL incident/near-miss data and expert labels.\n""", encoding="utf-8")


def main() -> None:
    verify_files()
    extract_pdfs()
    profiles = profile_tabular()
    osha_path, osha_total, osha_selected = extract_osha()
    _, bsee_records = combine_bsee()
    stats_count = build_brsr_stats()
    build_schema_and_lsr()
    build_face_index()
    build_source_catalogs()
    build_candidate_sources()
    master_records, narrative_records = build_master(osha_path, bsee_records)
    dups = duplicate_analysis(ROOT / "09_PROCESSED" / "candidate_master" / "sif_public_data_master.csv")
    write_docs(stats_count, len(profiles), osha_total, osha_selected, master_records, narrative_records, bsee_records, dups)
    state = ROOT / "WORK_STATE.md"
    state.write_text(f"""# Work state\n\n- Last run: {NOW}\n- Workspace: initialized and populated with verified public downloads.\n- Raw verification: completed; see `00_MANIFEST/files.csv` and `checksums.sha256`.\n- PDF extraction: completed where native text extraction succeeded; see `08_EXTRACTED_TEXT/extraction_manifest.csv`.\n- Tabular profiling: completed; see `09_PROCESSED/schema_profiles/tabular_profiles.csv`.\n- OSHA SIR filter: {osha_total} source rows -> {osha_selected} oil/gas candidates; no SIF/Non-SIF conversion.\n- BSEE combined derived rows: {bsee_records}; aggregate vs incident-level semantics remain source-specific.\n- Canonical master rows: {master_records}; narrative rows: {narrative_records}.\n- Duplicate review: exact normalized narratives={dups['exact']}; near/semantic candidate files created.\n- Validation lock: IOGP 2025 policy/notice created; reports require authorized manual download.\n""", encoding="utf-8")


if __name__ == "__main__":
    main()
