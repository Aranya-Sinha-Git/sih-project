from pathlib import Path
import json
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from preprocess import clean_narrative, normalize_text
from predict import predict
from evaluate_human import EvaluationError, assess_calibration, calibration_metrics, evaluate_rows, frozen_metadata
from build_blind_test_v0_1 import VALIDATION_POLICY, validation_locked_mask
from supervised_v0_1 import validate_saved_split
from weak_demo_engine import score_text


def reviewer_row(test_id: str, source_id: str, narrative: str, label: str = '1') -> dict:
    return {'test_id': test_id, 'source_record_id': source_id, 'narrative': narrative, 'reviewer_id': 'Reviewer A', 'review_date': '2026-09-01', 'reviewer_sif_label': label, 'reviewer_confidence': 'high', 'reviewer_notes': 'independent review', 'second_reviewer_id': 'Reviewer B', 'second_review_date': '2026-09-02', 'second_reviewer_label': label, 'second_reviewer_confidence': 'high', 'second_reviewer_notes': 'independent second review', 'disagreement_resolution': '', 'adjudicated_label': label, 'adjudication_locked': 'true'}


def reviewer_manifest(rows: list[dict], *, frozen: bool = True) -> dict:
    manifest = {'selected_ids': [row['source_record_id'] for row in rows], 'test_ids': [row['test_id'] for row in rows], 'test_narrative_hashes': {row['test_id']: __import__('hashlib').sha256(row['narrative'].strip().encode()).hexdigest() for row in rows}}
    if frozen:
        manifest.update({'model_hash': 'frozen-model', 'configuration_hash': 'frozen-config', 'binary_threshold': 0.4, 'review_band': [0.35, 0.45]})
    return manifest


def frozen_context() -> dict:
    return {'model_identity': 'tfidf_word_12_char_35', 'model_hash': 'frozen-model', 'configuration_hash': 'frozen-config', 'binary_threshold': 0.4, 'review_band': [0.35, 0.45], 'calibration_status': 'uncalibrated'}


def test_real_predictor_routes_exact_policy_boundaries(monkeypatch, tmp_path):
    import predict as frozen_predict

    model_path = tmp_path / 'tfidf_logreg.joblib'
    model_path.touch()
    scores = iter([0.34999, 0.35, 0.45, 0.45001])

    class FrozenFixture:
        def predict_proba(self, _texts):
            score = next(scores)
            class Probabilities:
                def __getitem__(self, key):
                    return score if key == (0, 1) else 1.0 - score
            return Probabilities()

    monkeypatch.setattr(frozen_predict, '_threshold_info', lambda _artifacts: {'model': 'tfidf_word_12_char_35', 'sif_threshold': 0.4, 'human_review_band': [0.35, 0.45]})
    monkeypatch.setattr(frozen_predict, '_load_model', lambda _path: FrozenFixture())
    expected = ['NON_SIF_POTENTIAL', 'HUMAN_REVIEW', 'HUMAN_REVIEW', 'SIF_POTENTIAL']
    for decision in expected:
        assert frozen_predict.predict('Boundary narrative for the frozen predictor.', artifact_dir=tmp_path)['decision'] == decision


def test_preprocessing_preserves_negation_and_numbers():
    assert clean_narrative("  not isolated  20  bar ") == "not isolated 20 bar"
    assert normalize_text("A\nB") == "a b"


def test_weak_demo_empty_and_high_energy_are_marked_unvalidated():
    assert score_text("")["model_status"] == "WEAK_DEMO_UNVALIDATED"
    output = score_text("Worker entered beneath a suspended load; exclusion zone was missing.")
    assert output["model_status"] == "WEAK_DEMO_UNVALIDATED"
    assert output["review_required"] is True


