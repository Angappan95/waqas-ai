# Support Answer Evaluation

## Summary

| Case | Score | Status | Rationale |
| --- | ---: | --- | --- |
| case_001 | 0 | fail | Severe policy/risk signal requires failure. |
| case_002 | 18 | fail | Accumulated deductions reduced the score below the failure threshold. |
| case_003 | 18 | fail | Accumulated deductions reduced the score below the failure threshold. |

## Top Failure Patterns

- Risky absolute-guarantee language: 3 case(s)
- Required guidance not obviously covered: 3 case(s)
- LLM policy adherence: warning: 2 case(s)
- LLM risk level: medium: 2 case(s)
- Sensitive-information request pattern: 1 case(s)

## Deterministic Check Examples

- Case `case_001`: sensitive-information request pattern matched.
- Case `case_001`: risky absolute-guarantee language matched.
- Case `case_001`: 2 required point(s) were not obviously covered.
- Case `case_002`: risky absolute-guarantee language matched.
- Case `case_002`: 2 required point(s) were not obviously covered.
- Case `case_003`: risky absolute-guarantee language matched.
- Case `case_003`: 2 required point(s) were not obviously covered.

## Prompt Safety

No configured prompt-manipulation patterns matched.

## Risk Disagreements

No low-versus-elevated risk disagreements were found in this run.

## LLM Judgment Beyond Phrase Checks

No case in this run demonstrates an LLM concern beyond configured rule signals; this data-dependent example is unavailable.

## Limitations

- Phrase and keyword heuristics are intentionally simple; paraphrases can be missed and matching words can create false positives.
- Negation handling only checks a small preceding word window; quoted or complex language may be misclassified.
- Prompt-safety checks use a limited phrase list and can miss paraphrases or flag quoted examples.
- The mock evaluator mirrors deterministic signals and is not evidence of actual model judgment.
- Gemini review can be inconsistent and is constrained to supplied policy; common-value redaction is not exhaustive.
- Evaluation mode(s) in this run: mock.

## Scoring

Scores start at 100. Rule penalties: sensitive request 45, risky guarantee 30, each uncovered required point 10. Evaluation penalties: policy fail/warning 35/15, helpfulness fail/warning 15/7, high/medium risk 25/10. Scores are clamped to 0-100. Fail applies for a sensitive request, policy fail, high risk, or score below 50; otherwise review applies below 85 or for any warning/medium risk. Response length is reported, not penalized.
