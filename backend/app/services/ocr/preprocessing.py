"""
Image preprocessing pipeline for document OCR — Task #6.

Full pipeline order:
  DPI normalise → grayscale → CLAHE → bilateral filter
  → deskew → adaptive threshold → erosion → dilation → noise removal

All functions are pure (no side effects) and independently testable.
"""
from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image


# ── Conversion helpers ────────────────────────────────────────────────────────
def pil_to_cv(image: Image.Image) -> np.ndarray:
    """PIL RGB/RGBA → OpenCV BGR uint8."""
    if image.mode == "RGBA":
        image = image.convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def cv_to_pil(img: np.ndarray) -> Image.Image:
    """OpenCV BGR → PIL RGB."""
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


# ── Core pipeline stages ──────────────────────────────────────────────────────
def to_grayscale(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 2:
        return img  # already grayscale
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def apply_clahe(gray: np.ndarray, clip_limit: float = 2.0, tile_size: int = 8) -> np.ndarray:
    """
    Contrast Limited Adaptive Histogram Equalization.
    Improves faded scans and uneven illumination without over-amplifying noise.
    """
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
    return clahe.apply(gray)


def bilateral_filter(gray: np.ndarray) -> np.ndarray:
    """
    Noise reduction while preserving sharp text edges.
    d=9 covers a 9-pixel neighbourhood; sigma 75 = moderate smoothing.
    """
    return cv2.bilateralFilter(gray, d=9, sigmaColor=75, sigmaSpace=75)


def deskew(gray: np.ndarray) -> np.ndarray:
    """
    Detect and correct document skew via Hough line transform.
    Corrects rotation up to ±45 degrees.
    Sub-half-degree skew is ignored (more harm than good to correct).
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, math.pi / 180, threshold=200)

    if lines is None or len(lines) == 0:
        return gray

    angles = []
    for rho, theta in lines[:, 0]:
        angle = (theta * 180 / math.pi) - 90
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return gray

    median_angle = float(np.median(angles))
    if abs(median_angle) < 0.5:
        return gray  # sub-half-degree: skip

    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), median_angle, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def adaptive_threshold(gray: np.ndarray) -> np.ndarray:
    """
    Binarize using adaptive Gaussian threshold.
    Handles uneven illumination (e.g. phone photos of documents).
    blockSize=11, C=2 works well for A4 printed text at 200–300 DPI.
    """
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=2,
    )


def erode(binary: np.ndarray, kernel_size: int = 2) -> np.ndarray:
    """
    Morphological erosion — removes isolated white pixels (salt noise).
    Use kernel_size=1 or 2 on printed text to avoid destroying strokes.
    """
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.erode(binary, kernel, iterations=1)


def dilate(binary: np.ndarray, kernel_size: int = 2) -> np.ndarray:
    """
    Morphological dilation — reconnects broken character strokes.
    Useful for low-DPI scans where ink has micro-gaps.
    """
    kernel = np.ones((kernel_size, kernel_size), np.uint8)
    return cv2.dilate(binary, kernel, iterations=1)


def remove_noise(binary: np.ndarray) -> np.ndarray:
    """Open + close morphology to clean salt-and-pepper noise."""
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel)


def normalize_dpi(image: Image.Image, target_dpi: int = 300) -> Image.Image:
    """
    Upscale images below target DPI.
    OCR accuracy degrades significantly below 200 DPI.
    """
    try:
        dpi_info = image.info.get("dpi", (72, 72))
        current_dpi = dpi_info[0] if isinstance(dpi_info, tuple) else int(dpi_info)
    except (TypeError, KeyError, IndexError):
        current_dpi = 72

    if 0 < current_dpi < target_dpi:
        scale = target_dpi / current_dpi
        new_size = (int(image.width * scale), int(image.height * scale))
        return image.resize(new_size, Image.LANCZOS)
    return image


# ── Full pipeline ─────────────────────────────────────────────────────────────
def preprocess_for_ocr(
    image: Image.Image,
    target_dpi: int = 300,
    apply_erosion: bool = True,
    apply_dilation: bool = True,
    erosion_kernel: int = 1,
    dilation_kernel: int = 1,
) -> np.ndarray:
    """
    Full preprocessing pipeline. Returns binarized numpy array ready for OCR.
    Parameters can be tuned per region type via preprocess_region().
    """
    image = normalize_dpi(image, target_dpi)
    img = pil_to_cv(image)
    gray = to_grayscale(img)
    enhanced = apply_clahe(gray)
    smoothed = bilateral_filter(enhanced)
    corrected = deskew(smoothed)
    binary = adaptive_threshold(corrected)

    if apply_erosion:
        binary = erode(binary, erosion_kernel)
    if apply_dilation:
        binary = dilate(binary, dilation_kernel)

    return remove_noise(binary)


def preprocess_region(image: Image.Image, region_type: str) -> np.ndarray:
    """
    Region-specific tuning — tables and stamps need different parameters.
    """
    if region_type == "table":
        # Tables: skip dilation (would merge cell borders), minimal erosion
        return preprocess_for_ocr(image, apply_erosion=True, apply_dilation=False, erosion_kernel=1)
    elif region_type in ("stamp", "signature"):
        # Stamps: heavier dilation to reconnect ink strokes
        return preprocess_for_ocr(image, apply_erosion=False, apply_dilation=True, dilation_kernel=2)
    else:
        # Body text: balanced defaults
        return preprocess_for_ocr(image)