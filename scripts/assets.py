#!/usr/bin/env python3
"""
MoatDaily - Asset Resolution
Deterministic image/logo sourcing + treatment for the renderer.

The AI only supplies hints (image_url override, entities, logos, primary_query).
This module does all the sourcing waterfall, cropping, and optional cutout work
so no per-post AI reasoning about pixels is needed.

Sourcing waterfall (stops at first success), all free / no API key:
  1. assets.image_url       - AI-picked (agent googled it directly, or the pick step below chose it)
  2. article's own og:image - parsed from source_url
  3. Brave image search     - by entities[0] or primary_query
  4. None -> caller renders a branded gradient fallback (never a broken image)

Image treatment (default "fullbleed"):
  - The renderer fits every hero into the PHOTO ZONE (the top ~62% of the post,
    NOT the full 4:5 canvas) - the reserved text panel below it never overlaps
    the photo, so the subject can never end up under the headline.
  - Source aspect ratio within cover_tolerance of the photo-zone ratio - subject-aware
    (face, then saliency) COVER crop fills the zone without destroying the photo.
  - Source aspect ratio far off (extreme portrait/panorama) - center-fit + LETTERBOX
    on brand-black, so an off-ratio photo floats cleanly instead of an ugly crop.
  - "cutout" (explicit opt-in) - rembg cutout, guarded: falls back to cover/letterbox
    if the result is mostly transparent or the subject bbox spans the whole frame.
"""

import base64
import io
import urllib.request
import urllib.parse
from pathlib import Path

from PIL import Image, ImageStat

import imagefx
import fetchers

USER_AGENT = "Mozilla/5.0 (compatible; MoatDailyBot/1.0; +https://moatdaily.example)"
REQUEST_TIMEOUT = 8


def _get(url, timeout=REQUEST_TIMEOUT, accept=None):
    """GET a URL and return raw bytes, or None on any failure."""
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return resp.read()
    except Exception:
        return None



# ---------------------------------------------------------------------------
# Sourcing waterfall
# ---------------------------------------------------------------------------


def get_og_image_url(article_url):
    """
    The article's <meta property="og:image"> - usually the most relevant photo.
    Fetched via fetchers.fetch_article, which tries Scrapling's stealth fetcher
    first (bypasses 403/hotlink-protected sites a plain GET can't reach) and
    falls back to a plain GET automatically.
    """
    if not article_url:
        return None
    og_image = fetchers.fetch_article(article_url).get("og_image")
    return urllib.parse.urljoin(article_url, og_image) if og_image else None


