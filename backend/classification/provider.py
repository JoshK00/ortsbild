import os
from typing import Protocol

from classification.emergency import mentions_emergency
from classification.models import Classification, ClassificationInput


class ClassificationError(Exception):
    """The provider did not give a usable answer (invalid structure, wrong values). Not a reason to retry blindly."""


class ClassificationProvider(Protocol):
    """Whatever turns a `ClassificationInput` into a `Classification`: a model behind an API, or a stand-in.

    A real provider calls a fixed endpoint (from the server configuration, never from a request) with
    `prompt.SYSTEM_PROMPT` and `prompt.user_message`, forces the structure of `Classification` and raises
    `ClassificationError` if the answer does not fit. Network errors are raised as they are, the caller retries them.
    """

    def classify(self, data: ClassificationInput) -> Classification: ...


# Words per category for the stand-in. German reports, so German words (stems, lower case).
CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "litter": ("müll", "abfall", "sperrmüll", "unrat", "dreck", "verschmutz", "mülleimer", "mülltonne", "flasche", "scherben", "sperrmuell"),
    "graffiti": ("graffiti", "schmier", "sprüh", "gesprüht", "tag ", "aufkleber"),
    "street_light": ("laterne", "straßenlaterne", "strassenlaterne", "straßenbeleuchtung", "beleuchtung", "lampe", "ampel", "dunkel"),
    "playground_equipment": ("spielplatz", "schaukel", "rutsche", "klettergerüst", "wippe", "sandkasten", "spielgerät"),
    "pothole": ("schlagloch", "schlaglöcher", "loch in", "straßenschaden", "riss in", "asphalt", "gehweg", "radweg", "bordstein"),
    "tree": ("baum", "bäume", "ast ", "äste", "umgestürzt", "stamm", "zweig"),
}
HAZARD_WORDS = ("gefahr", "gefährlich", "stolper", "sturz", "gestürzt", "scharf", "offen", "lose", "wackelt", "abgebrochen", "herabfall", "umgestürzt", "tief", "kind")


class RuleBasedProvider:
    """The fallback without a model: it looks at the words of the text only, the photo is ignored.

    It is the default of `CLASSIFICATION_PROVIDER` and what the tests use. Production sets `anthropic` (claude.py).
    Its confidence is low on purpose, so nobody takes its answers for more than they are.
    """

    def classify(self, data: ClassificationInput) -> Classification:
        text = (data.text or "").lower() + " "
        hits = {category: sum(text.count(word) for word in words) for category, words in CATEGORY_WORDS.items()}
        best, count = max(hits.items(), key=lambda item: item[1])
        if count == 0:
            best, confidence = "other", 0.2
        else:
            confidence = 0.6 if sum(1 for value in hits.values() if value) == 1 else 0.4
        hazard = any(word in text for word in HAZARD_WORDS)
        return Classification(
            category=best,
            lane="hazard" if hazard else "nuisance",
            emergency=mentions_emergency(data.text),
            confidence=confidence,
        )


def provider_from_env() -> ClassificationProvider:
    """The provider named in CLASSIFICATION_PROVIDER (default `rules`). An unknown name stops the start of the server."""
    name = os.getenv("CLASSIFICATION_PROVIDER", "rules")
    if name == "rules":
        return RuleBasedProvider()
    if name == "anthropic":
        from classification.claude import DEFAULT_MODEL, ClaudeProvider

        return ClaudeProvider(os.environ["ANTHROPIC_KEY"], os.getenv("ANTHROPIC_CLASSIFICATION_MODEL", DEFAULT_MODEL))
    raise ValueError(f"unknown CLASSIFICATION_PROVIDER: {name}")
