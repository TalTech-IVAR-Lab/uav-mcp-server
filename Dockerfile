FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    TRANSPORT=streamable-http \
    BACKEND_MODE=local

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY scripts/docker_entrypoint.sh /app/scripts/docker_entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install .

EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
