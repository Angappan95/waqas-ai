"""Validate artifacts from a completed evaluation run."""

import argparse
import sys
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
    args = parser.parse_args()
    try:
        result = validate_artifacts(root=args.project_root.resolve(), require_finalized=True)
    except Exception as error:
        print(f"Validation failed: {error}", file=sys.stderr)
        return 1
    modes = ", ".join(result["evaluation_modes"])
    print(f"Validation passed: {result['case_count']} case(s); mode(s): {modes}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())