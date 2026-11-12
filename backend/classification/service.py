import io
import logging

from PIL import Image

from classification.emergency import mentions_emergency
from classification.models import Classification, ClassificationInput
from classification.provider import ClassificationProvider
from models.sanitized_report import SanitizedReport
from privacy.photo_store import PhotoStore
from privacy.retry import retry

logger = logging.getLogger("ortsbild.classification")

MODEL_PHOTO_MAX_SIDE = 1024  # enough to see a pothole, and cheaper and faster than the full photo
MODEL_PHOTO_QUALITY = 85


def shrink_photo(data: bytes, max_side: int = MODEL_PHOTO_MAX_SIDE) -> bytes:
    """The photo as a small JPEG for the model."""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))  # keeps the proportions, never enlarges
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=MODEL_PHOTO_QUALITY)
    return out.getvalue()


class Classifier:
    """Classifies a sanitized report with the chosen provider.

    It never raises for a failing provider: classification is not a privacy step, a report without a
    classification is still a valid report and is classified later. Only the emergency check has a fallback.
    """

    def __init__(self, provider: ClassificationProvider, photo_store: PhotoStore) -> None:
        self.provider = provider
        self.photo_store = photo_store

    def classify(self, report: SanitizedReport) -> Classification | None:
        keyword_emergency = mentions_emergency(report.text)
        try:
            data = self._input(report)
            result = retry(lambda: self.provider.classify(data), "classification")
        except Exception as error:
            # Only the type, a message could hold report data
            logger.error("classification failed: report_id=%s error=%s", report.id, type(error).__name__)
            if keyword_emergency:
                # The second line of the emergency check still works: no category, but the alarm is kept
                return Classification(category="other", lane="hazard", emergency=True, confidence=0.0)
            return None
        # The emergency flag is the model OR the keyword search, text cannot switch it off
        return result.model_copy(update={"emergency": result.emergency or keyword_emergency})

    def _input(self, report: SanitizedReport) -> ClassificationInput:
        photo = None
        if report.photos:
            photo = shrink_photo(self.photo_store.load(report.photos[0].ref))
        return ClassificationInput(text=report.text, photo=photo)
