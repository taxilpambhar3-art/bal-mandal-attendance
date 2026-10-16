"""
Face Matching & Verification Engine for Bal Mandal Attendance.
Provides multi-metric image similarity analysis between live scanned face and enrolled photo.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageFile
import numpy as np

# Allow truncated frames from canvas data URLs
ImageFile.LOAD_TRUNCATED_IMAGES = True


def _load_image(img_input: str | Path | Image.Image) -> Optional[Image.Image]:
    """Safely loads an image as RGB PIL Image."""
    try:
        if isinstance(img_input, Image.Image):
            return img_input.convert("RGB")
        if isinstance(img_input, (str, Path)):
            p = Path(img_input)
            if p.exists() and p.is_file():
                with Image.open(p) as img:
                    return img.convert("RGB")
        return None
    except Exception as e:
        print(f"Error loading image: {e}")
        return None


def _get_face_crop(img: Image.Image) -> Image.Image:
    """Center crop 65% of the frame where child's face is positioned in circular ring."""
    w, h = img.size
    cw, ch = int(w * 0.65), int(h * 0.65)
    cx = w // 2
    cy = int(h * 0.45)  # Slightly above middle
    left = max(0, cx - cw // 2)
    top = max(0, cy - ch // 2)
    right = min(w, left + cw)
    bottom = min(h, top + ch)
    return img.crop((left, top, right, bottom)).resize((128, 128), Image.Resampling.LANCZOS)


def _compute_dhash(crop: Image.Image) -> np.ndarray:
    """Computes 8x8 difference hash (64 bits)."""
    tiny = crop.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    arr = np.array(tiny)
    return arr[:, 1:] > arr[:, :-1]


def _compute_hsv_hist(crop: Image.Image) -> np.ndarray:
    """Computes color histogram for skin/lighting distribution."""
    hsv = np.array(crop.convert("HSV"), dtype=np.float32)
    h_arr, _ = np.histogram(hsv[:, :, 0], bins=16, range=(0, 256), density=True)
    s_arr, _ = np.histogram(hsv[:, :, 1], bins=16, range=(0, 256), density=True)
    vec = np.concatenate([h_arr, s_arr])
    return vec / (np.sum(vec) + 1e-6)


def _compute_normalized_vector(crop: Image.Image) -> np.ndarray:
    """Extracts normalized spatial luminance vector."""
    gray = np.array(crop.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    norm = (gray - gray.mean()) / (gray.std() + 1e-6)
    return norm.flatten()


def _has_valid_face_content(img: Image.Image) -> bool:
    """Checks if the image has adequate dimensions and variance (rejects blank/solid color inputs)."""
    w, h = img.size
    if w < 20 or h < 20:
        return False
    gray = np.array(img.convert("L"), dtype=np.float32)
    return float(np.std(gray)) >= 8.0


def compare_face_photos(
    live_img_path: str | Path,
    enrolled_img_path: Optional[str | Path],
    threshold: float = 60.0,
    client_verified: Optional[bool] = None,
    client_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Compares live attendance photo with the registered enrolled photo.
    Returns dictionary with match boolean, confidence score (0-100), and verdict details.
    """
    if not enrolled_img_path:
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": "no_enrolled_photo",
            "message": "આ બાળકનો કોઈ રજિસ્ટર્ડ ફોટો મળ્યો નથી (No Enrolled Photo Found). પહેલા પ્રોફાઇલમાં ફેસ ઉમેરો.",
        }

    im_live = _load_image(live_img_path)
    im_enrolled = _load_image(enrolled_img_path)

    if not im_live or not im_enrolled:
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": "invalid_image",
            "message": "ફોટો વાંચવામાં ભૂલ આવી (Invalid Image File).",
        }

    # Validate that images have actual visual content (not solid black/white/blank)
    if not _has_valid_face_content(im_live):
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": "no_face_detected",
            "message": "કેમેરામાં ચહેરો સ્પષ્ટ દેખાતો નથી (No Clear Face in Camera). કેમેરા સામે ચહેરો લાવો.",
        }

    if not _has_valid_face_content(im_enrolled):
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": "invalid_enrolled_face",
            "message": "આ બાળકના રજિસ્ટર્ડ ફોટામાં ચહેરો માન્ય નથી. નવો ફોટો અપલોડ કરો.",
        }

    # If client-side deep neural face-api already evaluated the descriptor:
    if client_verified is not None and client_score is not None:
        is_match = bool(client_verified)
        return {
            "is_match": is_match,
            "confidence": round(float(client_score), 1),
            "reason": "matched" if is_match else "mismatch",
            "message": "ચહેરો સફળતાપૂર્વક મેળ ખાય છે!" if is_match else "સ્કેન કરેલો ચહેરો રજિસ્ટર્ડ ફોટા સાથે મેળ ખાતો નથી (Face Mismatch)!",
            "engine": "face-api-deepnet",
        }

    # Backend multi-feature analysis fallback
    crop_live = _get_face_crop(im_live)
    crop_enrolled = _get_face_crop(im_enrolled)

    # 1. Luminance Cosine
    v1 = _compute_normalized_vector(crop_live)
    v2 = _compute_normalized_vector(crop_enrolled)
    cos = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6))
    cos_norm = max(0.0, min(1.0, (cos + 1.0) / 2.0))

    # 2. Difference Hash (dHash)
    dh1 = _compute_dhash(crop_live)
    dh2 = _compute_dhash(crop_enrolled)
    dhash_sim = 1.0 - (np.count_nonzero(dh1 != dh2) / 64.0)

    # 3. HSV Color & Skin Distribution
    col1 = _compute_hsv_hist(crop_live)
    col2 = _compute_hsv_hist(crop_enrolled)
    col_sim = float(np.sum(np.minimum(col1, col2)))

    # Composite backend confidence
    confidence = round((0.35 * cos_norm + 0.35 * dhash_sim + 0.30 * col_sim) * 100, 1)

    is_match = confidence >= threshold

    return {
        "is_match": is_match,
        "confidence": confidence,
        "reason": "matched" if is_match else "mismatch",
        "message": "ચહેરો સફળતાપૂર્વક મેળ ખાય છે!" if is_match else "સ્કેન કરેલો ચહેરો રજિસ્ટર્ડ ફોટા સાથે મેળ ખાતો નથી (Face Mismatch)!",
        "engine": "backend-cv",
    }
