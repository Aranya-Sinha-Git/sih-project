# Prototype SIF Potential Labeling Framework

This is a prototype review framework, not an Oil India official definition or safety procedure.

## Core question

Could the event described, under credible circumstances already present in the narrative, reasonably have resulted in fatality or life-altering/permanent serious injury?

Review the hazard or energy (pressure/stored energy, electricity, suspended load, moving equipment, significant fall, fire/explosion, toxic atmosphere, confined space, rotating equipment); whether a person was actually or credibly exposed; and whether a critical barrier failed, was absent, bypassed, or not verified. Judge credible potential, not actual outcome alone.

| Label | Meaning | Training use |
|---|---|---|
| `1` / `SIF_POTENTIAL` | Credible severe/fatal potential is supported by the narrative. | Eligible only after `manual_reviewed` or `expert_reviewed` provenance. |
| `0` / `NON_SIF_POTENTIAL` | The narrative does not support credible SIF potential. | Eligible only after `manual_reviewed` or `expert_reviewed` provenance. |
| `U` / `UNCERTAIN` | Evidence is insufficient or reviewers disagree. | Exclude from binary training pending adjudication. |

Never infer the label from fatality, high-potential, severe injury, near miss, no injury, minor injury, or source report type. Record the source-native outcome separately. Prefer a second reviewer and document adjudication where disagreement could change the label.
