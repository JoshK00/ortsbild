"""Photo handling: validate, read GPS, downscale and strip all metadata."""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.ExifTags import IFD

ALLOWED_FORMATS = {"JPEG", "PNG"}
MAX_PIXELS = 50_000_000  # guards against decompression bombs

# EXIF GPS tag numbers
_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON = 1, 2, 3, 4


class InvalidImageError(ValueError):
    pass


@dataclass
class ProcessedImage:
    data: bytes  # JPEG without any metadata
    width: int
    height: int
    gps: tuple[float, float] | None  # (lat, lon) from EXIF, read before stripping


def process_image(data: bytes, *, max_bytes: int, max_edge_px: int) -> ProcessedImage:
    if len(data) > max_bytes:
        raise InvalidImageError(f"photo exceeds {max_bytes} bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED_FORMATS:
                raise InvalidImageError(f"unsupported image format: {img.format}")
            if img.width * img.height > MAX_PIXELS:
                raise InvalidImageError("image has too many pixels")
            gps = _read_gps(img)
            img = ImageOps.exif_transpose(img)  # bake orientation in before EXIF is dropped
            img.thumbnail((max_edge_px, max_edge_px))
            if img.mode != "RGB":
                img = img.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError, OSError) as exc:
        raise InvalidImageError(f"not a readable image: {exc}") from exc

    out = io.BytesIO()
    # Re-encoding without passing exif/icc drops all metadata (device, time, GPS).
    img.save(out, format="JPEG", quality=85, optimize=True)
    return ProcessedImage(data=out.getvalue(), width=img.width, height=img.height, gps=gps)


def _read_gps(img: Image.Image) -> tuple[float, float] | None:
    try:
        gps = img.getexif().get_ifd(IFD.GPSInfo)
    except Exception:  # broken EXIF must never break ingest
        return None
    if not gps or _GPS_LAT not in gps or _GPS_LON not in gps:
        return None
    try:
        lat = _dms_to_degrees(gps[_GPS_LAT], gps.get(_GPS_LAT_REF, "N"))
        lon = _dms_to_degrees(gps[_GPS_LON], gps.get(_GPS_LON_REF, "E"))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return round(lat, 7), round(lon, 7)


def _dms_to_degrees(dms, ref) -> float:
    degrees, minutes, seconds = (float(v) for v in dms)
    value = degrees + minutes / 60 + seconds / 3600
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    return -value if str(ref).strip().upper() in {"S", "W"} else value
