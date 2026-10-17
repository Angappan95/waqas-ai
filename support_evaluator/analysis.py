"""Deterministic cross-checks between rule-based and model risk assessments."""

from __future__ import annotations

from typing import Any


def deterministic_risk(rule: dict[str, Any]) -> str:
    if rule["sensitive_information_request"]["matched"]:
        return "high"
    coverage = rule["required_point_coverage"]
    has_missing_points = coverage["covered_count"] < coverage["total"]
    if rule["risky_absolute_guarantee"]["matched"] or has_missing_points:
        return "medium"
    return "low"


def build_disagreements(
    rules: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    disagreements = []
    for rule, evaluation in zip(rules, evaluations, strict=True):
        rule_risk = deterministic_risk(rule)
        model_risk = evaluation["risk_level"]
        if not ((rule_risk == "low") != (model_risk == "low")):
            continue

        if rule_risk == "low":
            likely_cause = "The model may have identified semantic or contextual risk that the phrase heuristics do not capture."
        else:
            likely_cause = "The model may have judged the context acceptable despite explicit heuristic risk signals."
        disagreements.append({
            "case_id": rule["case_id"],
            "deterministic_risk": rule_risk,
            "llm_risk": model_risk,
            "rule_signals": {
                "sensitive_information_request": rule["sensitive_information_request"]["matched"],
                "risky_absolute_guarantee": rule["risky_absolute_guarantee"]["matched"],
                "uncovered_required_points": (
                    rule["required_point_coverage"]["total"]
                    - rule["required_point_coverage"]["covered_count"]
                ),
            },
            "likely_cause": likely_cause,
        })
    return disagreements
