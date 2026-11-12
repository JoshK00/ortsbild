"""Run the evaluation set against the configured classification provider and print the numbers.

Usage: make eval-classification   (provider from CLASSIFICATION_PROVIDER, default: the rule based stand-in)
Example: CLASSIFICATION_PROVIDER=anthropic ANTHROPIC_CLASSIFICATION_MODEL=claude-haiku-5-5 make eval-classification
Only the photo cases (saves calls at a provider with a small quota): add the argument --photos-only
The cases are in eval/classification_cases.jsonl, see eval/README.md.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from classification.evaluation import format_summary, load_cases, run_cases, summarize
from classification.provider import provider_from_env
from classification.service import Classifier

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")
provider = provider_from_env()
cases = load_cases(ROOT / "eval" / "classification_cases.jsonl")
if "--photos-only" in sys.argv:
    cases = [case for case in cases if case.get("photo")]
# EVAL_PAUSE_SECONDS: wait between two cases, for a provider that throttles (a rate limit)
pause = float(os.getenv("EVAL_PAUSE_SECONDS", "0"))
results = run_cases(cases, lambda store: Classifier(provider, store), ROOT / "eval" / "photos", pause)
print(f"provider: {type(provider).__name__}")
print(format_summary(summarize(results)))
