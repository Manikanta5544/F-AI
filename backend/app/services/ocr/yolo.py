"""
YOLOv8 document layout detection — Task #7.

Uses yolov8x-doclaynet (pre-trained on 80k+ annotated document pages).
No training required — call it directly.

Graceful fallback: when model is unavailable (CI, CPU-only, no weights),
returns a single full-page region so the OCR pipeline still works.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from app.core.config import settings

RegionType = Literal["text", "table", "figure", "header", "stamp", "signature"]

# YOLOv8 doclaynet class names → our internal region types
_CLASS_MAP: dict[str, RegionType] = {
    "text":           "text",
    "title":          "header",
    "list":           "text",
    "table":          "table",
    "figure":         "figure",
    "caption":        "text",
    "page-header":    "header",
    "page-footer":    "text",
    "footnote":       "text",
    "formula":        "text",
    "section-header": "header",
}


@dataclass
class DetectedRegion:
    region_id: str
    region_type: RegionType
    # Normalised coordinates (0–1 relative to image size)
    x: float
    y: float
    width: float
    height: float
    confidence: float


class YOLOLayoutDetector:
    """
    Singleton — model loads once on first use, reused for all subsequent requests.
    Thread-safe for inference (YOLO model is read-only after load).
    """
    
    _instance: "YOLOLayoutDetector | None" = None
    _model = None

    @classmethod
    def get_instance(cls) -> "YOLOLayoutDetector":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        import asyncio
        self._load_model()
        self._lock = asyncio.Lock()

    def _load_model(self) -> None:
        model_path = settings.YOLO_MODEL_PATH
        try:
            from ultralytics import YOLO  # type: ignore[import]
            if os.path.exists(model_path):
                self._model = YOLO(model_path)
            else:
                # Download pre-trained doclaynet weights
                os.makedirs(os.path.dirname(model_path), exist_ok=True)
                self._model = YOLO("yolov8x-doclaynet.pt")
                self._model.save(model_path)
        except Exception:
            # Model unavailable: CI mode, no GPU, missing weights
            self._model = None

    @property
    def is_available(self) -> bool:
        return self._model is not None

    async def detect(
        self,
        image: Image.Image,
        confidence_threshold: float | None = None,
    ) -> list[DetectedRegion]:
        """
        Run layout detection. Returns regions sorted top-to-bottom, left-to-right.
        Falls back to single full-page region when model is unavailable.
        """
        threshold = confidence_threshold or settings.YOLO_CONFIDENCE_THRESHOLD

        if not self.is_available:
            return self._full_page_fallback(image)

        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            async with self._lock:
                results = self._model.predict(
                    source=image,
                    conf=threshold,
                    device=device,
                    verbose=False,
                )

            if not results or len(results[0].boxes) == 0:
                return self._full_page_fallback(image)

            detected: list[DetectedRegion] = []
            result = results[0]
            w, h = image.size

            for i, box in enumerate(result.boxes):
                cls_idx = int(box.cls.item())
                cls_name = result.names.get(cls_idx, "text")
                region_type = _CLASS_MAP.get(cls_name, "text")
                conf = float(box.conf.item())
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                detected.append(DetectedRegion(
                    region_id=f"region-{i}",
                    region_type=region_type,
                    x=x1 / w,
                    y=y1 / h,
                    width=(x2 - x1) / w,
                    height=(y2 - y1) / h,
                    confidence=conf,
                ))

            # Reading order: top-to-bottom, left-to-right
            detected.sort(key=lambda r: (round(r.y * 10), r.x))
            return detected

        except Exception:
            return self._full_page_fallback(image)

    def _full_page_fallback(self, image: Image.Image) -> list[DetectedRegion]:
        """Single region covering the full page — always safe."""
        return [
            DetectedRegion(
                region_id="region-0",
                region_type="text",
                x=0.0, y=0.0, width=1.0, height=1.0,
                confidence=1.0,
            )
        ]

    def crop_region(self, image: Image.Image, region: DetectedRegion) -> Image.Image:
        """Crop image to a detected region with 5-pixel padding."""
        w, h = image.size
        pad = 5
        x1 = max(0, int(region.x * w) - pad)
        y1 = max(0, int(region.y * h) - pad)
        x2 = min(w, int((region.x + region.width) * w) + pad)
        y2 = min(h, int((region.y + region.height) * h) + pad)
        return image.crop((x1, y1, x2, y2))