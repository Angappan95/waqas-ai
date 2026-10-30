"""Input validation and deterministic response checks."""

from __future__ import annotations

import re
import unicodedata
from math import ceil
from typing import Any

from .config import (
    HEURISTIC_VERSION,
    NEGATION_LOOKBACK_CHARS,
    NEGATION_LOOKBACK_WORDS,
    NEGATION_TERMS,
    PROMPT_MANIPULATION_PATTERNS,
    REQUIRED_KEYWORD_COVERAGE,
    RISKY_TERMS,
    SENSITIVE_REQUEST_PATTERNS,
    STOP_WORDS,
)

_RISKY_PATTERNS = tuple(
    (term, re.compile(rf"\b{re.escape(term)}\b")) for term in RISKY_TERMS
)


def normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.replace("can't", "cannot").replace("can’t", "cannot")
    normalized = normalized.replace("don't", "do not").replace("don’t", "do not")
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _normalize_with_offsets(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Normalize text while retaining a map back to original character offsets."""
    chars: list[str] = []
    offsets: list[tuple[int, int]] = []
    cluster: list[str] = []
    cluster_start = 0

    def flush_cluster(end: int) -> None:
        if not cluster:
            return
        normalized_cluster = unicodedata.normalize("NFKC", "".join(cluster)).casefold()
        chars.extend(normalized_cluster)
        offsets.extend([(cluster_start, end)] * len(normalized_cluster))
        cluster.clear()

    for index, character in enumerate(text):
        if cluster and not unicodedata.combining(character):
            flush_cluster(index)
        if not cluster:
            cluster_start = index
        cluster.append(character)
    flush_cluster(len(text))
    for source, replacement in (("can't", "cannot"), ("can’t", "cannot"), ("don't", "do not"), ("don’t", "do not")):
        current = "".join(chars)
        cursor = 0
        while (start := current.find(source, cursor)) >= 0:
            end = start + len(source)
            source_span = (min(span[0] for span in offsets[start:end]), max(span[1] for span in offsets[start:end]))
            chars[start:end] = list(replacement)
            offsets[start:end] = [source_span] * len(replacement)
            current = "".join(chars)
            cursor = start + len(replacement)
    collapsed_chars: list[str] = []
    collapsed_offsets: list[tuple[int, int]] = []
    pending_space: tuple[int, int] | None = None
    for character, offset in zip(chars, offsets, strict=True):
        if character.isalnum() or character == "_":
            if pending_space is not None:
                collapsed_chars.append(" ")
                collapsed_offsets.append(pending_space)
                pending_space = None
            collapsed_chars.append(character)
            collapsed_offsets.append(offset)
        elif collapsed_chars:
            pending_space = offset
    return "".join(collapsed_chars), collapsed_offsets


def _spans(offsets: list[tuple[int, int]], matches: list[tuple[int, int, str]]) -> list[dict[str, Any]]:
    evidence = []
    for start, end, code in matches:
        if start < end and end <= len(offsets):
            evidence.append({"code": code, "start": offsets[start][0], "end": offsets[end - 1][1]})
    return evidence


def _preceding_is_negated(text: str, start: int) -> bool:
    preceding_words = re.findall(
        r"[\w']+", text[max(0, start - NEGATION_LOOKBACK_CHARS):start].casefold(),
    )
    return any(word in NEGATION_TERMS for word in preceding_words[-NEGATION_LOOKBACK_WORDS:])


def _find_signals(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    ignore_negated: bool = False,
) -> tuple[list[str], list[tuple[int, int, str]]]:
    signals = []
    matches = []
    for label, pattern in patterns:
        found = [
            match for match in pattern.finditer(text)
            if not ignore_negated or not _preceding_is_negated(text, match.start())
        ]
        if found:
            signals.append(label)
            matches.extend((match.start(), match.end(), label) for match in found)
    return signals, matches


def validate_cases(cases: Any) -> list[dict[str, Any]]:
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases.json must contain a non-empty JSON array")

    seen_ids: set[str] = set()
    validated = []
    for index, case in enumerate(cases):
        location = f"cases.json item {index}"
        if not isinstance(case, dict):
            raise ValueError(f"{location} must be an object")
        for field in ("case_id", "user_message", "assistant_response", "policy_context"):
            if field not in case:
                raise ValueError(f"{location} is missing required field {field!r}")
        for field in ("case_id", "user_message", "assistant_response"):
            if not isinstance(case[field], str):
                raise ValueError(f"{location}.{field} must be a string")
        case_id = case["case_id"]
        if not case_id.strip():
            raise ValueError(f"{location}.case_id must not be empty")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case_id {case_id!r}")
        seen_ids.add(case_id)

        policy = case["policy_context"]
        if not isinstance(policy, dict):
            raise ValueError(f"{location}.policy_context must be an object")
        policy_version = policy.get("version", "unspecified")
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError(f"{location}.policy_context.version must be a non-empty string")
        for field in ("allowed_actions", "disallowed_actions", "required_points"):
            values = policy.get(field)
            if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
                raise ValueError(f"{location}.policy_context.{field} must be an array of strings")
        validated.append(case)
    return validated


def check_rules(case: dict[str, Any]) -> dict[str, Any]:
    response = case["assistant_response"]
    normalized_response, response_offsets = _normalize_with_offsets(response)
    sensitive_signals, sensitive_matches = _find_signals(
        normalized_response, SENSITIVE_REQUEST_PATTERNS, ignore_negated=True,
    )
    guarantee_signals, guarantee_matches = _find_signals(
        normalized_response, _RISKY_PATTERNS, ignore_negated=True,
    )
    normalized_user_message, user_offsets = _normalize_with_offsets(case["user_message"])
    prompt_safety_signals, prompt_matches = _find_signals(
        normalized_user_message, PROMPT_MANIPULATION_PATTERNS,
    )

    required_items = []
    rule_findings: list[dict[str, Any]] = []
    if sensitive_signals:
        rule_findings.append({"code": "sensitive_information_request", "policy_reference": {"type": "builtin", "id": "sensitive_information_request"}, "severity": "critical"})
    if guarantee_signals:
        rule_findings.append({"code": "risky_absolute_guarantee", "policy_reference": {"type": "builtin", "id": "risky_absolute_guarantee"}, "severity": "major"})
    for point_index, required_point in enumerate(case["policy_context"]["required_points"]):
        normalized_required = normalize(required_point)
        keywords = [word for word in normalized_required.split() if word not in STOP_WORDS]
        unique_keywords = list(dict.fromkeys(keywords))
        exact_match = bool(normalized_required and f" {normalized_required} " in f" {normalized_response} ")
        keyword_matches = {word: list(re.finditer(rf"\b{re.escape(word)}\b", normalized_response)) for word in unique_keywords}
        matched_keywords = [word for word, matches in keyword_matches.items() if matches]
        threshold = (
            max(1, ceil(len(unique_keywords) * REQUIRED_KEYWORD_COVERAGE))
            if unique_keywords else 1
        )
        covered = exact_match or len(matched_keywords) >= threshold
        if exact_match:
            start = normalized_response.find(normalized_required)
            point_evidence = _spans(response_offsets, [(start, start + len(normalized_required), "required_point")])
            evidence_status = "supported"
        else:
            token_matches = [(match.start(), match.end(), "required_point_keyword")
                             for word in matched_keywords for match in keyword_matches[word]]
            point_evidence = _spans(response_offsets, token_matches)
            evidence_status = "possible_support" if covered else "not_observed"
        required_items.append({
            "index": point_index,
            "required_point": required_point,
            "covered": covered,
            "method": "phrase" if exact_match else "keyword_overlap" if covered else "none",
            "status": evidence_status,
            "keyword_overlap": {
                "matched": matched_keywords,
                "required": unique_keywords,
                "threshold": threshold,
            },
            "evidence": point_evidence,
        })
        if not covered:
            rule_findings.append({"code": "required_point_not_observed", "policy_reference": {"field": "required_points", "index": point_index}, "severity": "minor"})
        elif not exact_match:
            rule_findings.append({"code": "required_point_ambiguous", "policy_reference": {"field": "required_points", "index": point_index}, "severity": "minor"})

    covered_count = sum(item["covered"] for item in required_items)
    return {
        "case_id": case["case_id"],
        "policy_version": case["policy_context"].get("version", "unspecified"),
        "heuristic_version": HEURISTIC_VERSION,
        "sensitive_information_request": {
            "matched": bool(sensitive_signals),
            "signals": sensitive_signals,
            "evidence": _spans(response_offsets, sensitive_matches),
        },
        "risky_absolute_guarantee": {
            "matched": bool(guarantee_signals),
            "signals": guarantee_signals,
            "evidence": _spans(response_offsets, guarantee_matches),
        },
        "prompt_safety": {
            "matched": bool(prompt_safety_signals),
            "signals": prompt_safety_signals,
            "evidence": _spans(user_offsets, prompt_matches),
        },
        "required_point_coverage": {
            "all_covered": covered_count == len(required_items),
            "covered_count": covered_count,
            "total": len(required_items),
            "items": required_items,
        },
        "response_length_chars": len(response),
        "rule_findings": rule_findings,
    }
