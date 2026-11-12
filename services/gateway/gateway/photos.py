"""Check that an upload really is a photo, by looking into the file.

The same rules as backend/api/reports.py (`detect_image`). The gateway does not change the photo: removing the
metadata and covering faces is the job of the privacy layer of the backend.
"""

import io

import pillow_heif
from PIL import Image, UnidentifiedImageError

pillow_heif.register_heif_opener()  # the iPhone default format

# what the file really is (detected from its content) -> (mime type, file extension)
IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "HEIF": ("image/heic", "heic"),
}


class NotAnImage(ValueError):
    """The file is no readable image (422)."""


class UnsupportedImage(ValueError):
    """The file is an image, but not JPEG, PNG or HEIC (415)."""


def detect_image(data: bytes) -> tuple[str, str]:
    """Return (mime type, extension) of an image. The type the client claims is only a claim and is not used."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as error:
        raise NotAnImage("the file is not a readable image") from error
    if image_format not in IMAGE_FORMATS:
        raise UnsupportedImage("only JPEG, PNG and HEIC images are accepted")
    return IMAGE_FORMATS[image_format]
