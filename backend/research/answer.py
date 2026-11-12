import json

from pydantic import ValidationError

from research.models import Channel, ResearchResult

MAX_WEB_CONFIDENCE = 0.8  # an answer from the web is never "sure", the user checks it


def result_from_text(text: str) -> ResearchResult | None:
    """The answer of a research model (one JSON object in its text) as a result, or None if it is not usable.

    Whether the pages really say what the answer claims is checked afterwards by `research.verify`, not here.
    """
    try:
        answer = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None
    if not isinstance(answer, dict) or not answer.get("authority"):
        return None
    sources = [s for s in answer.get("sources") or [] if isinstance(s, str)]
    if not sources:
        return None  # a claim without a source is dropped
    channel = None
    if answer.get("channel_type") and answer.get("channel_target"):
        try:
            channel = Channel(type=answer["channel_type"], target=answer["channel_target"])
        except ValidationError:
            channel = None  # keep the authority, drop a contact that has no valid form
    try:
        confidence = min(float(answer.get("confidence") or 0), MAX_WEB_CONFIDENCE)
        return ResearchResult(
            authority=str(answer["authority"])[:200], channel=channel,
            language=answer.get("language") if isinstance(answer.get("language"), str) else None,
            sources=sources, confidence=max(confidence, 0.0), origin="web",
        )
    except (ValidationError, TypeError, ValueError):
        return None
