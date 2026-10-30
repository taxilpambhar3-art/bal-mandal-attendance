"""
Face Matching & Verification Engine for Bal Mandal Attendance.
Provides multi-metric image similarity analysis between live scanned face and enrolled photo.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, Optional, List
from PIL import Image, ImageFile
import numpy as np

# Allow truncated frames from canvas data URLs
ImageFile.LOAD_TRUNCATED_IMAGES = True


def _load_image(img_input: str | Path | Image.Image) -> Optional[Image.Image]:
    """Safely loads an image as RGB PIL Image with DB restoration fallback."""
    try:
        if isinstance(img_input, Image.Image):
            return img_input.convert("RGB")
        if isinstance(img_input, str) and img_input.startswith("data:image/"):
            import base64, io
            _header, b64_data = img_input.split(",", 1)
            raw = base64.b64decode(b64_data.strip())
            with Image.open(io.BytesIO(raw)) as img:
                return img.convert("RGB")
        if isinstance(img_input, (str, Path)):
            p = Path(img_input)
            if not p.exists() or (p.is_file() and p.stat().st_size < 50):
                # Attempt to restore missing or corrupted file from StoredPhoto in database
                try:
                    from .database import SessionLocal
                    from .models import StoredPhoto
                    import base64
                    with SessionLocal() as db_session:
                        sp = db_session.query(StoredPhoto).filter(StoredPhoto.filename == p.name).first()
                        if sp and sp.data_b64:
                            p.parent.mkdir(parents=True, exist_ok=True)
                            p.write_bytes(base64.b64decode(sp.data_b64))
                except Exception as e:
                    print(f"Error restoring photo in matcher: {e}")

            if p.exists() and p.is_file() and p.stat().st_size >= 50:
                with Image.open(p) as img:
                    return img.convert("RGB")
        return None
    except Exception as e:
        print(f"Error loading image: {e}")
        return None


def _get_face_crops(img: Image.Image) -> List[Image.Image]:
    """
    Extracts multiple candidate crops at various scales and vertical alignments.
    Accommodates differences between tightly cropped passport photos and wider webcam views.
    """
    w, h = img.size
    crops = []
    # Scales: tight face (48%), standard face (60%), wide face (75%)
    # Vertical centers: 42% (eye/nose level) and 48% (geometric center)
    for scale in [0.48, 0.60, 0.75]:
        cw, ch = int(w * scale), int(h * scale)
        for cy_factor in [0.42, 0.48]:
            cx = w // 2
            cy = int(h * cy_factor)
            left = max(0, cx - cw // 2)
            top = max(0, cy - ch // 2)
            right = min(w, left + cw)
            bottom = min(h, top + ch)
            crops.append(img.crop((left, top, right, bottom)).resize((64, 64), Image.Resampling.LANCZOS))
    return crops


def _compute_hsv_hist(img: Image.Image) -> np.ndarray:
    """Computes color histogram for skin/lighting distribution."""
    hsv = np.array(img.convert("HSV"), dtype=np.float32)
    h_arr, _ = np.histogram(hsv[:, :, 0], bins=16, range=(0, 256), density=True)
    s_arr, _ = np.histogram(hsv[:, :, 1], bins=16, range=(0, 256), density=True)
    vec = np.concatenate([h_arr, s_arr])
    return vec / (np.sum(vec) + 1e-6)


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
    threshold: float = 58.0,
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
            "match": False,
            "confidence": 0.0,
            "reason": "no_enrolled_photo",
            "message": "No registered face photo found for this child. Please upload a photo in child profile.",
        }

    # If client-side deep neural face-api already evaluated the 128D descriptor:
    if client_verified is not None:
        c_score = float(client_score) if client_score is not None else 85.0
        is_match = bool(client_verified) and c_score >= 58.0
        return {
            "is_match": is_match,
            "match": is_match,
            "confidence": round(c_score, 1),
            "reason": "matched" if is_match else "mismatch",
            "message": "Face matched successfully!" if is_match else "Face does not match registered photo (Face Mismatch)!",
            "engine": "face-api-deepnet",
        }

    im_live = _load_image(live_img_path)
    im_enrolled = _load_image(enrolled_img_path)

    if not im_live or not im_enrolled:
        return {
            "is_match": False,
            "match": False,
            "confidence": 0.0,
            "reason": "invalid_image",
            "message": "Error reading image file (Invalid Image File).",
        }

    # Validate that images have actual visual content (not solid black/white/blank)
    if not _has_valid_face_content(im_live):
        return {
            "is_match": False,
            "match": False,
            "confidence": 0.0,
            "reason": "no_face_detected",
            "message": "Face not clearly detected in camera. Please face the camera directly.",
        }

    if not _has_valid_face_content(im_enrolled):
        return {
            "is_match": False,
            "match": False,
            "confidence": 0.0,
            "reason": "invalid_enrolled_face",
            "message": "Enrolled photo does not contain a clear face. Please re-upload photo.",
        }

    # Multi-crop cross-scale facial analysis
    crops_live = _get_face_crops(im_live)
    crops_enrolled = _get_face_crops(im_enrolled)

    best_zncc = -1.0
    best_grad_zncc = -1.0

    for c_live in crops_live:
        g1 = np.array(c_live.convert("L"), dtype=np.float32)
        std1 = g1.std()
        if std1 < 1.0:
            continue
        z1 = (g1 - g1.mean()) / std1
        gx1 = g1[:, 2:] - g1[:, :-2]
        gy1 = g1[2:, :] - g1[:-2, :]
        zgx1 = (gx1 - gx1.mean()) / (gx1.std() + 1e-6)
        zgy1 = (gy1 - gy1.mean()) / (gy1.std() + 1e-6)

        for c_enrolled in crops_enrolled:
            g2 = np.array(c_enrolled.convert("L"), dtype=np.float32)
            std2 = g2.std()
            if std2 < 1.0:
                continue
            z2 = (g2 - g2.mean()) / std2

            # 1. Zero-Mean Normalized Cross-Correlation (Luminance structure)
            zncc = float(np.mean(z1 * z2))

            # 2. Edge Gradient Correlation (Eyebrows, eyes, nose, lips contour alignment)
            gx2 = g2[:, 2:] - g2[:, :-2]
            gy2 = g2[2:, :] - g2[:-2, :]
            zgx2 = (gx2 - gx2.mean()) / (gx2.std() + 1e-6)
            zgy2 = (gy2 - gy2.mean()) / (gy2.std() + 1e-6)
            grad_zncc = float(0.5 * (np.mean(zgx1 * zgx2) + np.mean(zgy1 * zgy2)))

            if zncc > best_zncc:
                best_zncc = zncc
            if grad_zncc > best_grad_zncc:
                best_grad_zncc = grad_zncc

    # 3. Color / skin-tone histogram intersection
    h1 = _compute_hsv_hist(crops_live[0])
    h2 = _compute_hsv_hist(crops_enrolled[0])
    sim_hist = float(np.sum(np.minimum(h1, h2)))

    # Composite metric terms
    z_term = max(0.0, best_zncc)
    g_term = max(0.0, best_grad_zncc)
    h_term = max(0.0, sim_hist)

    composite = 0.50 * z_term + 0.40 * g_term + 0.10 * h_term

    # Calibrated non-linear confidence curve
    if composite <= 0.20:
        confidence = composite * 100.0  # 0 to 20%
    elif composite <= 0.45:
        confidence = 20.0 + ((composite - 0.20) / 0.25) * 30.0  # 20 to 50%
    else:
        confidence = 55.0 + (((composite - 0.45) / 0.55) ** 0.8) * 43.0  # 55 to 98%

    confidence = round(min(99.0, max(0.0, confidence)), 1)
    is_match = confidence >= threshold

    return {
        "is_match": is_match,
        "match": is_match,
        "confidence": confidence,
        "reason": "matched" if is_match else "mismatch",
        "message": "Face matched successfully!" if is_match else "Face does not match registered photo (Face Mismatch)!",
        "engine": "backend-cv-zncc",
    }
