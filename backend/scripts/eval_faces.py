"""Run the face detector over a folder of photos and draw what it found, so a person can look at the result.

Usage (from the backend folder):  PYTHONPATH=. python scripts/eval_faces.py eval/faces [score_threshold, default FACE_SCORE_THRESHOLD or 0.7]
Writes `<name>_boxes.jpg` next to each photo (red boxes with the confidence) and prints how many faces were found.

There are no hand-drawn boxes yet, so this does not compute a recall: it makes the misses and the false boxes visible.
TODO: Draw the true boxes by hand for the photos in eval/faces and print recall and false boxes per photo.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from privacy.image_detectors import YuNetFaceDetector, face_score_threshold_from_env, merge_overlapping

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/faces")
threshold = float(sys.argv[2]) if len(sys.argv) > 2 else face_score_threshold_from_env()
detector = YuNetFaceDetector(score_threshold=threshold)

for path in sorted(folder.glob("*.jpg")):
    if path.stem.endswith("_boxes"):
        continue
    image = Image.open(path).convert("RGB")
    boxes = merge_overlapping(detector.detect(image))
    draw = ImageDraw.Draw(image)
    for box in boxes:
        draw.rectangle([box.left, box.top, box.right, box.bottom], outline=(255, 0, 0), width=max(2, image.width // 400))
        draw.text((box.left, max(0, box.top - 12)), f"{box.confidence:.2f}", fill=(255, 255, 0))
    image.save(path.with_name(path.stem + "_boxes.jpg"), quality=85)
    sure = sum(1 for box in boxes if (box.confidence or 0) >= 0.6)
    print(f"{path.name}: {len(boxes)} boxes, {sure} of them with a score of 0.6 or more")
