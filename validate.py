"""Validate artifacts from a completed evaluation run."""

import argparse
import sys
import uuid
from pathlib import Path

from support_evaluator.config import PROJECT_ROOT
from support_evaluator.artifacts import validate_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="directory containing cases.json and evaluation artifacts",
    )
    parser.add_argument(
        "--run-id",
        help="validate an archived run from <project-root>/.runs/<run-id>",
    )
    args = parser.parse_args()
    validation_root = args.project_root.resolve()
    if args.run_id:
        try:
            parsed_run_id = uuid.UUID(args.run_id)
        except ValueError:
            print("Validation failed: run-id must be a UUID", file=sys.stderr)
            return 1
        validation_root = validation_root / ".runs" / str(parsed_run_id)
        if not validation_root.is_dir():
            print(f"Validation failed: archived run {args.run_id!r} was not found", file=sys.stderr)
            return 1
    try:
        result = validate_artifacts(root=validation_root, require_finalized=True)
    except Exception as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    modes = ", ".join(result["evaluation_modes"])
    print(f"Validation passed: {result['case_count']} case(s); mode(s): {modes}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
