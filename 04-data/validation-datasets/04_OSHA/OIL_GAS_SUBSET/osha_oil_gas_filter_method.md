# OSHA SIR oil/gas filter method

- Source archive: `04_OSHA\SEVERE_INJURY_RAW\osha_sir_jan2015_nov2025.zip`
- Archive member used: `04_OSHA\SEVERE_INJURY_RAW\extracted\January2015toNovember2025.csv`
- Total source rows: 105996
- Selected rows: 63020
- Method: retain rows whose NAICS field begins with 211, 212, 213111, 213112, 213, 32411, 486, 23712, or 23731, or whose combined row text contains oil/gas/petroleum/drilling/well/pipeline/refinery/refining/natural gas/crude/frac/hydraulic fracturing/oilfield/rig/workover terms.
- Ambiguous rows: keyword-only matches require review; they are retained as candidates, not labels.
- Exclusions: no row was labeled Non-SIF; OSHA SIR is severe-injury reporting and does not include fatalities.
- Caveats: federal OSHA jurisdiction only; state-plan incidents are absent; the dataset is refreshed periodically.
