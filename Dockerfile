ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.10-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    APP_ENV=prod \
    FLOWGAME_HOST=0.0.0.0 \
    FLOWGAME_PORT=8008 \
    FLOWGAME_RELOAD=false

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip config set global.index-url "${PIP_INDEX_URL}" \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY run.py .
COPY src ./src
COPY .env ./.env

RUN mkdir -p /var/log/flowgame

EXPOSE 8008

HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/health')"

CMD ["python", "run.py"]
