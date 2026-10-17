"""Artifact persistence and validation for completed evaluation runs."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis import build_disagreements
from .config import (
    CALL_STATUS_SUCCEEDED,
    EVALUATION_MODES,
    HEURISTIC_VERSION,
    MOCK_MODEL,
    PIPELINE_STAGES,
    PROJECT_ROOT,
    REQUIRED_ARTIFACTS,
    RUN_STATUS_FINALIZED,
    RUN_STATUS_IN_PROGRESS,
)
from .llm import validate_evaluation
from .rules import check_rules, validate_cases
from .scoring import aggregate_scores


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path.name} is not valid JSON: {error}") from error


def _validate_rule_result(rule: Any, expected_case_id: str) -> None:
    if not isinstance(rule, dict) or rule.get("case_id") != expected_case_id:
        raise ValueError(f"rule check is invalid for case {expected_case_id!r}")
    if rule.get("heuristic_version") != HEURISTIC_VERSION:
        raise ValueError("rule-check artifact has an unsupported heuristic version")
    for field in ("sensitive_information_request", "risky_absolute_guarantee", "prompt_safety"):
        signal = rule.get(field)
        if (
            not isinstance(signal, dict)
            or not isinstance(signal.get("matched"), bool)
            or not isinstance(signal.get("signals"), list)
            or any(not isinstance(item, str) for item in signal["signals"])
            or signal["matched"] != bool(signal["signals"])
        ):
            raise ValueError(f"rule-check signal {field!r} is invalid for case {expected_case_id!r}")

    coverage = rule.get("required_point_coverage")
    if not isinstance(coverage, dict) or not isinstance(coverage.get("items"), list):
        raise ValueError(f"required-point coverage is invalid for case {expected_case_id!r}")
    items = coverage["items"]
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("required_point"), str)
            or not isinstance(item.get("covered"), bool)
            or item.get("method") not in {"phrase", "keyword_overlap", "none"}
        ):
            raise ValueError(f"required-point entry is invalid for case {expected_case_id!r}")
    covered = sum(item["covered"] for item in items)
    if (
        coverage.get("covered_count") != covered
        or coverage.get("total") != len(items)
        or coverage.get("all_covered") != (covered == len(items))
    ):
        raise ValueError(f"required-point summary is inconsistent for case {expected_case_id!r}")
    response_length = rule.get("response_length_chars")
    if not isinstance(response_length, int) or response_length < 0:
        raise ValueError(f"response length is invalid for case {expected_case_id!r}")


def _read_call_log(path: Path) -> list[dict[str, Any]]:
    calls = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            call = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"llm_calls.jsonl line {line_number} is invalid JSON") from error
        if not isinstance(call, dict):
            raise ValueError(f"llm_calls.jsonl line {line_number} must contain a JSON object")
        calls.append(call)
    return calls


def _validate_call_log(
    calls: list[dict[str, Any]], evaluations: list[dict[str, Any]],
    case_ids: list[str], manifest: dict[str, Any],
) -> None:
    if len(calls) != len(case_ids):
        raise ValueError("llm_calls.jsonl must contain exactly one record per case")
    for call, evaluation, case_id in zip(calls, evaluations, case_ids, strict=True):
        if call.get("stage") != "LLM_EVAL" or call.get("case_id") != case_id:
            raise ValueError(f"LLM call log does not match case {case_id!r}")
        if call.get("status") != CALL_STATUS_SUCCEEDED:
            raise ValueError(f"LLM call for {case_id!r} is not marked successful")
        mode = evaluation["evaluation_mode"]
        if call.get("provider") != mode:
            raise ValueError(f"LLM call provider does not match evaluation for {case_id!r}")
        expected_model = MOCK_MODEL if mode == "mock" else manifest.get("model")
        if not isinstance(expected_model, str) or call.get("model") != expected_model:
            raise ValueError(f"LLM call model does not match evaluation for {case_id!r}")
        if (
            call.get("input_artifacts") != ["cases.json", "rule_checks.json"]
            or call.get("output_artifact") != "llm_evaluations.json"
        ):
            raise ValueError(f"LLM call artifact paths are invalid for {case_id!r}")
        prompt_hash = call.get("prompt_hash")
        if not isinstance(prompt_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", prompt_hash):
            raise ValueError(f"LLM call prompt_hash is invalid for {case_id!r}")
        timestamp_value = call.get("timestamp")
        try:
            timestamp = datetime.fromisoformat(timestamp_value.replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"LLM call timestamp is invalid for {case_id!r}") from None
        if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
            raise ValueError(f"LLM call timestamp must be UTC for {case_id!r}")


def _validate_manifest(manifest: Any, require_finalized: bool) -> None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("run_id"), str):
        raise ValueError("run_manifest.json is invalid")
    stages = manifest.get("stages")
    expected_stages = list(PIPELINE_STAGES if require_finalized else PIPELINE_STAGES[:6])
    if (
        not isinstance(stages, list)
        or any(not isinstance(item, dict) for item in stages)
        or [item.get("stage") for item in stages] != expected_stages
    ):
        raise ValueError("run_manifest.json does not show the required ordered pipeline stages")
    timestamps = []
    for stage in stages:
        try:
            timestamp = datetime.fromisoformat(stage["completed_at"].replace("Z", "+00:00"))
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError("run_manifest.json contains an invalid stage timestamp") from None
        if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
            raise ValueError("run_manifest.json stage timestamps must be UTC")
        timestamps.append(timestamp)
    if timestamps != sorted(timestamps):
        raise ValueError("run_manifest.json stage timestamps are out of order")
    expected_state = RUN_STATUS_FINALIZED if require_finalized else RUN_STATUS_IN_PROGRESS
    if manifest.get("state") != expected_state:
        raise ValueError(f"run_manifest.json must be in state {expected_state}")


def validate_artifacts(
    root: Path = PROJECT_ROOT,
    require_finalized: bool = True,
    manifest_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases_path = root / "cases.json"
    required_paths = [cases_path] + [root / name for name in REQUIRED_ARTIFACTS]
    missing = [path.name for path in required_paths if not path.is_file()]
    if missing:
        raise ValueError("missing required artifacts: " + ", ".join(missing))

    cases = validate_cases(load_json(cases_path))
    rules = load_json(root / "rule_checks.json")
    evaluations = load_json(root / "llm_evaluations.json")
    scores = load_json(root / "final_scores.json")
    disagreements_path = root / "disagreements.json"
    disagreements = load_json(disagreements_path) if disagreements_path.is_file() else None
    manifest = manifest_override or load_json(root / "run_manifest.json")
    if not all(isinstance(records, list) for records in (rules, evaluations, scores)):
        raise ValueError(
            "rule checks, evaluations, and scores must be JSON arrays"
        )
    if disagreements is not None and not isinstance(disagreements, list):
        raise ValueError("disagreements.json must contain a JSON array when present")

    case_ids = [case["case_id"] for case in cases]
    record_sets = (
        ("rule checks", rules),
        ("LLM evaluations", evaluations),
        ("final scores", scores),
    )
    for name, records in record_sets:
        record_ids = [record.get("case_id") if isinstance(record, dict) else None for record in records]
        if record_ids != case_ids:
            raise ValueError(f"{name} must contain exactly one ordered record per input case")

    for case, rule, case_id in zip(cases, rules, case_ids, strict=True):
        _validate_rule_result(rule, case_id)
        if rule != check_rules(case):
            raise ValueError(f"rule-check artifact does not match deterministic checks for {case_id!r}")
    for evaluation, case_id in zip(evaluations, case_ids, strict=True):
        if evaluation.get("evaluation_mode") not in EVALUATION_MODES:
            raise ValueError(f"evaluation for {case_id!r} is missing a valid evaluation_mode")
        schema = {key: value for key, value in evaluation.items() if key != "evaluation_mode"}
        validate_evaluation(schema, case_id)
    expected_scores = aggregate_scores(rules, evaluations)
    if scores != expected_scores:
        raise ValueError("final_scores.json does not match the deterministic aggregation formula")
    if disagreements is not None and disagreements != build_disagreements(rules, evaluations):
        raise ValueError("disagreements.json does not match the deterministic risk comparison")

    _validate_manifest(manifest, require_finalized)
    calls = _read_call_log(root / "llm_calls.jsonl")
    _validate_call_log(calls, evaluations, case_ids, manifest)
    report = (root / "report.md").read_text(encoding="utf-8")
    _validate_report(report, case_ids)
    return {
        "case_count": len(cases),
        "evaluation_modes": sorted({evaluation["evaluation_mode"] for evaluation in evaluations}),
    }


def _validate_report(report: str, case_ids: list[str]) -> None:
    required_headings = (
        "## Summary", "## Top Failure Patterns", "## Deterministic Check Examples",
        "## LLM Judgment Beyond Phrase Checks", "## Limitations", "## Scoring",
    )
    if not report.strip():
        raise ValueError("report.md is empty")
    missing = [heading for heading in required_headings if heading not in report]
    if missing:
        raise ValueError("report.md is missing required section(s): " + ", ".join(missing))
    summary = report.split("## Summary", 1)[1].split("## ", 1)[0]
    absent_cases = []
    for case_id in case_ids:
        escaped_case_id = case_id.replace("|", "\\|")
        if f"| {escaped_case_id} |" not in summary:
            absent_cases.append(case_id)
    if absent_cases:
        raise ValueError("report.md summary is missing case(s): " + ", ".join(absent_cases))
    examples = report.split("## Deterministic Check Examples", 1)[1].split("## ", 1)[0]
    example_lines = [line for line in examples.splitlines() if line.startswith("- Case `")]
    if len(example_lines) < 2 and "could not be demonstrated" not in examples:
        raise ValueError("report.md must include two deterministic examples or disclose the limitation")
    added_value = report.split("## LLM Judgment Beyond Phrase Checks", 1)[1].split("## ", 1)[0]
    unavailable_phrases = (
        "No case in this run demonstrates",
        "data-dependent example is unavailable",
    )
    if not any(phrase in added_value for phrase in unavailable_phrases) and "- Case `" not in added_value:
        raise ValueError("report.md must include an LLM-added-value example or disclose its unavailability")
