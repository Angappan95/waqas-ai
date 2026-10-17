"""Shared application settings and environment-derived evaluator configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
GENERATED_ARTIFACTS = (
    "rule_checks.json",
    "llm_evaluations.json",
    "final_scores.json",
    "report.md",
    "llm_calls.jsonl",
    "run_manifest.json",
    "disagreements.json",
)
REQUIRED_ARTIFACTS = tuple(
    name for name in GENERATED_ARTIFACTS if name != "disagreements.json"
)
PIPELINE_STAGES = (
    "INIT", "CASES_LOADED", "RULE_CHECKS_COMPLETE", "LLM_EVAL_COMPLETE",
    "SCORES_AGGREGATED", "REPORT_GENERATED", "VALIDATION_COMPLETE", "RESULTS_FINALISED",
)
RUN_STATUS_IN_PROGRESS = "IN_PROGRESS"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_FINALIZED = "RESULTS_FINALISED"
PROJECT_ROOT_ARGUMENT = "--project-root"

HEURISTIC_VERSION = "phrase-coverage-v1"
STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could",
    "do", "does", "for", "from", "how", "i", "if", "in", "is", "it",
    "may", "me", "my", "of", "on", "or", "our", "please", "the", "to",
    "we", "what", "when", "will", "with", "you", "your",
})
REQUIRED_KEYWORD_COVERAGE = 0.5
SENSITIVE_REQUEST_PATTERNS = (
    ("direct_secret_request", re.compile(
        r"\b(?:send|share|provide|tell|give|reply\s+with|enter|type)\s+"
        r"(?:me\s+)?(?:your\s+)?(?:full\s+)?"
        r"(?:password|passcode|pin|security\s+code|verification\s+code|"
        r"one\s+time\s+code|api\s+key|secret)\b"
    )),
    ("explicit_password_question", re.compile(r"\bwhat\s+is\s+(?:your\s+)?password\b")),
    ("request_for_password", re.compile(r"\b(?:ask|request)\s+for\s+(?:your\s+)?password\b")),
)
PROMPT_MANIPULATION_PATTERNS = (
    ("ignore_policy_or_instructions", re.compile(
        r"\b(?:ignore|disregard|bypass|override|forget)\b.{0,60}"
        r"\b(?:policy|rules?|instructions?|system|previous|prior)\b"
    )),
    ("pretend_action_is_allowed", re.compile(
        r"\bpretend\b.{0,80}\b(?:allowed|permitted|acceptable)\b"
    )),
    ("reclassify_disallowed_action", re.compile(
        r"\b(?:treat|consider|mark)\b.{0,60}\b(?:this|it|that)\b.{0,40}"
        r"\b(?:allowed|permitted|acceptable)\b"
    )),
)
RISKY_TERMS = ("always", "instantly", "immediately", "guaranteed", "guarantee", "definitely")
NEGATION_TERMS = frozenset({"cannot", "not", "never", "avoid", "without"})
NEGATION_LOOKBACK_CHARS = 45
NEGATION_LOOKBACK_WORDS = 4

REDACTION_PATTERNS = (
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[EMAIL_REDACTED]"),
    (re.compile(r"(?<!\w)\+?\d[\d().\- ]{7,}\d(?!\w)"), "[PHONE_REDACTED]"),
    (
        re.compile(
            r"\b(?:account|card|routing|payment|transaction)\s*"
            r"(?:(?:number|no\.?|id)\s*[:#-]?|[#:]\s*)"
            r"[A-Z0-9][A-Z0-9-]{5,}\b", re.IGNORECASE,
        ),
        "[ACCOUNT_ID_REDACTED]",
    ),
    (
        re.compile(r"\b(?:password|passcode|secret|api\s+key|token)\s*(?:is|:|=)\s*[^\s,.;]+", re.IGNORECASE),
        "[SECRET_REDACTED]",
    ),
)

MOCK_MODEL = "deterministic-mock-v1"
GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_TIMEOUT_SECONDS = 60
GEMINI_RESPONSE_MIME_TYPE = "application/json"
POLICY_ADHERENCE_VALUES = frozenset({"pass", "warning", "fail"})
HELPFULNESS_VALUES = POLICY_ADHERENCE_VALUES
RISK_LEVEL_VALUES = frozenset({"low", "medium", "high"})
EVALUATION_MODES = frozenset({"mock", "gemini"})
CALL_STATUS_SUCCEEDED = "succeeded"
CALL_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class ScoreConfig:
    base_score: int = 100
    minimum_score: int = 0
    maximum_score: int = 100
    sensitive_request_penalty: int = 45
    risky_guarantee_penalty: int = 30
    missing_required_point_penalty: int = 10
    policy_warning_penalty: int = 15
    policy_fail_penalty: int = 35
    helpfulness_warning_penalty: int = 7
    helpfulness_fail_penalty: int = 15
    medium_risk_penalty: int = 10
    high_risk_penalty: int = 25
    fail_below_score: int = 50
    review_below_score: int = 85


SCORE = ScoreConfig()
REPORT_EXAMPLE_LIMIT = 10
REPORT_PATTERN_LIMIT = 5


@dataclass(frozen=True)
class EvaluatorConfig:
    api_key: str | None
    model: str | None

    @classmethod
    def from_environment(cls) -> "EvaluatorConfig":
        api_key = os.environ.get("GEMINI_API_KEY", "").strip() or None
        model = os.environ.get("GEMINI_MODEL", "").strip() or None
        if api_key and not model:
            raise ValueError("GEMINI_MODEL is required when GEMINI_API_KEY is set")
        return cls(api_key=api_key, model=model)

    @property
    def mode(self) -> str:
        return "gemini" if self.api_key else "mock"

    @property
    def model_name(self) -> str:
        return self.model if self.api_key and self.model else MOCK_MODEL
