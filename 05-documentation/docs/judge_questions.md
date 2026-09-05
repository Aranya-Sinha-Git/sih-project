# Judge questions

**Why not ChatGPT?** This is a bounded workflow with stored provenance, deterministic fallback scoring, analytics, retrieval and human review—not an open-ended assistant.

**What is SIF?** A potential serious injury or fatality exposure; it is separate from whether an injury occurred.

**High Potential vs SIF?** They are independent fields. A High Potential event does not automatically become SIF Potential.

**Where is data from?** No operational records are preloaded. Users submit or import records, and the application stores their source field. Separately stored public-source test fixtures are never loaded automatically.

**False negatives and recall?** Training evaluation prioritises recall and false-negative rate, then sends uncertainty to humans.

**Hallucination controls?** The demo rules cite matching language, describe evidence as signals, and do not claim causality.

**How are patterns detected?** Local similarity and grouped recurring precursor/rule signals; future embedding clustering can replace the fallback.

**Validation?** Not yet evaluated on labelled external test data. Training scripts calculate held-out metrics when labels exist.

**Why Oil India / scale / innovation?** It turns many unstructured reports into reviewable leading indicators and can integrate CSV/ETL sources, local model artifacts and a production database later.

**Limitations?** Transparent rules, local SQLite, no external validation and no operational approval. It assists—not replaces—qualified personnel and approved procedures.
