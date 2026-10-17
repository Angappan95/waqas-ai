# Waqas AI Support Answer Evaluator

This command-line pipeline checks support answers against each case's supplied policy. Python performs deterministic checks and computes scores. Gemini provides case-level qualitative review when configured; otherwise a clearly labeled deterministic mock keeps the pipeline runnable without credentials.

## Run

This project requires Python 3.10 or newer and uses only the Python standard library for mock evaluation, Gemini requests, and validation. Run directly from a clean checkout:

```sh
python main.py
python validate.py
```

By default, the project root is the repository directory. To read cases and write artifacts elsewhere, pass `--project-root` to either command:

```sh
python main.py --project-root ./runs/example
python validate.py --project-root ./runs/example
```

The selected directory must contain `cases.json`; generated artifacts are written there. Replace it with a UTF-8 JSON array using the same schema. Every case needs a unique non-empty `case_id`, string `user_message` and `assistant_response`, and a `policy_context` containing string arrays named `allowed_actions`, `disallowed_actions`, and `required_points`. Empty input is rejected.

## Gemini

Set both environment variables to use live evaluation:

```sh
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-2.5-flash"
uv run python main.py
```

The key is sent in an HTTP header and is never written to artifacts. If the key is set, a missing model, provider error, or invalid response fails the run; it does not silently switch to mock mode. Without a key, each case receives one deterministic mock evaluation labeled `evaluation_mode: mock`, logged with provider `mock` and model `deterministic-mock-v1`.

Live requests redact common email addresses, phone-like numbers, labeled account/payment identifiers, and values following password/secret labels. Placeholders are `[EMAIL_REDACTED]`, `[PHONE_REDACTED]`, `[ACCOUNT_ID_REDACTED]`, and `[SECRET_REDACTED]`. These patterns are not exhaustive. Original input stays local except for the redacted request sent to Gemini; raw case text is not copied to reports or call logs.

## Artifacts and Design

The pipeline creates `rule_checks.json`, `llm_evaluations.json`, `final_scores.json`, `report.md`, `llm_calls.jsonl`, and `run_manifest.json`. It also creates the optional stretch-goal artifact `disagreements.json`. Each run replaces generated outputs. The manifest records ordered stage completion and marks failed runs incomplete. Attempted evaluator calls are logged with success/failure status, including failed provider or schema-validation responses. `validate.py` checks schemas, case cardinality, deterministic rule and score recomputation, report sections, call-log consistency, and stage ordering without contacting a provider.

Implementation is divided into `support_evaluator/config.py`, `rules.py`, `llm.py`, `scoring.py`, `reporting.py`, `artifacts.py`, and `pipeline.py`; `main.py` and `validate.py` are small command-line entry points. The pipeline advances stages in explicit sequence and records a failed manifest when a stage raises an error.

Rule checks use NFKC normalization, case-folding, and punctuation-to-space normalization. Sensitive requests match a small set of direct requests for passwords, passcodes, verification codes, API keys, and secrets; nearby negation suppresses a match. Risky absolute terms are `always`, `instantly`, `immediately`, `guaranteed`, `guarantee`, and `definitely`, with the same limited negation window. Required-point coverage is either a normalized phrase match or at least half of the distinct non-stopword tokens; the artifact records matched tokens. Prompt-safety checks flag a limited set of user-message phrases that attempt to override policy or evaluator instructions. `disagreements.json` records low-versus-elevated deterministic/model risk differences and likely causes. These are reproducible heuristics, not a policy classifier. Response length is Python character count.

Scores start at 100. Rule penalties: sensitive request 45, risky guarantee 30, and 10 per uncovered required point. Evaluation penalties: policy fail/warning 35/15, helpfulness fail/warning 15/7, and high/medium risk 25/10. Scores are clamped to 0-100. Fail applies for a sensitive request, policy fail, high risk, or score below 50. Otherwise, review applies below 85 or for any warning/medium risk. Response length is reported but not penalized. Each score explanation itemizes its adjustments.

The reliability feature is strict structured-response validation with no retries. Invalid live-model output stops the run. Report examples are derived from current results; when replacement data cannot demonstrate a requested example, the report says so rather than fabricating one. The mock evaluator mirrors configured rule signals and is not a substitute for real model judgment.
