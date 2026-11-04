import os
from typing import Protocol

from drafting.models import DraftContent, DraftInput

CATEGORY_DE = {
    "litter": "Müll oder Abfall", "graffiti": "Graffiti", "street_light": "defekte Beleuchtung",
    "playground_equipment": "beschädigtes Spielgerät", "pothole": "Straßenschaden", "tree": "Baum oder Ast", "other": "Mangel im öffentlichen Raum",
}


class DraftError(Exception):
    """The provider did not give a usable draft (refusal, invalid structure). Not a reason to retry blindly."""


class DraftProvider(Protocol):
    """Whatever writes the text of a draft: a model behind an API, or a template.

    A real provider calls a fixed endpoint (from the server configuration, never from a request) with
    `prompt.SYSTEM_PROMPT` and `prompt.user_message`, forces the structure of `DraftContent` and raises `DraftError`
    if the answer does not fit. Network errors are raised as they are, the caller retries them.
    """

    def draft(self, data: DraftInput) -> DraftContent: ...


class TemplateDraftProvider:
    """A fixed German letter, no model. For tests and for running the chain without a model.

    TODO: It writes German whatever language is asked for, and it does not describe anything beyond the category and the
    text of the citizen. It is not what the users should get, a model writes the real draft.
    """

    def draft(self, data: DraftInput) -> DraftContent:
        kind = CATEGORY_DE[data.category]
        lines = ["Sehr geehrte Damen und Herren,", "", f"ich möchte folgenden Mangel melden: {kind}."]
        if data.text and data.text.strip():
            lines += ["", f"Beschreibung: {data.text.strip()}"]
        if data.lane == "hazard":
            lines += ["", "Der Mangel kann Menschen gefährden, ich bitte um eine zeitnahe Prüfung."]
        else:
            lines += ["", "Ich bitte um Prüfung und Behebung."]
        lines += ["", "Vielen Dank und freundliche Grüße", "eine Bürgerin oder ein Bürger über die App Ortsbild"]
        target = f" an {data.authority}" if data.authority else ""
        return DraftContent(subject=f"Meldung: {kind}"[:200], body="\n".join(lines), summary_de=f"Meldung zu {kind}{target}.")


def provider_from_env() -> DraftProvider:
    """The provider named in DRAFT_PROVIDER (default `template`). An unknown name stops the start of the server."""
    name = os.getenv("DRAFT_PROVIDER", "template")
    if name == "template":
        return TemplateDraftProvider()
    if name == "anthropic":
        from drafting.claude import DEFAULT_MODEL, ClaudeDraftProvider

        return ClaudeDraftProvider(os.environ["ANTHROPIC_KEY"], os.getenv("ANTHROPIC_DRAFT_MODEL", DEFAULT_MODEL))
    raise ValueError(f"unknown DRAFT_PROVIDER: {name}")
