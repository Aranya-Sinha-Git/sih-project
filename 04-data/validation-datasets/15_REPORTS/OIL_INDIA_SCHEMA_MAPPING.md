# Oil India schema mapping

| Oil India public field | Canonical field | IOGP equivalent | OSHA equivalent | NIOSH equivalent | Availability | Transformation notes |
|---|---|---|---|---|---|---|
| Details of event/circumstances | narrative | narrative/what happened | incident description | case narrative | direct in OIL procedure | preserve source text; no summarization in raw |
| Location/site | location/site | country/site/activity context | establishment/city/state | incident location | direct/partial | normalize only in processed view |
| Injuries/illness | injury/injury_severity | actual consequence | nature/body part/hospitalization | fatality/outcome | direct/partial | preserve actual outcome separately from potential |
| Potential consequences | high_potential / sif_potential input | high-potential source-native class | unavailable | unavailable | direct OIL procedure; labels absent | do not convert to SIF |
| Management-system failures | barrier_failures/causal_factors | causal factors/barriers | generally unavailable | contributing factors | direct in OIL procedure | source-native when present |
| Corrective/preventive actions | corrective_actions | actions/recommendations | generally unavailable | recommendations | direct in OIL procedure | preserve ownership/due dates if provided |
| Activity | activity | activity/function | NAICS/establishment context | phase/activity | project-derived unless explicitly named | require source evidence before marking OIL-public |
| LSR | primary/secondary_life_saving_rule | Life-Saving Rule | not native | not native | reference mapping | map only with documented rule logic |
