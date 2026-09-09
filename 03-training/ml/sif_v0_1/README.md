# SIF NLP v0.1

This isolated workspace builds a scientifically constrained SIF-potential workflow without changing source datasets or the existing application.

Run from this folder with the backend virtual environment:

```powershell
..\..\..\01-app\backend\.venv\Scripts\python.exe src\build_candidate_pool.py
..\..\..\01-app\backend\.venv\Scripts\python.exe src\train_tfidf.py
..\..\..\01-app\backend\.venv\Scripts\python.exe src\finalize_status.py
..\..\..\01-app\backend\.venv\Scripts\python.exe src\predict.py --text "Worker entered beneath a suspended load during lifting."
streamlit run annotation_app.py
```

The versioned domain-adaptation run, its fitted artifacts, protected prototype
test and measured runtime integration are documented in
`DOMAIN_ADAPTED_V0_2_MODEL_CARD.md`. Run `src/train_domain_adapted_v0_2.py` to
rebuild it and `src/benchmark_domain_v0_2.py` to repeat the local benchmark.

For the durable local labeling interface, double-click `02-labeling/run-labeling.cmd` from the workspace root. Every decision is committed to `data/local_label_store/annotations.sqlite3`, mirrored to `annotations.backup.sqlite3`, and exported atomically to `data/annotation_decisions.csv` and `data/reviewed_labels.csv`. Existing CSV decisions are migrated automatically on first launch. Set `SIF_LABEL_DATA_DIR` before launching only if you want the SQLite files stored in another folder on the laptop.

Human decisions exported with `manual_reviewed` provenance remain distinct from the existing AI-assisted supervised prototype labels. The local SQLite store is the source of truth for annotation history; CSV files are compatibility snapshots.
