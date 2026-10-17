"""Deterministic aggregation of rule checks and qualitative evaluations."""

from __future__ import annotations

from typing import Any

from .config import SCORE


def _append_adjustment(
    adjustments: list[dict[str, Any]], signal: str, penalty: int, detail: str,
) -> None:
    if penalty:
        adjustments.append({"signal": signal, "points": -penalty, "detail": detail})


def _status_for(score: int, severe: bool, evaluation: dict[str, Any]) -> str:
    if severe or score < SCORE.fail_below_score:
        return "fail"
    if (
        score < SCORE.review_below_score
        or evaluation["policy_adherence"] == "warning"
        or evaluation["customer_helpfulness"] == "warning"
        or evaluation["risk_level"] == "medium"
    ):
        return "review"
    return "pass"


def _rationale_for(status: str, severe: bool) -> str:
    if severe:
        return "Severe policy/risk signal requires failure."
    if status == "fail":
        return "Accumulated deductions reduced the score below the failure threshold."
    if status == "review":
        return "Score or caution signal requires reviewer attention."
    return "No configured rule or model signal crossed a review threshold."


def aggregate_scores(
    rules: list[dict[str, Any]], evaluations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for rule, evaluation in zip(rules, evaluations, strict=True):
        rule_adjustments: list[dict[str, Any]] = []
        evaluation_adjustments: list[dict[str, Any]] = []
        sensitive = rule["sensitive_information_request"]["matched"]
        risky = rule["risky_absolute_guarantee"]["matched"]
        coverage = rule["required_point_coverage"]
        missing_points = coverage["total"] - coverage["covered_count"]

        _append_adjustment(
            rule_adjustments, "sensitive_information_request",
            SCORE.sensitive_request_penalty if sensitive else 0,
            "A sensitive-information request pattern matched." if sensitive else "",
        )
        _append_adjustment(
            rule_adjustments, "risky_absolute_guarantee",
            SCORE.risky_guarantee_penalty if risky else 0,
            "Risky absolute-guarantee language matched." if risky else "",
        )
        _append_adjustment(
            rule_adjustments, "missing_required_points",
            SCORE.missing_required_point_penalty * missing_points,
            f"{missing_points} required point(s) were not covered." if missing_points else "",
        )

        policy_penalty = {
            "pass": 0,
            "warning": SCORE.policy_warning_penalty,
            "fail": SCORE.policy_fail_penalty,
        }[evaluation["policy_adherence"]]
        helpfulness_penalty = {
            "pass": 0,
            "warning": SCORE.helpfulness_warning_penalty,
            "fail": SCORE.helpfulness_fail_penalty,
        }[evaluation["customer_helpfulness"]]
        risk_penalty = {
            "low": 0,
            "medium": SCORE.medium_risk_penalty,
            "high": SCORE.high_risk_penalty,
        }[evaluation["risk_level"]]
        _append_adjustment(
            evaluation_adjustments, "policy_adherence", policy_penalty,
            f"LLM policy_adherence={evaluation['policy_adherence']}." if policy_penalty else "",
        )
        _append_adjustment(
            evaluation_adjustments, "customer_helpfulness", helpfulness_penalty,
            f"LLM customer_helpfulness={evaluation['customer_helpfulness']}." if helpfulness_penalty else "",
        )
        _append_adjustment(
            evaluation_adjustments, "risk_level", risk_penalty,
            f"LLM risk_level={evaluation['risk_level']}." if risk_penalty else "",
        )

        deductions = sum(
            adjustment["points"]
            for adjustment in rule_adjustments + evaluation_adjustments
        )
        score = max(SCORE.minimum_score, min(SCORE.maximum_score, SCORE.base_score + deductions))
        severe = sensitive or evaluation["policy_adherence"] == "fail" or evaluation["risk_level"] == "high"
        status = _status_for(score, severe, evaluation)
        results.append({
            "case_id": rule["case_id"],
            "score": score,
            "status": status,
            "explanation": {
                "base_score": SCORE.base_score,
                "rule_adjustments": rule_adjustments,
                "llm_adjustments": evaluation_adjustments,
                "final_rationale": _rationale_for(status, severe),
            },
        })
    return results
