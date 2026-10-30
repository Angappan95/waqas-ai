"""Deterministic aggregation of rule checks and qualitative evaluations."""

from __future__ import annotations

from typing import Any

from .config import SCORE

_LEGACY_PENALTIES = {
    "policy_adherence": {
        "pass": 0, "warning": SCORE.policy_warning_penalty, "fail": SCORE.policy_fail_penalty,
    },
    "customer_helpfulness": {
        "pass": 0, "warning": SCORE.helpfulness_warning_penalty, "fail": SCORE.helpfulness_fail_penalty,
    },
    "risk_level": {
        "low": 0, "medium": SCORE.medium_risk_penalty, "high": SCORE.high_risk_penalty,
    },
}
_FINDING_PENALTIES = {
    "critical": SCORE.critical_finding_penalty,
    "major": SCORE.major_finding_penalty,
    "minor": SCORE.minor_finding_penalty,
}


def _append_adjustment(
    adjustments: list[dict[str, Any]], signal: str, penalty: int, detail: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if penalty:
        adjustment = {"signal": signal, "points": -penalty, "detail": detail}
        if metadata:
            adjustment.update(metadata)
        adjustments.append(adjustment)


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


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, int | None]:
    reference = finding.get("policy_reference", {})
    return (
        finding.get("code", ""),
        reference.get("field", reference.get("id", "")),
        reference.get("index"),
    )


def _missing_point_indexes(coverage: dict[str, Any]) -> list[int]:
    return [
        item.get("index", index)
        for index, item in enumerate(coverage.get("items", []))
        if item.get("status", "supported" if item.get("covered") else "not_observed") == "not_observed"
    ]


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
        missing_indexes = _missing_point_indexes(coverage)
        missing_points = len(missing_indexes) if coverage.get("items") else coverage["total"] - coverage["covered_count"]
        missing_detail = (
            f"Required-point indexes {missing_indexes} were not observed; see rule_checks.json for their policy text and evidence."
            if "rule_findings" in rule
            else f"{missing_points} required point(s) were not covered."
        )

        _append_adjustment(
            rule_adjustments, "sensitive_information_request",
            SCORE.sensitive_request_penalty if sensitive else 0,
            "A sensitive-information request pattern matched." if sensitive else "",
            {"evidence": rule["sensitive_information_request"].get("evidence", [])} if "rule_findings" in rule else None,
        )
        _append_adjustment(
            rule_adjustments, "risky_absolute_guarantee",
            SCORE.risky_guarantee_penalty if risky else 0,
            "Risky absolute-guarantee language matched." if risky else "",
            {"evidence": rule["risky_absolute_guarantee"].get("evidence", [])} if "rule_findings" in rule else None,
        )
        _append_adjustment(
            rule_adjustments, "missing_required_points",
            SCORE.missing_required_point_penalty * missing_points,
            missing_detail if missing_points else "",
        )

        rule_findings = rule.get("rule_findings", [])
        accounted = {_finding_key(item) for item in rule_findings}
        model_findings = evaluation.get("findings")
        if model_findings is None:
            for signal, penalties in _LEGACY_PENALTIES.items():
                value = evaluation[signal]
                penalty = penalties[value]
                _append_adjustment(
                    evaluation_adjustments, signal, penalty,
                    f"LLM {signal}={value}." if penalty else "",
                )
        else:
            seen = set()
            for finding in model_findings:
                key = _finding_key(finding)
                if key in accounted or key in seen:
                    continue
                seen.add(key)
                _append_adjustment(
                    evaluation_adjustments,
                    finding["code"],
                    _FINDING_PENALTIES[finding["severity"]],
                    finding["rationale"],
                    {"policy_reference": finding["policy_reference"], "evidence": finding["evidence"]},
                )

        deductions = sum(
            adjustment["points"]
            for adjustment in rule_adjustments + evaluation_adjustments
        )
        score = max(SCORE.minimum_score, min(SCORE.maximum_score, SCORE.base_score + deductions))
        if model_findings is None:
            severe = sensitive or evaluation["policy_adherence"] == "fail" or evaluation["risk_level"] == "high"
        else:
            severe = sensitive or any(item["severity"] == "critical" for item in model_findings)
        status = _status_for(score, severe, evaluation)
        if status == "pass" and (rule_findings or model_findings):
            status = "review"
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
