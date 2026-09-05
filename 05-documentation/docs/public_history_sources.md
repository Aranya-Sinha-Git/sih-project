# Public history sources

The live history contains 100 real public records only. It is intentionally balanced for prototype testing, not representative of any operator or industry rate.

- 50 positive weak labels: OSHA IMIS public accident-detail records whose OSHA result entry marks a fatality. Original detail pages are saved in `01-app/backend/data/public_osha_fatality_reports/`.
- 50 negative weak labels: U.S. Department of Energy Operating Experience Summary records that document a no-injury near miss or property-only outcome. Original PDFs are saved in `01-app/backend/data/public_doe_oes/`.

Every imported record is `source=public_verified`, `sif_label_status=weak_label`, and carries a source URL, source report ID, and label basis in `analysis.provenance`. A weak label is not expert SIF adjudication; use it for prototype evaluation and review workflow testing only.

Primary repositories: [OSHA Accident Investigation Search](https://www.osha.gov/ords/imis/AccidentSearch.html) and [DOE Operating Experience / ORPS public portal](https://orpspublic.doe.gov/Orps/orps.asp).
