# Labeling workstream

- `run-labeling.cmd` launches the on-laptop Streamlit labeling interface. It uses the shared backend Python environment and stores durable local decisions in `03-training/ml/sif_v0_1/data/local_label_store/`.
- `web-review-app/` is the standalone Supabase/Netlify review application. Its setup and deployment instructions are in `web-review-app/README.md`.

The local and web labeling tools are intentionally separate, so either can be worked on without starting the main application.