def test_model_loading_long_text_and_deterministic_inference():
    text = "pressure release isolation verification worker exposure " * 500
    first = predict(text)
    second = predict(text)
    assert first == second
    assert first["model_status"] == "AI_ASSISTED_SUPERVISED_PROTOTYPE"
    assert isinstance(first["sif_score"], float)
    assert first["decision"] in {"SIF_POTENTIAL", "NON_SIF_POTENTIAL", "HUMAN_REVIEW"}


def test_empty_invalid_and_missing_artifact_are_safe(tmp_path):
    empty = predict("   ")
    assert empty["decision"] == "HUMAN_REVIEW"
    assert empty["review_required"] is True
    with pytest.raises(TypeError):
        predict(None)
    missing = predict("isolated equipment", artifact_dir=tmp_path)
    assert missing["model_status"] == "ARTIFACT_MISSING"
    assert missing["decision"] == "HUMAN_REVIEW"


def test_saved_split_is_duplicate_safe():
    validate_saved_split()


def test_blind_builder_excludes_shared_validation_locked_flags():
    policy = json.loads(VALIDATION_POLICY.read_text(encoding='utf-8'))
    frame = pd.DataFrame([
        {'source': 'operational', 'source_record_id': 'OPEN', 'validation_locked': 'false'},
        {'source': 'operational', 'source_record_id': 'FLAGGED', 'validation_locked': 'true'},
        {'source': 'IOGP 2025', 'source_record_id': 'SOURCE-LOCKED', 'validation_locked': 'false'},
    ])
    mask = validation_locked_mask(frame, {str(value).casefold() for value in policy['locked_sources']}, set(policy['locked_record_flags']))
    assert frame.loc[~mask, 'source_record_id'].tolist() == ['OPEN']


def test_human_evaluator_uses_locked_labels_and_never_fits():
    rows = [
        reviewer_row('BT-1', 'SRC-1', 'first narrative', '1'),
        reviewer_row('BT-2', 'SRC-2', 'second narrative', '0'),
        reviewer_row('BT-3', 'SRC-3', 'third narrative', '1'),
    ]
    scores = {'first narrative':0.2,'second narrative':0.4,'third narrative':0.5}
    class NoFit:
        def fit(self, *args, **kwargs):
            raise AssertionError('human evaluation must not fit')
        def __call__(self, text):
            return {'sif_score':scores[text]}
    result = evaluate_rows(rows, NoFit(), 0.4, manifest=reviewer_manifest(rows), frozen=frozen_context())
    assert result['sample_size']==3 and result['binary_metrics']['confusion_matrix']==[[0,1],[1,1]] and result['false_negative_ids']==['BT-1']
    assert result['three_band_routing']['counts']=={'NON_SIF_POTENTIAL':1,'HUMAN_REVIEW':1,'SIF_POTENTIAL':1} and result['three_band_routing']['human_positive_cases_routed_non_sif']==1

    nested = {'selected_ids': [row['source_record_id'] for row in rows], 'freeze_manifest': {'test_ids': [row['test_id'] for row in rows], 'test_narrative_hashes': {row['test_id']: __import__('hashlib').sha256(row['narrative'].strip().encode()).hexdigest() for row in rows}, 'model_hash': 'frozen-model', 'configuration_hash': 'frozen-config', 'binary_threshold': 0.4, 'review_band': [0.35, 0.45]}}
    assert evaluate_rows(rows, NoFit(), 0.4, manifest=nested, frozen=frozen_context())['sample_size'] == 3


