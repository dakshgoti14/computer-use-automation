# Public demo deployment image (e.g. Render). Runs two processes in one
# container: the demo bank app (internal only, 127.0.0.1:8001 - the target
# surface under automation) and this system's own API (0.0.0.0:$PORT -
# what the platform actually exposes), plus a real headless Chromium for
# Playwright to drive. Not used for local development - see README.md
# ("Installation") for the normal `make install` / venv path, which is
# faster to iterate in.

FROM python:3.12-slim

# Playwright's Chromium needs a real (if minimal) set of system libraries;
# `playwright install --with-deps` below handles most of it, but curl is
# needed for the container's own startup healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/app

COPY pyproject.toml ./
COPY app ./app
COPY demo_app ./demo_app
COPY capabilities ./capabilities
COPY evidence ./evidence
COPY scripts ./scripts

RUN pip install --no-cache-dir -e . \
    && playwright install --with-deps chromium

ENV PUBLIC_DEMO_MODE=true \
    HEADLESS_BROWSER=true \
    DEMO_APP_HOST=127.0.0.1 \
    DEMO_APP_PORT=8001 \
    DEMO_APP_BASE_URL=http://127.0.0.1:8001 \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

COPY docker/start.sh /srv/app/start.sh
RUN chmod +x /srv/app/start.sh

# Render (and most PaaS targets) inject $PORT at runtime; default to 8000
# for `docker run` without one.
ENV PORT=8000
EXPOSE 8000

CMD ["/srv/app/start.sh"]
