# Work state

- Last run: 2026-08-27T10:23:29.367247+00:00
- Workspace: initialized and populated with verified public downloads.
- Raw verification: completed; see `00_MANIFEST/files.csv` and `checksums.sha256`.
- PDF extraction: completed where native text extraction succeeded; see `08_EXTRACTED_TEXT/extraction_manifest.csv`.
- Tabular profiling: completed; see `09_PROCESSED/schema_profiles/tabular_profiles.csv`.
- OSHA SIR filter: 105996 source rows -> 63020 oil/gas candidates; no SIF/Non-SIF conversion.
- BSEE combined derived rows: 6252; aggregate vs incident-level semantics remain source-specific.
- Canonical master rows: 63020; narrative rows: 63020.
- Duplicate review: exact normalized narratives=0; near/semantic candidate files created.
- Validation lock: IOGP 2025 policy/notice created; reports require authorized manual download.
- Folder audit: completed; no empty directories remain under the dataset root. Status artifacts and official page captures were added where incident downloads were unavailable; see `15_REPORTS/FOLDER_POPULATION_STATUS.md`.