def test_human_evaluator_rejects_bad_joins_labels_and_hashes(tmp_path, monkeypatch):
    base=reviewer_row('BT-1','SRC-1','locked narrative','1')
    manifest=reviewer_manifest([base])
    with pytest.raises(EvaluationError, match='manifest'):
        evaluate_rows([base],lambda text:{'sif_score':0.8},0.4,frozen=frozen_context())
    with pytest.raises(EvaluationError, match='Duplicate'):
        evaluate_rows([base,dict(base)],lambda text:{'sif_score':0.8},0.4,manifest=reviewer_manifest([base,dict(base)]),frozen=frozen_context())
    missing=dict(base);missing['adjudicated_label']=''
    excluded_manifest=reviewer_manifest([missing]);excluded_manifest['excluded_ids']=['BT-1']
    assert evaluate_rows([missing],lambda text:{'sif_score':0.8},0.4,manifest=excluded_manifest,frozen=frozen_context())['unresolved_exclusions']==1
    unknown=dict(base);unknown['adjudicated_label']='maybe'
    with pytest.raises(EvaluationError, match='Unknown'):
        evaluate_rows([unknown],lambda text:{'sif_score':0.8},0.4,manifest=reviewer_manifest([unknown]),frozen=frozen_context())
    with pytest.raises(EvaluationError, match='exactly match'):
        evaluate_rows([base],lambda text:{'sif_score':0.8},0.4,manifest={**manifest,'selected_ids':['SRC-OTHER']},frozen=frozen_context())
    with pytest.raises(EvaluationError, match='Narrative hash'):
        evaluate_rows([dict(base, narrative='changed narrative')],lambda text:{'sif_score':0.8},0.4,manifest=manifest,frozen=frozen_context())
    with pytest.raises(EvaluationError, match='locked'):
        evaluate_rows([dict(base, adjudication_locked='false')],lambda text:{'sif_score':0.8},0.4,manifest=manifest,frozen=frozen_context())
    artifacts=Path(__file__).resolve().parents[1]/'artifacts'/'supervised'
    manifest=tmp_path/'manifest.json';manifest.write_text('{"model_hash":"wrong"}',encoding='utf-8')
    packet=tmp_path/'packet.csv';packet.write_text('test_id,narrative,adjudicated_label\nBT-1,locked narrative,1\n',encoding='utf-8')
    from evaluate_human import evaluate_file
    monkeypatch.setattr('evaluate_human.frozen_metadata', lambda _artifacts: {'model_identity':'tfidf_word_12_char_35','model_hash':'actual-model','configuration_hash':'actual-config','binary_threshold':0.4,'review_band':[0.35,0.45],'calibration_status':'uncalibrated'})
    with pytest.raises(EvaluationError, match='model_hash'):
        evaluate_file(packet,artifacts,manifest)


def test_frozen_metadata_is_read_only_and_reports_single_class():
    artifacts=Path(__file__).resolve().parents[1]/'artifacts'/'supervised'
    metadata=frozen_metadata(artifacts)
    assert metadata['model_hash'] and metadata['configuration_hash'] and metadata['calibration_status']=='uncalibrated'
    row=reviewer_row('BT-1','SRC-1','only negative','0')
    result=evaluate_rows([row],lambda text:{'sif_score':0.1},metadata['binary_threshold'],manifest={**reviewer_manifest([row]),'model_hash':metadata['model_hash'],'configuration_hash':metadata['configuration_hash']},frozen=metadata)
    assert result['sample_size']==1 and result['binary_metrics']['recall']==0.0


def test_calibration_is_independent_and_never_reuses_blind_test():
    rows=[reviewer_row('DEV-1','DEV-SRC-1','development one','0'),reviewer_row('DEV-2','DEV-SRC-2','development two','1')]
    result=assess_calibration(rows,lambda text:{'sif_score':0.2 if 'one' in text else 0.8},population='independent_development',manifest=reviewer_manifest(rows,frozen=False),blind_manifest={'test_ids':['BT-1']})
    assert result['status']=='assessed_frozen_raw_scores' and result['brier_score']==0.04 and result['calibrator_fitted'] is False
    with pytest.raises(EvaluationError,match='overlap'):
        assess_calibration(rows,lambda text:{'sif_score':0.5},population='development_alias',manifest=reviewer_manifest(rows,frozen=False),blind_manifest={'test_ids':['DEV-1']})
    with pytest.raises(EvaluationError,match=r'\[0, 1\]'):
        calibration_metrics([0],[1.1])
