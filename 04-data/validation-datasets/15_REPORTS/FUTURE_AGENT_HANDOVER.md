# Future agent handover

## What exists

- Root: `C:\Users\arany\Desktop\SIH Project\SIF validation datasets`
- Oil India: five BRSR PDFs, public HSE reporting/tender PDFs, and Baghjan/OISD/NGT documents under `01_OIL_INDIA_PUBLIC`.
- IOGP: public Life-Saving Rules workcard and current Line-of-Fire materials under `02_IOGP/LIFE_SAVING_RULES`; 2021-2025 narrative reports are logged as manual.
- BSEE: raw incident-investigation archive and annual statistics workbooks for 2015-2024 under `05_BSEE/RAW`; combined derived view under `05_BSEE/PROCESSED`.
- OSHA: verified official SIR ZIP through November 2025 and an oil/gas candidate subset under `04_OSHA`.
- NIOSH FACE: oil/gas landing-page index under `06_NIOSH_FACE/INDEX`; direct CDC document downloads returned 403 and were not bypassed.
- NIOSH FOG: official documentation is cited and the data limitation is documented; no row-level raw export acquired.

## Exact regeneration command

`C:\Users\arany\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools/process_all.py`

## Important policy

IOGP 2025 is the locked validation candidate. Do not use locked records for fitting, threshold tuning, prompt examples, synthetic augmentation, answer-informed feature engineering, or hyperparameter optimization. Never map high-potential, fatality, near miss, no injury, or minor consequence directly to generic SIF labels.

## Remaining work

Complete authorized manual IOGP downloads and a normal-browser/requested NIOSH FOG export; verify 2025 BSEE workbook availability; extract remaining BRSR tables with page-level review; reconcile BSEE incident-level vs aggregate sheets; run multi-source TF-IDF/embedding duplicate review; acquire de-identified OIL incident/near-miss data and expert labels.
