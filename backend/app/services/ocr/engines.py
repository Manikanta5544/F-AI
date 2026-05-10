"""
OCR engine adapters — Task #4.

Engines supported:
  - PaddleOCR    (best all-around; great for Indian text)
  - EasyOCR      (strong multilingual)
  - Tesseract    (fallback; well-known, slower)
  - Docling      (structured PDF extraction; preserves table cells)
  - TrOCR        (Microsoft transformer-based; high accuracy on printed text)

All engines expose a unified BaseOCREngine.extract() interface.
Singletons: PaddleOCR and EasyOCR are heavy — load once and reuse.
Ensemble: run primary + secondary, pick winner by average confidence.
"""
from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from PIL import Image


@dataclass
class OCRWord:
    text: str
    confidence: float      # 0–1
    x: float               # normalised 0–1
    y: float
    width: float
    height: float


class BaseOCREngine(abc.ABC):
    name: ClassVar[str]

    @abc.abstractmethod
    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        """Run OCR. Returns word-level results with normalised coordinates."""

    def full_text(self, words: list[OCRWord]) -> str:
        return " ".join(w.text for w in words if w.text.strip())

    def avg_confidence(self, words: list[OCRWord]) -> float:
        if not words:
            return 0.0
        return sum(w.confidence for w in words) / len(words)


# ── PaddleOCR ─────────────────────────────────────────────────────────────────
class PaddleOCREngine(BaseOCREngine):
    name = "paddle"
    _instance: "PaddleOCREngine | None" = None
    _ocr = None

    @classmethod
    def get_instance(cls) -> "PaddleOCREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
            import torch
            self._ocr = PaddleOCR(
                use_angle_cls=True, lang="en",
                use_gpu=torch.cuda.is_available(), show_log=False,
            )
        except Exception:
            self._ocr = None

    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        if self._ocr is None:
            return []
        try:
            if isinstance(image, Image.Image):
                image = np.array(image.convert("RGB"))
            result = self._ocr.ocr(image, cls=True)
            if not result or not result[0]:
                return []
            words = []
            h, w = image.shape[:2]
            for line in result[0]:
                box, (text, conf) = line
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                words.append(OCRWord(
                    text=text, confidence=float(conf),
                    x=min(xs) / w, y=min(ys) / h,
                    width=(max(xs) - min(xs)) / w,
                    height=(max(ys) - min(ys)) / h,
                ))
            return words
        except Exception:
            return []


# ── EasyOCR ───────────────────────────────────────────────────────────────────
class EasyOCREngine(BaseOCREngine):
    name = "easyocr"
    _instance: "EasyOCREngine | None" = None
    _reader = None

    @classmethod
    def get_instance(cls) -> "EasyOCREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        try:
            import easyocr  # type: ignore[import]
            import torch
            self._reader = easyocr.Reader(["en"], gpu=torch.cuda.is_available())
        except Exception:
            self._reader = None

    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        if self._reader is None:
            return []
        try:
            if isinstance(image, Image.Image):
                image = np.array(image.convert("RGB"))
            results = self._reader.readtext(image)
            words = []
            h, w = image.shape[:2]
            for box, text, conf in results:
                xs = [p[0] for p in box]; ys = [p[1] for p in box]
                words.append(OCRWord(
                    text=text, confidence=float(conf),
                    x=min(xs) / w, y=min(ys) / h,
                    width=(max(xs) - min(xs)) / w,
                    height=(max(ys) - min(ys)) / h,
                ))
            return words
        except Exception:
            return []


# ── Tesseract ─────────────────────────────────────────────────────────────────
class TesseractEngine(BaseOCREngine):
    name = "tesseract"

    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        try:
            import pytesseract  # type: ignore[import]
            if isinstance(image, np.ndarray):
                image = Image.fromarray(image)
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            words = []
            w, h = image.size
            for i in range(len(data["text"])):
                text = str(data["text"][i]).strip()
                conf = int(data["conf"][i])
                if not text or conf < 0:
                    continue
                words.append(OCRWord(
                    text=text, confidence=conf / 100.0,
                    x=data["left"][i] / w, y=data["top"][i] / h,
                    width=data["width"][i] / w, height=data["height"][i] / h,
                ))
            return words
        except Exception:
            return []


