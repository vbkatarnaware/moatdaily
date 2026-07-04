#!/usr/bin/env python3
"""
MoatDaily - Deterministic Premium Finish
Pure PIL/numpy post-processing applied to every sourced hero photo: a gentle
brand-ward color grade, a light vignette, and a touch of film grain. No AI,
no tokens - the editorial texture that makes a plain sourced photo feel
intentional instead of a raw stock download.
"""

import io

from PIL import Image, ImageFilter, ImageEnhance


def _hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def apply_color_grade(img, tint_hex="#1A1A2E", strength=0.10):
    """Blend a low-opacity brand tint over the photo + a small contrast lift."""
    tint = Image.new("RGB", img.size, _hex_to_rgb(tint_hex))
    graded = Image.blend(img, tint, strength)
    graded = ImageEnhance.Contrast(graded).enhance(1.06)
    graded = ImageEnhance.Color(graded).enhance(0.94)
    return graded


def apply_vignette(img, strength=0.35, inner_radius_frac=0.55):
    """Darken the edges with a radial gradient so the frame feels intentional.
    Edges (distance from center >= inner_radius_frac of the corner distance)
    darken toward `strength`; the center stays untouched.
    """
    try:
        import numpy as np
    except ImportError:
        return img

    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt((xx - w / 2) ** 2 + (yy - h / 2) ** 2)
    max_radius = (w ** 2 + h ** 2) ** 0.5 / 2
    frac = dist / max_radius
    darken = np.clip((frac - inner_radius_frac) / (1 - inner_radius_frac), 0, 1) * strength
    mask = Image.fromarray((darken * 255).astype("uint8"), mode="L")
    mask = mask.filter(ImageFilter.GaussianBlur(max(w, h) * 0.05))
    black = Image.new("RGB", img.size, (0, 0, 0))
    return Image.composite(black, img, mask)


def apply_grain(img, amount=0.02):
    """Subtle film grain - breaks up flat gradients/skies, adds editorial texture."""
    try:
        import numpy as np
    except ImportError:
        return img

    arr = np.asarray(img).astype("int16")
    noise = np.random.default_rng().normal(0, 255 * amount, arr.shape[:2])
    noise = noise[:, :, None]
    arr = arr + noise
    arr = arr.clip(0, 255).astype("uint8")
    return Image.fromarray(arr, mode="RGB")


def finish(image_bytes, tint_hex="#1A1A2E", grade_strength=0.10, vignette_strength=0.35, grain_amount=0.02):
    """Full deterministic finish pipeline: grade -> vignette -> grain. Fails open (returns original bytes)."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = apply_color_grade(img, tint_hex, grade_strength)
        img = apply_vignette(img, vignette_strength)
        img = apply_grain(img, grain_amount)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception as e:
        print(f"[WARN] imagefx.finish failed, using unfinished image: {e}")
        return image_bytes
