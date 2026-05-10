"""
OCR Pipeline Orchestrator.

Flow (Tasks #4, #6, #7 combined):
  1. Load file → list of PIL images (one per PDF page)
  2. YOLO layout detection (optional, based on mode/flag)
  3. For each region:
     a. Crop from page image
     b. Region-specific preprocessing (erosion/dilation tuning)
     c. OCR ensemble (Paddle + EasyOCR → pick best)
  4. Assemble structured OCRResult with per-region metrics
"""
from __future__ import annotations

import io
import time
import uuid
from typing import Callable, Awaitable, Literal

from PIL import Image

from app.core.config import settings
from app.models.schemas.schemas import (
    BoundingBox, OCRMetrics, OCRRegion, OCRResult, OCRToken,
)
from app.services.ocr.engines import run_ensemble
from app.services.ocr.preprocessing import preprocess_region, cv_to_pil
from app.services.ocr.yolo import YOLOLayoutDetector

OCRMode = Literal["fast", "full", "ci"]

ProgressCallback = Callable[[int], Awaitable[None]] | None


# ── File loading ──────────────────────────────────────────────────────────────
def _load_images(file_bytes: bytes, filename: str) -> list[Image.Image]:
    """Convert uploaded file bytes to a list of PIL images (one per page for PDFs)."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "pdf":
        try:
            import pdfplumber  # type: ignore[import]
            pages = []
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    pages.append(page.to_image(resolution=300).original)
            return pages or [Image.new("RGB", (800, 1100), "white")]
        except Exception:
            pass

    try:
        return [Image.open(io.BytesIO(file_bytes)).convert("RGB")]
    except Exception:
        return [Image.new("RGB", (800, 1100), "white")]


# ── Main pipeline ─────────────────────────────────────────────────────────────
async def run_ocr_pipeline(
    file_bytes: bytes,
    filename: str,
    mode: OCRMode = "full",
    progress_callback: ProgressCallback = None,
    enable_yolo: bool | None = None,
    enable_ensemble: bool | None = None,
) -> OCRResult:
    """
    Main entry point for the OCR pipeline.

    Args:
        file_bytes:        Raw file content (PDF or image).
        filename:          Original filename (used to determine type).
        mode:              'fast' = Paddle only; 'full' = YOLO + ensemble; 'ci' = mock.
        progress_callback: Optional async callable receiving 0–100 progress.
        enable_yolo:       Override settings flag if provided.
        enable_ensemble:   Override settings flag if provided.
    """
    start_ms = int(time.time() * 1000)
    job_id = str(uuid.uuid4())

    # Resolve feature flags: caller override > settings
    use_yolo = (enable_yolo if enable_yolo is not None else settings.ENABLE_YOLO) and mode == "full"
    use_ensemble = (enable_ensemble if enable_ensemble is not None else settings.ENABLE_OCR_ENSEMBLE) and mode == "full"

    async def _progress(pct: int) -> None:
        if progress_callback:
            await progress_callback(pct)

    await _progress(5)

    # Step 1: Load images
    pages = _load_images(file_bytes, filename)
    page_count = len(pages) if pages else 1

    await _progress(15)

    detector = YOLOLayoutDetector.get_instance()
    all_regions: list[OCRRegion] = []
    total_chars = 0
    fallback_triggered = False
    engine_counts: dict[str, int] = {}

    # Step 2 & 3: Per-page YOLO → region OCR
    for page_num, page_image in enumerate(pages):
        page_base = 15 + int((page_num / page_count) * 70)

        detected = await detector.detect(page_image) if use_yolo else detector._full_page_fallback(page_image)
        await _progress(page_base + 10)

        w_px, h_px = page_image.size

        for reg_idx, region in enumerate(detected):
            reg_progress = page_base + 10 + int((reg_idx / max(len(detected), 1)) * 50)
            await _progress(reg_progress)

            cropped = detector.crop_region(page_image, region)
            if cropped.width < 10 or cropped.height < 10:
                continue

            preprocessed = preprocess_region(cropped, region.region_type)
            preprocessed_pil = cv_to_pil(preprocessed) if preprocessed.ndim == 2 else Image.fromarray(preprocessed)

            words, engine_used = run_ensemble(
                preprocessed_pil,
                region_type=region.region_type,
                enable_ensemble=use_ensemble,
            )

            if not words:
                continue

            avg_conf = sum(w.confidence for w in words) / len(words)
            if avg_conf < settings.OCR_CONFIDENCE_THRESHOLD and engine_used != "tesseract":
                fallback_triggered = True

            text = " ".join(w.text for w in words if w.text.strip())
            total_chars += len(text)
            engine_counts[engine_used] = engine_counts.get(engine_used, 0) + 1

            tokens = [
                OCRToken(
                    text=word.text,
                    confidence=word.confidence,
                    bbox=BoundingBox(
                        x=word.x * w_px,
                        y=word.y * h_px,
                        width=word.width * w_px,
                        height=word.height * h_px,
                    ),
                    engine=engine_used,
                )
                for word in words
            ]

            all_regions.append(OCRRegion(
                id=f"page{page_num}-{region.region_id}",
                type=region.region_type,
                bbox=BoundingBox(
                    x=region.x * w_px,
                    y=region.y * h_px,
                    width=region.width * w_px,
                    height=region.height * h_px,
                ),
                confidence=avg_conf,
                tokens=tokens,
                text=text,
            ))

    await _progress(95)

    end_ms = int(time.time() * 1000)
    avg_confidence = (
        sum(r.confidence for r in all_regions) / len(all_regions)
        if all_regions else 0.0
    )
    primary_engine = max(engine_counts, key=lambda k: engine_counts[k]) if engine_counts else "paddle"

    result = OCRResult(
        job_id=job_id,
        filename=filename,
        page_count=page_count,
        mode=mode,
        regions=all_regions,
        engine_used=primary_engine,
        fallback_triggered=fallback_triggered,
        metrics=OCRMetrics(
            processing_ms=end_ms - start_ms,
            characters_extracted=total_chars,
            avg_confidence=round(avg_confidence, 4),
        ),
    )

    await _progress(100)
    return result