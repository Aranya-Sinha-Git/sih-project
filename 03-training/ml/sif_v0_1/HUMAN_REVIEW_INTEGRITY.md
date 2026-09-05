# Human review finalization

The canonical `blind_test_v0_2` release remains historical. The canonical
`blind_test_v0_3` packet and freeze manifest are the official pre-review
artifacts. They remain blank and must never be overwritten with human labels.

After independent review and adjudication, run
`finalize_human_reviews_v0_3.py`. It writes only the fixed v0.3 finalized
packet and finalization-manifest locations. Then run
`attest_human_evaluation_v0_3.py` to write the one fixed official attestation.
The official evaluator accepts no packet or manifest path arguments and fails
closed unless all three fixed artifacts agree.

Before human review begins, commit the canonical v0.3 blank release and create
an annotated Git tag. Supply that commit SHA and tag to finalization and
attestation, and push that commit/tag to the remote before publishing official
metrics. This is an operational attestation aid, not a digital signature.

Normalized narrative hashes prevent identifier aliases and normalization-only
rewrites from entering calibration. They cannot prove that a paraphrase is a
different incident. Future development and calibration datasets must not
contain paraphrased, summarized, translated, or otherwise repackaged blind
incidents; flag suspicious semantic near-duplicates for manual governance and
do not automatically alter the frozen release or its evaluation.
