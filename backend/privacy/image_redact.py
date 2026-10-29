from PIL import Image, ImageDraw

from privacy.image_detectors import Box


def blackout(image: Image.Image, boxes: list[Box], padding: float = 0.3) -> Image.Image:
    """Cover every box with a black bar and return the new image.

    Black bars instead of blurring: a blur can sometimes be partly undone, a bar cannot.
    The box is made a bit bigger (padding, share of its size), the detector may cut the edges.
    """
    result = image.copy()
    draw = ImageDraw.Draw(result)
    for box in boxes:
        pad_x = int((box.right - box.left) * padding)
        pad_y = int((box.bottom - box.top) * padding)
        draw.rectangle(
            [
                max(0, box.left - pad_x),
                max(0, box.top - pad_y),
                min(image.width, box.right + pad_x) - 1,
                min(image.height, box.bottom + pad_y) - 1,
            ],
            fill=(0, 0, 0),
        )
    return result
