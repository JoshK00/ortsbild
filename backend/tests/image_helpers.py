import io

from PIL import Image


def make_jpeg(with_exif: bool = False, size=(40, 20)) -> bytes:
    """Create a small red JPEG, optionally with EXIF data (camera model and GPS tag)."""
    image = Image.new("RGB", size, (200, 30, 30))
    output = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[271] = "TestCam"  # Make
        exif[34853] = {1: "N", 2: (48.0, 8.0, 15.0)}  # GPSInfo
        image.save(output, format="JPEG", exif=exif)
    else:
        image.save(output, format="JPEG")
    return output.getvalue()


def make_png(size=(10, 10)) -> bytes:
    """Create a small blue PNG."""
    output = io.BytesIO()
    Image.new("RGB", size, (30, 30, 200)).save(output, format="PNG")
    return output.getvalue()


def make_heic(with_exif: bool = False, size=(40, 20)) -> bytes:
    """Create a small HEIC image (the iPhone default), optionally with EXIF data."""
    import pillow_heif

    pillow_heif.register_heif_opener()
    image = Image.new("RGB", size, (30, 200, 30))
    output = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[271] = "TestPhone"  # Make
        image.save(output, format="HEIF", exif=exif)
    else:
        image.save(output, format="HEIF")
    return output.getvalue()
