# syntax=docker/dockerfile:1

FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

COPY pyproject.toml requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

RUN chown -R app:app /app

USER app

EXPOSE 8080

CMD ["uvicorn", "src.dresma_rec.main:app", "--host", "0.0.0.0", "--port", "8080"]
