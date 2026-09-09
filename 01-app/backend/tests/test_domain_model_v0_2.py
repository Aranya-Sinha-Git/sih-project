from pathlib import Path

from app.services.classifier import FrozenClassifierAdapter
from app.services.domain_model import DomainSafetyModel, get_domain_model
from app.services.local_llm import LocalLLMService


def test_real_artifacts_load_through_runtime_and_candidate_adapter():
    service = get_domain_model().load()
    metadata = service.metadata()
    assert metadata["sif"]["status"] == "READY"
    assert metadata["lsr_status"] == "READY"
    assert metadata["runtime_generative_llm_calls"] is False
    candidate = FrozenClassifierAdapter(
        Path(__file__).resolve().parents[3]
        / "03-training" / "ml" / "sif_v0_1" / "artifacts" / "domain_adapted_v0_2"
    )
    assert candidate.metadata()["status"] == "READY"
    assert candidate.screen("A worker contacted an energized conductor during maintenance.")["sif_score"] is not None


def test_single_and_multiple_rule_mappings_have_exact_report_evidence():
    service = get_domain_model()
    single_text = "The technician contacted an energized wire after lockout was not applied."
    single = service.map_rules(single_text)
    assert "LSR04" in single["assigned_rule_ids"]
    evidence = next(rule for rule in single["rules"] if rule["rule_id"] == "LSR04")["evidence"]
    assert evidence and evidence[0]["excerpt"] in single_text

    multi_text = "A hopper being lifted by a forklift fell on the employee and caused a back injury."
    multi = service.map_rules(multi_text)
    assert {"LSR06", "LSR07"}.issubset(multi["assigned_rule_ids"])
    assert all(item["excerpt"] in multi_text for rule in multi["rules"] for item in rule["evidence"])


def test_zero_mapping_unavailable_and_negation_are_explicit():
    service = get_domain_model()
    zero = service.map_rules("Routine housekeeping removed paper from an office floor.")
    assert zero["assigned_rule_ids"] == []
    assert zero["mapping_status"] == "MAPPING_UNAVAILABLE"
    assert set(zero["unavailable_rule_ids"]) == {"LSR01", "LSR02", "LSR08"}
    assert "Zero mappings" not in zero["rendered_explanation"]  # status text already states the coverage failure

    negated = service.map_rules("There were no dropped objects and isolation was verified before work began.")
    line_of_fire = next(rule for rule in negated["rules"] if rule["rule_id"] == "LSR06")
    assert line_of_fire["evidence"] == []
    assert line_of_fire["violation_status"] == "NOT_ESTABLISHED"


def test_missing_model_and_short_narrative_never_become_confident_negatives(tmp_path):
    unavailable = DomainSafetyModel(tmp_path / "missing.joblib").map_rules("Short unclear report.")
    assert unavailable["mapping_status"] == "MAPPING_UNAVAILABLE"
    assert len(unavailable["unavailable_rule_ids"]) == 9


def test_batch_mapping_matches_single_mapping_and_llm_is_disabled():
    service = get_domain_model()
    texts = [
        "The technician contacted an energized wire after lockout was not applied.",
        "A hopper being lifted by a forklift fell on the employee and caused a back injury.",
    ]
    batch = service.map_rules_batch(texts)
    assert [item["assigned_rule_ids"] for item in batch] == [service.map_rules(text)["assigned_rule_ids"] for text in texts]
    llm = LocalLLMService(url="http://must-not-be-used.invalid")
    assert llm.configured is False
    assert llm.explain(texts[0], {"decision": "HUMAN_REVIEW"}, [], [], force=True)["runtime_generative_llm_calls"] is False
