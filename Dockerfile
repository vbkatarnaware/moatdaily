# MoatDaily pipeline image.
#
# Design notes:
#  - Chromium is baked in via `playwright install --with-deps chromium`, so the
#    image is a complete, runnable artifact on ANY host with zero browser setup
#    (matches the "trivial to move to a different server" goal). The browser
#    build always self-matches the installed playwright version, so there's no
#    coupling to whatever Chromium another project happens to have cached.
#  - The image is deliberately SECRET-FREE. config/settings.yaml and
#    credentials/ are .dockerignore'd and mounted read-only at `docker run`
#    time, so nothing sensitive is ever committed to an image layer / GHCR.
#  - data/ and output/ are also mounted at runtime so pipeline reads/writes
#    persist on the host and are servable by Caddy.
#
# Typical run (one pipeline stage at a time):
#   docker run --rm \
#     -v /home/ubuntu/moatdaily/config/settings.yaml:/app/config/settings.yaml:ro \
#     -v /home/ubuntu/moatdaily/credentials:/app/credentials:ro \
#     -v /home/ubuntu/moatdaily/data:/app/data \
#     -v /home/ubuntu/moatdaily/output:/app/output \
#     ghcr.io/vbkatarnaware/moatdaily:latest \
#     python scripts/render_html.py
#
#   NOTE: data/ must be mounted read-write - render_html.py writes resolved
#   per-slide image paths back into data/copy.json. Only settings.yaml and
#   credentials/ are read-only.

FROM python:3.12-slim

# Browsers live at a fixed path inside the image.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Python deps first, so the (slow) dependency layer is cached across code edits.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Chromium + its system libraries, baked in. --with-deps pulls the apt runtime
# libs (libnss3, libatk, ...) headless Chromium needs on a slim base.
RUN playwright install --with-deps chromium

# App code (secrets and generated data are excluded via .dockerignore and
# mounted at runtime instead).
COPY . .

# No long-running process: pipeline stages are invoked on demand. Default just
# proves the image is healthy.
CMD ["python", "-c", "import playwright, cv2, PIL; print('moatdaily image OK')"]
