# Folder population status

Generated 2026-08-27 after the folder audit.

- Empty folders before this pass: 20.
- Empty folders after this pass: 0.
- Files currently present under the dataset root: 149.
- Source/status files covered by the refreshed verification manifest: 77.
- Official landing pages captured in this pass: 5 successful captures; 2 official pages returned HTTP 403/404 and are documented in `12_REFERENCE_ONLY/page_capture_log.csv`.

Important: populating a folder does not mean that the corresponding incident dataset was available. Folders for gated IOGP reports and blocked NIOSH exports contain access-status records, not fabricated incidents. Real structured incident records remain limited to the acquired OSHA SIR and BSEE views, as described in `DATASET_SUMMARY.md`.

Download access is split into `16_DOWNLOAD_STATUS/READY_ACCESSIBLE` and `16_DOWNLOAD_STATUS/COULD_NOT_ACCESS`. These folders contain navigation/status indexes; the immutable raw files remain in their original source folders.

For direct opening, use `16_DOWNLOAD_STATUS/READY_ACCESSIBLE/FILES`. It contains 33 copied verified source files with no zero-byte files. The inaccessible folder contains `OPEN_OFFICIAL_LINKS.html` for the official pages.
