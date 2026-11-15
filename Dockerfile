# syntax=docker/dockerfile:1

FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.14-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

RUN groupadd --system --gid 10001 dehecho \
 && useradd --system --uid 10001 --gid dehecho --no-create-home dehecho

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY main.py ./
COPY app ./app
COPY data ./data
COPY datos_mensuales_2014_2023 ./datos_mensuales_2014_2023
COPY definitivo.csv ./
COPY docs/investigacion ./docs/investigacion

USER dehecho
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=3); sys.exit(0)"

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
