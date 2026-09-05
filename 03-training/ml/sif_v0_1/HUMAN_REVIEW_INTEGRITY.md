# Human review finalization

The canonical `blind_test_v0_2` packet and freeze manifest are pre-review
artifacts. They remain blank and must never be overwritten with human labels.

After independent review and adjudication, run `finalize_human_reviews.py` to
write a separate canonicalized finalized packet and its finalization manifest.
The evaluator accepts only that packet/manifest pair. The manifest binds the
canonical v0.2 freeze hash, deterministic completed-packet content hash,
finalization-policy hash, retained/excluded counts, exclusions, and review
provenance.

Before human review begins, commit the canonical blank release and create an
annotated Git tag. Supply that commit SHA and tag to finalization as optional
external attestation metadata. This is an operational attestation aid, not a
digital signature.

Normalized narrative hashes prevent identifier aliases and normalization-only
rewrites from entering calibration. They cannot prove that a paraphrase is a
different incident. Future development and calibration datasets must not
contain paraphrased, summarized, translated, or otherwise repackaged blind
incidents; flag suspicious semantic near-duplicates for manual governance and
do not automatically alter the frozen release or its evaluation.
