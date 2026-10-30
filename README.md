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
python validate.py --project-root ./runs/example --run-id <run-id>
```

The selected directory must contain `cases.json`; replace it with a UTF-8 JSON array using the documented schema. Every case needs a unique non-empty `case_id`, string `user_message` and `assistant_response`, and a `policy_context` containing string arrays named `allowed_actions`, `disallowed_actions`, and `required_points`. Add a `version` string to each policy context so reports and runs identify the policy used. Empty input is rejected.

## Gemini

Set both environment variables to use live evaluation:

```sh
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-2.5-flash"
uv run python main.py
```

The key is sent in an HTTP header and is never written to artifacts. If the key is set, a missing model, provider error, or invalid response fails the run; it does not silently switch to mock mode. Without a key, each case receives one deterministic mock evaluation labeled `evaluation_mode: mock`, logged with provider `mock` and model `deterministic-mock-v1`.

Live requests redact common email addresses (`[EMAIL_REDACTED]`), phone-like numbers (`[PHONE_REDACTED]`), labeled account/payment identifiers (`[ACCOUNT_ID_REDACTED]`), and values following password/secret labels (`[SECRET_REDACTED]`). These patterns are not exhaustive. The evaluator asks Gemini to ground each concern in a supplied policy item and an exact span of the response as sent to the model. It verifies the span before accepting the result, then stores only its offsets and a hash, not the quoted text. Common sensitive values in generated rationale are redacted before artifacts are written; avoid sending data that must never leave your environment.

## Artifacts and Design

Every attempt is stored immutably under `.runs/<run_id>/`, including its input snapshot, policy digest, manifest, checks, evaluations, scores, report, and call log. `.runs/index.json` tracks the latest attempt and latest successful run. Root-level artifact names remain as a convenience view of the latest attempt; they are never the archive. A failed latest attempt makes `python validate.py` fail, while an older successful run can be checked with `python validate.py --run-id <run-id>`. Attempted evaluator calls are logged with success/failure status. Validation checks schemas, case cardinality, deterministic rule and score recomputation, evidence references, report sections, call-log consistency, and stage ordering without contacting a provider.

Implementation is divided into `support_evaluator/config.py`, `rules.py`, `llm.py`, `scoring.py`, `reporting.py`, `artifacts.py`, `run_store.py`, and `pipeline.py`; `main.py` and `validate.py` are small command-line entry points. The pipeline advances stages in explicit sequence and records a failed manifest when a stage raises an error.

Rule checks use NFKC normalization, case-folding, and punctuation-to-space normalization. Sensitive requests and risky absolute terms are screening signals with source offsets; they do not store matched text. Required-point results distinguish exact phrase support, possible keyword support, and points not observed. Keyword overlap is not treated as proof of semantic compliance and routes the case to review. Prompt-safety checks flag a limited set of user-message patterns. `disagreements.json` records low-versus-elevated deterministic/model risk differences. These are reproducible heuristics, not a policy classifier. Response length is Python character count.

Scores start at 100. Rule penalties: sensitive request 45, risky guarantee 30, and 10 per unobserved required point. Independent model findings add 45/25/10 points for critical/major/minor severity. A model finding with the same code and policy reference as a deterministic finding is counted once. Critical findings or a score below 50 fail; uncertainty, other findings, or a score below 85 require review. Scores remain code-computed and itemize their adjustments.

Invalid or ungrounded live-model output stops the run. Each archived run snapshots its inputs and policy context with SHA-256 digests, so later runs cannot erase or silently change prior results. Report examples are derived from current results; when replacement data cannot demonstrate a requested example, the report says so rather than fabricating one. The mock evaluator mirrors configured rule signals and is not a substitute for real model judgment.
