import io

from PIL import Image, ImageOps

from models.incoming_report import Photo
from models.sanitized_report import RedactionEntry
from privacy.photo_store import PhotoStore

# mime type -> (Pillow format, file extension)
SUPPORTED_FORMATS = {
    "image/jpeg": ("JPEG", "jpg"),
    "image/png": ("PNG", "png"),
}
# TODO: Support image/heic (iPhone default). Pillow needs a plugin for it. Until then a
#       HEIC photo fails closed and blocks the report.


def strip_exif(data: bytes, mime_type: str) -> tuple[bytes, bool]:
    """Re-encode an image without its metadata.

    Returns the new image bytes and whether the original carried EXIF data (GPS, device, time).
    Pillow writes no EXIF on save unless asked to, so re-saving drops it.
    """
    if mime_type not in SUPPORTED_FORMATS:
        raise ValueError(f"unsupported image type: {mime_type}")
    image_format, _ = SUPPORTED_FORMATS[mime_type]
    with Image.open(io.BytesIO(data)) as image:
        had_exif = len(image.getexif()) > 0
        # Apply the rotation from the metadata first, otherwise the photo turns sideways
        upright = ImageOps.exif_transpose(image)
        output = io.BytesIO()
        save_options = {"quality": 95} if image_format == "JPEG" else {}
        upright.save(output, format=image_format, **save_options)
    return output.getvalue(), had_exif


def strip_photo_metadata(
    photos: list[Photo], report_id: str, store: PhotoStore
) -> tuple[list[Photo], list[RedactionEntry]]:
    """Copy every photo to the clean bucket without metadata.

    Returns the new photo references and one log entry if any photo had EXIF data.
    """
    clean_photos = []
    photos_with_exif = 0
    for photo in photos:
        data, had_exif = strip_exif(store.load(photo.ref), photo.mime_type)
        _, extension = SUPPORTED_FORMATS[photo.mime_type]
        clean_ref = f"clean/{report_id}/{photo.id}.{extension}"
        store.save(clean_ref, data, photo.mime_type)
        clean_photos.append(Photo(id=photo.id, mime_type=photo.mime_type, ref=clean_ref))
        photos_with_exif += had_exif
    log = []
    if photos_with_exif:
        log.append(RedactionEntry(step="strip_metadata", kind="exif", count=photos_with_exif))
    return clean_photos, log
