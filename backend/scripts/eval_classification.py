"""Run the evaluation set against the configured classification provider and print the numbers.

Usage: make eval-classification   (provider from CLASSIFICATION_PROVIDER, default: the rule based stand-in)
The cases are in eval/classification_cases.jsonl, see eval/README.md.
"""
from pathlib import Path

from dotenv import load_dotenv

from classification.evaluation import format_summary, load_cases, run_cases, summarize
from classification.provider import provider_from_env
from classification.service import Classifier

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")
provider = provider_from_env()
cases = load_cases(ROOT / "eval" / "classification_cases.jsonl")
results = run_cases(cases, lambda store: Classifier(provider, store), ROOT / "eval" / "photos")
print(f"provider: {type(provider).__name__}")
print(format_summary(summarize(results)))
