FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    APP_ENV=prod

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY run.py .
COPY src ./src
COPY .env ./.env

# 执行日志默认目录（与 FLOWGAME_EXECUTION_LOG_PATH 容器内路径对应，compose 可挂载卷）
RUN mkdir -p /var/log/flowgame

EXPOSE 8008

HEALTHCHECK --interval=10s --timeout=5s --retries=12 --start-period=30s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/health')"

CMD ["uvicorn", "src.flowgame.app:app", "--host", "0.0.0.0", "--port", "8008"]
