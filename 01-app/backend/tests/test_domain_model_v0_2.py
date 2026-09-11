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
    assert candidate.screen("  \n  ")["decision"] == "HUMAN_REVIEW"


def test_representative_examples_cover_sif_non_sif_and_review_routes():
    classifier = get_domain_model().classifier
    clear_sif = classifier.screen("An employee contacted an energized 13,800 volt power line and suffered severe burns.")
    clear_non_sif = classifier.screen("A worker walking across a muddy yard slipped and twisted an ankle.")
    uncertain = classifier.screen("An employee took measurements while standing on an earthen berm, lost balance, and fractured an ankle.")
    assert clear_sif["decision"] == "SIF_POTENTIAL"
    assert clear_non_sif["decision"] == "NON_SIF_POTENTIAL"
    assert uncertain["decision"] == "HUMAN_REVIEW"


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
    assert all(
        "does not prove the rule is irrelevant" in rule["rendered_explanation"]
        for rule in zero["rules"] if rule["assignment_status"] == "BELOW_THRESHOLD"
    )

    negated = service.map_rules("There were no dropped objects and isolation was verified before work began.")
    line_of_fire = next(rule for rule in negated["rules"] if rule["rule_id"] == "LSR06")
    assert line_of_fire["evidence"] == []
    assert line_of_fire["violation_status"] == "NOT_ESTABLISHED"
    assert "does not prove the rule is irrelevant" in line_of_fire["rendered_explanation"]


def test_contextual_collisions_do_not_become_confident_mappings_without_evidence():
    service = get_domain_model()
    drive_belt = service.map_rules("A compressor drive belt failed during routine maintenance; no vehicle was being driven.")
    guy_wire = service.map_rules("A guy wire snapped while a crew was stabilizing a tower; no vehicle was involved.")
    generic_maintenance = service.map_rules("An employee performed routine maintenance on a pump.")

    assert "LSR03" not in drive_belt["assigned_rule_ids"]
    assert "LSR03" not in guy_wire["assigned_rule_ids"]
    assert "LSR05" not in drive_belt["assigned_rule_ids"]
    assert "LSR05" not in generic_maintenance["assigned_rule_ids"]
    assert all(not rule["evidence"] for rule in drive_belt["rules"] if rule["rule_id"] == "LSR05")
    assert all(not rule["evidence"] for rule in generic_maintenance["rules"] if rule["rule_id"] == "LSR05")
    assert all(
        rule["reason_code"] == "NO_EXTRACTABLE_SUPPORT_FOR_CONFIDENT_ASSIGNMENT"
        for mapping in (drive_belt, generic_maintenance)
        for rule in mapping["rules"]
        if rule["rule_id"] == "LSR05"
    )


def test_evidence_backed_driving_mapping_remains_available():
    service = get_domain_model()
    mapping = service.map_rules("A truck driver lost control and struck a pedestrian.")
    assert "LSR06" in mapping["assigned_rule_ids"]
    assigned = next(rule for rule in mapping["rules"] if rule["rule_id"] == "LSR06")
    assert assigned["evidence"]
    assert assigned["evidence"][0]["excerpt"] in "A truck driver lost control and struck a pedestrian."


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