def get_wikipedia_lead_image(entity_name):
    """
    Wikipedia REST API lead image for a named entity (person, company, place).
    Free, no key - the canonical photo source for anyone/anything with a page,
    and usually higher quality/more relevant than a generic image search hit.
    """
    if not entity_name:
        return None
    title = urllib.parse.quote(entity_name.strip().replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    data = _get(url, accept="application/json")
    if not data:
        return None
    try:
        import json as _json
        payload = _json.loads(data)
    except Exception:
        return None
    image = payload.get("originalimage") or payload.get("thumbnail")
    return image.get("source") if image else None


def get_brave_image(query, api_key):
    """Brave Image Search API - high quality web image search."""
    if not query or not api_key:
        return None
    url = f"https://api.search.brave.com/res/v1/images/search?q={urllib.parse.quote(query)}"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
        "User-Agent": USER_AGENT
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                data = resp.read()
                if resp.info().get('Content-Encoding') == 'gzip':
                    import gzip
                    data = gzip.decompress(data)
                import json as _json
                payload = _json.loads(data)
                results = payload.get("results", [])
                if results:
                    return results[0].get("properties", {}).get("url")
    except Exception as e:
        print(f"[WARN] Brave API error: {e}")
        return None
    return None


def iter_image_candidates(assets_spec, source_url, source_image_url=None, brave_api_key=None):
    """
    Yield (url, source_label, trusted) waterfall candidates in priority order.
    trusted=True means "use as-is" - either an explicit AI/agent pick (the primary
    path: the agent googled the story directly and knows this is the right photo),
    or a candidate the select-images vision step already confirmed. Untrusted
    candidates get run through the photo-quality guard before use, since og:image/
    Wikipedia lookups on a company/topic frequently resolve to a flat logo, not a photo.
    """
    override = (assets_spec or {}).get("image_url", "").strip()
    if override:
        yield override, "override", True

    if source_image_url:
        yield source_image_url, "api:image", False

    og_url = get_og_image_url(source_url)
    if og_url:
        yield og_url, "og:image", False

    entities = (assets_spec or {}).get("entities", [])
    for entity in entities[:2]:
        wiki_url = get_wikipedia_lead_image(entity)
        if wiki_url:
            yield wiki_url, f"wikipedia:{entity}", False

    # Entity name first, then the free-text query, as the Brave search term.
    search_query = entities[0] if entities else (assets_spec or {}).get("primary_query", "").strip()
    if search_query and brave_api_key:
        brave_url = get_brave_image(search_query, brave_api_key)
        if brave_url:
            yield brave_url, "brave_search", False


def resolve_image_url(assets_spec, source_url, brave_api_key=None):
    """Back-compat convenience: first candidate URL regardless of photo-quality."""
    for url, label, _trusted in iter_image_candidates(assets_spec, source_url, brave_api_key=brave_api_key):
        return url, label
    return None, None


def _is_probably_photo(image_bytes):
    """
    Cheap heuristic to reject flat logos/wordmarks (common when a Wikipedia/og:image
    lookup for a company resolves to its infobox logo instead of an actual photo).
    Logos are dominated by one or two flat colors; photos have much more variance.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((48, 48))
    except Exception:
        return False
    from collections import Counter
    pixels = list(img.getdata())
    dominant_ratio = Counter(pixels).most_common(1)[0][1] / len(pixels)
    return dominant_ratio < 0.35


# ---------------------------------------------------------------------------
# Image treatment: cover crop / letterbox fit (default) vs guarded cutout (opt-in)
# ---------------------------------------------------------------------------

def download_image_bytes(url):
    return _get(url, timeout=12)


_HAARCASCADE_NAME = "haarcascade_frontalface_default.xml"
_BUNDLED_HAARCASCADE = str(Path(__file__).parent / "data" / _HAARCASCADE_NAME)


def _haarcascade_path():
    """Some opencv-headless wheels ship cv2.data.haarcascades as an empty dir - fall
    back to our own bundled copy (scripts/data/) so face detection doesn't silently
    degrade to saliency-only on machines where that packaging quirk shows up (it did
    on the dev box; may recur on the EC2 box).
    """
    import cv2
    cv2_path = cv2.data.haarcascades + _HAARCASCADE_NAME
    return cv2_path if Path(cv2_path).exists() else _BUNDLED_HAARCASCADE


def _face_center(cv_img_bgr):
    """Return (x, y) of the largest detected face, or None."""
    try:
        import cv2
        gray = cv2.cvtColor(cv_img_bgr, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(_haarcascade_path())
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda rect: rect[2] * rect[3])
        return (x + w // 2, y + h // 3)  # bias slightly toward eyes, not chin
    except Exception as e:
        print(f"[WARN] Face detection failed: {e}")
        return None


def _saliency_center(cv_img_bgr):
    """Return (x, y) centroid of the most visually salient region, or None.
    Used when there's no face - keeps the actual subject (product, building,
    skyline focal point) inside the frame instead of a fixed top-weighted guess.
    """
    try:
        import cv2
        import numpy as np
        saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
        success, sal_map = saliency.computeSaliency(cv_img_bgr)
        if not success:
            return None
        sal_map = (sal_map * 255).astype("uint8")
        threshold = np.percentile(sal_map, 80)
        ys, xs = np.where(sal_map >= threshold)
        if len(xs) == 0:
            return None
        return (int(xs.mean()), int(ys.mean()))
    except Exception as e:
        print(f"[WARN] Saliency detection failed: {e}")
        return None


def smart_crop(image_bytes, target_w, target_h):
    """
    COVER crop to exactly fill target_w x target_h, biased toward the actual
    subject: face detection first, then saliency (visual-interest) detection,
    then a fixed top-weighted fallback. This is what keeps the subject inside
    the photo zone instead of getting cut off by a blind center crop.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    src_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_height = target_h
        new_width = int(target_h * src_ratio)
    else:
        new_width = target_w
        new_height = int(target_w / src_ratio)

    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    left = (new_width - target_w) // 2
    top = max(0, int((new_height - target_h) * 0.35))

    center = None
    try:
        import cv2
        import numpy as np
        cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        center = _face_center(cv_img) or _saliency_center(cv_img)
    except ImportError:
        center = None

    if center:
        cx, cy = center
        left = max(0, min(cx - target_w // 2, new_width - target_w))
        top = max(0, min(cy - target_h // 3, new_height - target_h))

    img = img.crop((left, top, left + target_w, top + target_h))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def fit_letterbox(image_bytes, target_w, target_h, bg_hex="#0A0A0A"):
    """
    Center-fit the whole image inside target_w x target_h WITHOUT cropping, painting
    the leftover margin with bg_hex. Used when the source aspect ratio is too far from
    the target to crop cleanly - the brand-black bars blend into the post background.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    canvas = Image.new("RGB", (target_w, target_h), bg_hex)
    scale = min(target_w / img.width, target_h / img.height)
    new_w = max(1, int(img.width * scale))
    new_h = max(1, int(img.height * scale))
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def guarded_cutout(image_bytes):
    """
    Run rembg; return cutout bytes only if the result is a real subject
    (not mostly-transparent). Otherwise return None so the caller falls
    back to a direct fullbleed embed.
    """
    try:
        import rembg
    except ImportError:
        return None

    try:
        output = rembg.remove(image_bytes)
    except Exception:
        return None

    try:
        cutout = Image.open(io.BytesIO(output)).convert("RGBA")
    except Exception:
        return None

    alpha = cutout.split()[-1]
    stat = ImageStat.Stat(alpha)
    opaque_ratio = stat.mean[0] / 255.0  # fraction of the canvas that ended up opaque

    # Guard 1: rembg failed to find a clean subject (blank/near-empty or it kept ~everything)
    if opaque_ratio < 0.03 or opaque_ratio > 0.92:
        return None

    # Guard 2: a real isolated subject shouldn't touch all four edges of the frame
    # (a building/landscape photo that "cuts out" busily will span the full bbox).
    bbox = alpha.getbbox()
    if bbox:
        left, top, right, bottom = bbox
        w, h = alpha.size
        spans_full_width = (right - left) / w > 0.95
        spans_full_height = (bottom - top) / h > 0.95
        if spans_full_width and spans_full_height:
            return None

        # Crop to the subject's bounding box (+ a small margin). Without this, rembg's
        # output keeps the full source canvas size - the transparent padding around a
        # small subject scales along with it in the template, so the subject still
        # renders tiny. Cropping tight is what lets the template fill the zone with it.
        margin = int(max(right - left, bottom - top) * 0.06)
        left = max(0, left - margin)
        top = max(0, top - margin)
        right = min(w, right + margin)
        bottom = min(h, bottom + margin)
        cutout = cutout.crop((left, top, right, bottom))

    buf = io.BytesIO()
    cutout.save(buf, format="PNG")
    return buf.getvalue()


def to_data_uri(image_bytes, mime="image/jpeg"):
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


BRAND_GRADIENT_FALLBACK = (
    "linear-gradient(135deg, #1A1A2E 0%, #0A0A0A 60%)"
)


def _fit_to_frame(raw, target_w, target_h, cover_tolerance, letterbox_bg):
    """
    Decide cover-crop vs letterbox by how far the source aspect ratio is from target.
    Close enough -> smart cover crop (fills the frame). Too far -> letterbox (no crop loss).
    """
    try:
        img = Image.open(io.BytesIO(raw))
        src_ratio = img.width / img.height
    except Exception:
        return smart_crop(raw, target_w, target_h)

    target_ratio = target_w / target_h
    if abs(src_ratio - target_ratio) <= cover_tolerance:
        return smart_crop(raw, target_w, target_h)
    return fit_letterbox(raw, target_w, target_h, letterbox_bg)


def resolve_hero_image(assets_spec, source_url, treatment, target_w, target_h,
                       cover_tolerance=0.85, letterbox_bg="#0A0A0A", source_image_url=None, brave_api_key=None,
                       finish_opts=None):
    """
    Full pipeline: walk the sourcing waterfall until a usable photo is found, fit it to
    the target zone (target_w x target_h is the PHOTO ZONE, not the full canvas - the
    reserved text panel below it is rendered separately), then apply the deterministic
    premium finish. Returns a dict: {"kind": "photo"|"cutout"|"none", "data_uri": str|None, "source": str|None}
    """
    raw = None
    source_label = None
    for url, label, trusted in iter_image_candidates(assets_spec, source_url, source_image_url, brave_api_key):
        candidate = download_image_bytes(url)
        if not candidate:
            continue
        if not trusted and not _is_probably_photo(candidate):
            continue  # looked like a flat logo/wordmark, not a real photo - try next candidate
        raw, source_label = candidate, label
        break

    if not raw:
        return {"kind": "none", "data_uri": None, "source": None}

    if treatment == "cutout":
        cutout_bytes = guarded_cutout(raw)
        if cutout_bytes:
            return {
                "kind": "cutout",
                "data_uri": to_data_uri(cutout_bytes, "image/png"),
                "source": source_label,
            }
        # guard failed -> fall through to cover/letterbox with the same source image

    try:
        fitted = _fit_to_frame(raw, target_w, target_h, cover_tolerance, letterbox_bg)
        fitted = imagefx.finish(fitted, **(finish_opts or {}))
    except Exception:
        return {"kind": "none", "data_uri": None, "source": None}

    return {
        "kind": "photo",
        "data_uri": to_data_uri(fitted, "image/jpeg"),
        "source": source_label,
    }
