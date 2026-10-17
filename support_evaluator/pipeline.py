"""Orchestrate the staged answer-evaluation pipeline."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from .analysis import build_disagreements
from .artifacts import load_json, validate_artifacts, write_json
from .config import (
    CALL_STATUS_FAILED,
    CALL_STATUS_SUCCEEDED,
    GENERATED_ARTIFACTS,
    PIPELINE_STAGES,
    PROJECT_ROOT,
    PROJECT_ROOT_ARGUMENT,
    RUN_STATUS_FAILED,
    RUN_STATUS_FINALIZED,
    RUN_STATUS_IN_PROGRESS,
    EvaluatorConfig,
)
from .llm import EvaluationError, evaluate_case
from .reporting import generate_report
from .rules import check_rules, validate_cases
from .scoring import aggregate_scores


class PipelineState(TypedDict, total=False):
    """Values produced and consumed by pipeline stages."""

    root: Path
    run_id: str
    completed_stages: list[dict[str, str]]
    cases: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    disagreements: list[dict[str, Any]]
    evaluator_mode: str
    model: str
    validation_result: dict[str, Any]
    failed_stage: str
    error: str


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _manifest(state: PipelineState, status: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "run_id": state["run_id"],
        "state": status,
        "stages": state["completed_stages"],
    }
    if state.get("model"):
        manifest["model"] = state["model"]
    if state.get("failed_stage"):
        manifest["failed_stage"] = state["failed_stage"]
    if state.get("error"):
        manifest["error"] = state["error"]
    return manifest


def _load_case_inputs(state: PipelineState) -> dict[str, Any]:
    cases = validate_cases(load_json(state["root"] / "cases.json"))
    return {"cases": cases}


def _run_rule_checks(state: PipelineState) -> dict[str, Any]:
    rules = [check_rules(case) for case in state["cases"]]
    write_json(state["root"] / "rule_checks.json", rules)
    return {"rules": rules}


def _call_log_record(
    *,
    case_id: str,
    evaluator: EvaluatorConfig,
    prompt_hash: str,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "LLM_EVAL",
        "case_id": case_id,
        "timestamp": _timestamp(),
        "provider": evaluator.mode,
        "model": evaluator.model_name,
        "prompt_hash": prompt_hash,
        "input_artifacts": ["cases.json", "rule_checks.json"],
        "output_artifact": "llm_evaluations.json",
        "status": status,
    }
    if error is not None:
        record["error"] = error
    return record


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _run_llm_evaluations(state: PipelineState) -> dict[str, Any]:
    evaluator = EvaluatorConfig.from_environment()
    calls_path = state["root"] / "llm_calls.jsonl"
    calls_path.write_text("", encoding="utf-8")
    evaluations = []
    for case, rule in zip(state["cases"], state["rules"], strict=True):
        try:
            result = evaluate_case(case, rule, evaluator)
        except EvaluationError as error:
            _append_jsonl(calls_path, _call_log_record(
                case_id=error.case_id,
                evaluator=evaluator,
                prompt_hash=error.prompt_hash,
                status=CALL_STATUS_FAILED,
                error=str(error),
            ))
            raise
        evaluations.append(result.evaluation)
        _append_jsonl(calls_path, _call_log_record(
            case_id=case["case_id"],
            evaluator=evaluator,
            prompt_hash=result.prompt_hash,
            status=CALL_STATUS_SUCCEEDED,
        ))
    write_json(state["root"] / "llm_evaluations.json", evaluations)
    return {
        "evaluations": evaluations,
        "evaluator_mode": evaluator.mode,
        "model": evaluator.model_name,
    }


def _aggregate_scores(state: PipelineState) -> dict[str, Any]:
    scores = aggregate_scores(state["rules"], state["evaluations"])
    disagreements = build_disagreements(state["rules"], state["evaluations"])
    write_json(state["root"] / "final_scores.json", scores)
    write_json(state["root"] / "disagreements.json", disagreements)
    return {"scores": scores, "disagreements": disagreements}


def _generate_report(state: PipelineState) -> dict[str, Any]:
    report = generate_report(
        state["rules"], state["evaluations"], state["scores"], state["disagreements"],
    )
    (state["root"] / "report.md").write_text(report, encoding="utf-8")
    return {}


def _validate_run(state: PipelineState) -> dict[str, Any]:
    manifest = _manifest(state, RUN_STATUS_IN_PROGRESS)
    write_json(state["root"] / "run_manifest.json", manifest)
    result = validate_artifacts(
        root=state["root"],
        require_finalized=False,
        manifest_override=manifest,
    )
    return {"validation_result": result}


def run_pipeline(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    project_root = root.expanduser().resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    for artifact in GENERATED_ARTIFACTS:
        path = project_root / artifact
        if path.exists():
            path.unlink()

    state: PipelineState = {
        "root": project_root,
        "run_id": str(uuid.uuid4()),
        "completed_stages": [{"stage": PIPELINE_STAGES[0], "completed_at": _timestamp()}],
    }
    operations = (
        _load_case_inputs,
        _run_rule_checks,
        _run_llm_evaluations,
        _aggregate_scores,
        _generate_report,
        _validate_run,
    )
    current_stage = PIPELINE_STAGES[1]
    try:
        for current_stage, operation in zip(PIPELINE_STAGES[1:7], operations, strict=True):
            state.update(operation(state))
            state["completed_stages"].append(
                {"stage": current_stage, "completed_at": _timestamp()},
            )
        state["completed_stages"].append(
            {"stage": RUN_STATUS_FINALIZED, "completed_at": _timestamp()},
        )
        write_json(project_root / "run_manifest.json", _manifest(state, RUN_STATUS_FINALIZED))
    except Exception as error:
        state["failed_stage"] = current_stage
        state["error"] = f"{type(error).__name__}: {error}"
        write_json(project_root / "run_manifest.json", _manifest(state, RUN_STATUS_FAILED))
        raise RuntimeError(f"{current_stage}: {state['error']}") from error
    return {
        "case_count": len(state["cases"]),
        "mode": state["evaluator_mode"],
        "run_id": state["run_id"],
        "project_root": str(project_root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate support-answer policy and quality.")
    parser.add_argument(
        PROJECT_ROOT_ARGUMENT,
        type=Path,
        default=PROJECT_ROOT,
        help="directory containing cases.json and evaluation artifacts",
    )
    args = parser.parse_args(argv)
    try:
        result = run_pipeline(args.project_root)
    except Exception as error:
        print(f"Pipeline failed: {error}", file=sys.stderr)
        return 1
    print(
        f"Evaluation complete: {result['case_count']} case(s), mode={result['mode']}, "
        f"project_root={result['project_root']}."
    )
    return 0
