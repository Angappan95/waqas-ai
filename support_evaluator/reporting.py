"""Build a reviewer-facing report from the current run's artifacts."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .config import REPORT_EXAMPLE_LIMIT, REPORT_PATTERN_LIMIT, SCORE


def _failure_patterns(
    rules: list[dict[str, Any]], evaluations: list[dict[str, Any]],
) -> Counter[str]:
    patterns: Counter[str] = Counter()
    for rule, evaluation in zip(rules, evaluations, strict=True):
        if rule["sensitive_information_request"]["matched"]:
            patterns["Sensitive-information request pattern"] += 1
        if rule["risky_absolute_guarantee"]["matched"]:
            patterns["Risky absolute-guarantee language"] += 1
        if rule["prompt_safety"]["matched"]:
            patterns["Prompt manipulation attempt"] += 1
        coverage = rule["required_point_coverage"]
        if any(item.get("status") == "not_observed" for item in coverage["items"]):
            patterns["Required guidance not obviously covered"] += 1
        if any(item.get("status") == "possible_support" for item in coverage["items"]):
            patterns["Required guidance needs contextual review"] += 1
        if evaluation["policy_adherence"] != "pass":
            patterns[f"LLM policy adherence: {evaluation['policy_adherence']}"] += 1
        if evaluation["risk_level"] != "low":
            patterns[f"LLM risk level: {evaluation['risk_level']}"] += 1
    return patterns


def _deterministic_examples(rules: list[dict[str, Any]]) -> list[tuple[str, str]]:
    examples = []
    for rule in rules:
        case_id = rule["case_id"]
        if rule["sensitive_information_request"]["matched"]:
            examples.append((case_id, "sensitive-information request pattern matched"))
        if rule["risky_absolute_guarantee"]["matched"]:
            examples.append((case_id, "risky absolute-guarantee language matched"))
        if rule["prompt_safety"]["matched"]:
            examples.append((case_id, "prompt-manipulation language matched"))
        coverage = rule["required_point_coverage"]
        missing = sum(item.get("status") == "not_observed" for item in coverage["items"])
        if missing:
            examples.append((case_id, f"{missing} required point(s) were not obviously covered"))
        ambiguous = sum(item.get("status") == "possible_support" for item in coverage["items"])
        if ambiguous:
            examples.append((case_id, f"{ambiguous} required point(s) had keyword overlap without confirmed semantic coverage"))
    return examples


def _llm_added_value(
    rules: list[dict[str, Any]], evaluations: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    for rule, evaluation in zip(rules, evaluations, strict=True):
        no_rule_alert = (
            not rule["sensitive_information_request"]["matched"]
            and not rule["risky_absolute_guarantee"]["matched"]
            and rule["required_point_coverage"]["all_covered"]
        )
        model_alert = (
            evaluation["policy_adherence"] != "pass"
            or evaluation["risk_level"] != "low"
            or evaluation["customer_helpfulness"] != "pass"
        )
        if no_rule_alert and model_alert:
            return rule["case_id"], evaluation
    return None


def generate_report(
    rules: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    scores: list[dict[str, Any]],
    disagreements: list[dict[str, Any]],
) -> str:
    lines = [
        "# Support Answer Evaluation", "", "## Summary", "",
        "| Case | Score | Status | Rationale |", "| --- | ---: | --- | --- |",
    ]
    for score in scores:
        case_id = score["case_id"].replace("|", "\\|")
        rationale = score["explanation"]["final_rationale"]
        lines.append(f"| {case_id} | {score['score']} | {score['status']} | {rationale} |")

    patterns = _failure_patterns(rules, evaluations)
    lines.extend(["", "## Top Failure Patterns", ""])
    if patterns:
        lines.extend(
            f"- {name}: {count} case(s)"
            for name, count in patterns.most_common(REPORT_PATTERN_LIMIT)
        )
    else:
        lines.append("No configured failure or caution patterns were observed.")

    examples = _deterministic_examples(rules)
    lines.extend(["", "## Deterministic Check Examples", ""])
    lines.extend(
        f"- Case `{case_id}`: {description}."
        for case_id, description in examples[:REPORT_EXAMPLE_LIMIT]
    )
    if len(examples) < 2:
        lines.append(
            f"Only {len(examples)} deterministic example(s) were present; "
            "two could not be demonstrated without fabricating cases."
        )

    lines.extend(["", "## Prompt Safety", ""])
    prompt_flags = [rule for rule in rules if rule["prompt_safety"]["matched"]]
    if prompt_flags:
        for rule in prompt_flags:
            signals = ", ".join(rule["prompt_safety"]["signals"])
            lines.append(f"- Case `{rule['case_id']}`: detected {signals}.")
    else:
        lines.append("No configured prompt-manipulation patterns matched.")

    lines.extend(["", "## Risk Disagreements", ""])
    if disagreements:
        for item in disagreements:
            lines.append(
                f"- Case `{item['case_id']}`: deterministic risk `{item['deterministic_risk']}` "
                f"versus LLM risk `{item['llm_risk']}`. Likely cause: {item['likely_cause']}"
            )
    else:
        lines.append("No low-versus-elevated risk disagreements were found in this run.")

    lines.extend(["", "## Evidence-backed Findings", ""])
    findings_found = False
    for evaluation in evaluations:
        for finding in evaluation.get("findings", []):
            findings_found = True
            reference = finding["policy_reference"]
            if reference.get("type") == "builtin":
                policy_item = f"built-in check `{reference['id']}`"
            else:
                policy_item = f"policy `{reference['field']}[{reference['index']}]`"
            evidence = finding.get("evidence")
            span = "omission" if evidence is None else f"response chars {evidence['start']}-{evidence['end']}"
            lines.append(
                f"- Case `{evaluation['case_id']}`: `{finding['code']}` ({finding['severity']}); "
                f"{policy_item}; {span}."
            )
    if not findings_found:
        lines.append("No evidence-backed findings were returned.")

    lines.extend(["", "## LLM Judgment Beyond Phrase Checks", ""])
    added_value = _llm_added_value(rules, evaluations)
    if added_value:
        case_id, evaluation = added_value
        lines.append(
            f"- Case `{case_id}`: the LLM marked policy `{evaluation['policy_adherence']}`, "
            f"helpfulness `{evaluation['customer_helpfulness']}`, and risk `{evaluation['risk_level']}` "
            "although configured deterministic checks found no alert and all required points covered. "
            "Review the reasoning before treating this qualitative judgment as correct."
        )
    else:
        lines.append(
            "No case in this run demonstrates an LLM concern beyond configured rule signals; "
            "this data-dependent example is unavailable."
        )

    modes = sorted({evaluation["evaluation_mode"] for evaluation in evaluations})
    lines.extend([
        "", "## Limitations", "",
        "- Phrase and keyword checks are screening signals; keyword overlap is marked for contextual review rather than treated as confirmed semantic coverage.",
        "- Negation handling only checks a small preceding word window; quoted or complex language may be misclassified.",
        "- Prompt-safety checks use a limited phrase list and can miss paraphrases or flag quoted examples.",
        "- The mock evaluator mirrors deterministic signals and is not evidence of actual model judgment.",
        "- Gemini review can be inconsistent and is constrained to supplied policy; common-value redaction is not exhaustive.",
        f"- Evaluation mode(s) in this run: {', '.join(modes)}.",
        "", "## Scoring", "",
        f"Scores start at {SCORE.base_score}. Deterministic penalties: sensitive request "
        f"{SCORE.sensitive_request_penalty}, risky guarantee {SCORE.risky_guarantee_penalty}, "
        f"and each unobserved required point {SCORE.missing_required_point_penalty}. "
        f"Unique model findings add severity penalties (critical/major/minor: "
        f"{SCORE.critical_finding_penalty}/{SCORE.major_finding_penalty}/{SCORE.minor_finding_penalty}); "
        "findings matching an existing deterministic reason are counted once. Scores are clamped to "
        f"{SCORE.minimum_score}-{SCORE.maximum_score}. Critical findings or a score below "
        f"{SCORE.fail_below_score} fail; uncertain evidence, other findings, or a score below "
        f"{SCORE.review_below_score} require review. Response length is reported, not penalized.",
        "",
    ])
    return "\n".join(lines)
