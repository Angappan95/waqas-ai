"""Command-line entry point for the support-answer evaluator."""

import sys

from support_evaluator.pipeline import main


if __name__ == "__main__":
    sys.exit(main())