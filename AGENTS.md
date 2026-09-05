# Repository Agent Requirements

- Treat `03-training/ml/sif_v0_1/data/blind_test_v0_2` as a frozen human-validation release. Do not alter its canonical packet or freeze manifest after release.
- Changes to the frozen human-validation workflow must preserve the v0.1 historical artifacts and must not add predictions, AI labels, model scores, retrieval results, or explanations to reviewer packets.
- Before concluding any repository change, run the relevant targeted tests, commit the completed work, and push the commit to the configured GitHub `origin` remote. Report the commit and push result.
