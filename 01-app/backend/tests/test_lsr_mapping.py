import json

import pytest

from app.services.retrieval import CATALOG_PATH, RetrievalService


# Supplied facts, kept intact (the original full report was not provided).
FACADE = (
    "Two 9.8 kg façade panels dropped from approximately 22.35 m. "
    "Loose panels remained hanging overhead. "
    "Repeated references to falling/dropped panels and dropped objects."
)


@pytest.mark.parametrize("narrative,expected", [
    (FACADE, {"Line of Fire"}),
    ("A tool dropped from a scaffold.", {"Line of Fire"}),
    ("A dropped tool from scaffold struck the ground.", {"Line of Fire"}),
    ("A worker was without fall protection.", {"Working at Height"}),
    ("A worker fell from a scaffold.", {"Working at Height"}),
    ("A suspended crane load passed over the crew.", {"Safe Mechanical Lifting", "Line of Fire"}),
    ("The crane was lifting a load inside the controlled area.", {"Safe Mechanical Lifting"}),
    ("The crane operation was planned and controlled.", {"Safe Mechanical Lifting"}),
    ("Energy isolation was verified before work began.", set()),
    ("Energy isolation failed before maintenance.", {"Energy Isolation"}),
    ("The driver was speeding.", {"Driving"}),
    ("Journey management controls were required for vehicle movement.", {"Driving"}),
    ("The technician disabled the safety interlock.", {"Bypassing Safety Controls"}),
    ("A worker entered the tank.", {"Confined Space"}),
    ("Confined space entry required atmospheric testing.", {"Confined Space"}),
    ("Welding beside fuel containers produced sparks.", {"Hot Work"}),
    ("Work started without a permit.", {"Work Authorisation"}),
    ("An ordinary garden scheduling meeting concluded.", set()),
    ("The panel height was measured at 22.35 m.", set()),
    ("The office discussed safety, energy, fire, controls, load and height.", set()),
    ("There were no dropped objects.", set()),
    ("No isolation failure occurred.", set()),
    ("Isolation was verified; but a separate isolation failed.", {"Energy Isolation"}),
    ("An object fell from height.", {"Line of Fire"}),
    ("Falling objects landed nearby.", {"Line of Fire"}),
    ("A dislodged panel landed on the ground.", {"Line of Fire"}),
    ("Loose panels remained hanging overhead.", {"Line of Fire"}),
    ("An overhead object threatened the crew.", {"Line of Fire"}),
    ("A worker stood in the release path.", {"Line of Fire"}),
    ("The projectile trajectory intersected the walkway.", {"Line of Fire"}),
    ("A worker stood near moving equipment.", {"Line of Fire"}),
    ("The crew faced struck-by exposure.", {"Line of Fire"}),
    ("A loose panel could strike a worker.", {"Line of Fire"}),
    ("The objects were not dropped.", set()),
])
def test_contextual_rule_mapping(narrative, expected):
    service = RetrievalService()
    evidence = service.reference_evidence(narrative)
    rules = [item for item in evidence if item['reference_type'] == 'iogp_reference']
    assert {item['rule'] for item in rules} == expected
    for item in rules:
        official = next(ref for ref in service.references if ref['evidence_id'] == item['evidence_id'])
        assert item['excerpt'] == official['text']
        assert item['citation'] == {key: official[key] for key in ('publisher', 'source_url', 'document_version', 'page_section')}
        assert item['retrieval_method'] == 'curated_concepts_tfidf'
        assert all(span in narrative for span in item['narrative_spans'])


def test_nomination_cannot_invent_missing_reference(tmp_path):
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    catalog['references'] = [ref for ref in catalog['references'] if ref['rule'] != 'Line of Fire']
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(catalog), encoding='utf-8')
    assert not RetrievalService(path).reference_evidence(FACADE)


def test_facade_api_and_screening_independence(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, 'rows', lambda: [])
    report = main.AnalyzeInput(narrative=FACADE)
    result = main.analyzed_result(report)
    assert result['rules']['primary'] == {
        'rule': 'Line of Fire', 'evidence_id': 'IOGP-459-LINEOFFIRE',
        'provenance': 'grounded_iogp_reference',
    }
    assert result['rules']['secondary'] == []
    grounded = result['intelligence']['reference_evidence'][0]
    assert grounded['citation']['publisher'] == 'IOGP'
    assert grounded['excerpt'] == 'Keep yourself and others out of the line of fire.'
    monkeypatch.setattr(main, 'intelligence_snapshot', lambda *args: {'reference_evidence': []})
    unmapped = main.analyzed_result(report)
    assert unmapped['rules']['primary'] is None
    for key in ('screening', 'sif_probability', 'sif_potential', 'classification', 'risk', 'review_required'):
        assert result[key] == unmapped[key]


def test_verified_isolation_is_not_extracted_as_failure():
    from app.services.engine import analyze_text
    result = analyze_text('Energy isolation was verified before work began.')
    assert result['barrier_failures'] == []
    assert result['precursors'] == ['no strong precursor pattern']