# ── TrOCR (Microsoft Transformer OCR) ────────────────────────────────────────
class TrOCREngine(BaseOCREngine):
    """
    Microsoft TrOCR — transformer encoder-decoder fine-tuned for printed text.
    High accuracy, slower than Paddle. Use for challenging documents.
    """
    name = "tr"
    _instance: "TrOCREngine | None" = None
    _processor = None
    _model = None

    @classmethod
    def get_instance(cls) -> "TrOCREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel  # type: ignore[import]
            self._processor = TrOCRProcessor.from_pretrained("microsoft/trocr-base-printed")
            self._model = VisionEncoderDecoderModel.from_pretrained("microsoft/trocr-base-printed")
        except Exception:
            self._processor = None
            self._model = None

    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        if self._model is None or self._processor is None:
            return []
        try:
            import torch
            if isinstance(image, np.ndarray):
                pil = Image.fromarray(image).convert("RGB")
            else:
                pil = image.convert("RGB")

            pixel_values = self._processor(images=pil, return_tensors="pt").pixel_values
            with torch.no_grad():
                generated_ids = self._model.generate(pixel_values)
            text = self._processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

            if not text.strip():
                return []

            # TrOCR returns full-region text; wrap as single word with full bbox
            words = []
            for word in text.split():
                words.append(OCRWord(
                    text=word, confidence=0.90,
                    x=0.0, y=0.0, width=1.0, height=1.0,
                ))
            return words
        except Exception:
            return []


# ── Docling ───────────────────────────────────────────────────────────────────
class DoclingEngine(BaseOCREngine):
    """
    Docling — best for structured PDFs (preserves table cells natively).
    Works on PDF bytes; this adapter converts image to a temp PNG.
    """
    name = "docling"

    def extract(self, image: np.ndarray | Image.Image) -> list[OCRWord]:
        tmp_path: str | None = None
        try:
            from docling.document_converter import DocumentConverter  # type: ignore[import]
            import tempfile

            pil = Image.fromarray(image) if isinstance(image, np.ndarray) else image
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                pil.save(tmp.name)
                tmp_path = tmp.name

            converter = DocumentConverter()
            result = converter.convert(tmp_path)

            text = result.document.export_to_text()
            if not text:
                return []

            # Docling doesn't expose per-word bbox in image mode
            return [
                OCRWord(text=w, confidence=0.92, x=0.0, y=0.0, width=1.0, height=1.0)
                for w in text.split()
            ]
        except Exception:
            return []
        finally:
            # FIX: always clean up the temp file, even if an exception occurred
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


# ── Ensemble ──────────────────────────────────────────────────────────────────
def run_ensemble(
    image: np.ndarray | Image.Image,
    region_type: str = "text",
    enable_ensemble: bool = True,
) -> tuple[list[OCRWord], str]:
    """
    Run OCR engine(s) and return (words, engine_name).

    Strategy:
      - Full ensemble: PaddleOCR + EasyOCR → pick winner by avg confidence.
      - Tables: PaddleOCR only (best table handling, column alignment).
      - Fallback: if winner confidence < 0.75 → try Tesseract.
    """
    paddle = PaddleOCREngine.get_instance()
    easy = EasyOCREngine.get_instance()
    tesseract = TesseractEngine()

    if not enable_ensemble or region_type == "table":
        words = paddle.extract(image)
        engine = "paddle"
    else:
        paddle_words = paddle.extract(image)
        easy_words = easy.extract(image)
        paddle_conf = paddle.avg_confidence(paddle_words)
        easy_conf = easy.avg_confidence(easy_words)

        if paddle_conf >= easy_conf:
            words, engine = paddle_words, "paddle"
        else:
            words, engine = easy_words, "easyocr"

    # Low-confidence fallback to Tesseract
    avg = sum(w.confidence for w in words) / max(len(words), 1)
    if avg < 0.75 and region_type != "table":
        tess_words = tesseract.extract(image)
        if tesseract.avg_confidence(tess_words) > avg:
            words, engine = tess_words, "tesseract"

    return words, engine