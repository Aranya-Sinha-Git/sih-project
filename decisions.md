# Validation Decisions

Date: 2026-09-05

## Blind-test status

The current `03-training/ml/sif_v0_1/data/blind_test` release is **not approved** for reporting an uncontaminated blind-test result. Its shipped packet and manifest do not satisfy the current human evaluator's required contract.

## Release gates

Do not score, calibrate against, rename, rebuild, or report this blind set until all of the following are complete:

1. Publish one immutable, canonical freeze manifest before human review. It must contain exact test IDs, source IDs, normalized-narrative hashes, packet hashes, model artifact hash, configuration hash, binary threshold, and review band.
2. Require the evaluator to verify that canonical manifest and packet hashes; do not accept a caller-created replacement manifest as the authority.
3. Regenerate or migrate the reviewer packet to include both reviewer identities, review dates, confidences, adjudication lock state, adjudicator identity/date, and an exclusion reason where applicable.
4. Make every configured validation-lock column mandatory. Missing lock columns must fail the builder rather than disable record-level locking.
5. Block calibration use by canonical test/source IDs, candidate IDs, and narrative hashes; calibration data must be independently frozen and disjoint.
6. Add an integration test that evaluates the actual released packet and manifest, including negative tests for altered IDs, narratives, hashes, artifact/configuration, thresholds, and aliases.

## Permitted use before remediation

The current files may be inspected for provenance and schema migration only. They must not be presented as external-validation results or used to select a model, threshold, calibration rule, or release claim.

