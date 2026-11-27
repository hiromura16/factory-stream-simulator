FROM python:3.12-slim@sha256:4a68d3169325c47e1bafbb86425220f03fbdff6f079a419e8d39407183288217
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 1000 --create-home factory && mkdir /data && chown factory:factory /data
COPY --chown=factory:factory . .
USER factory
ENV DATA_DIR=/data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz',timeout=2)"
# 実行中のジョブはプロセス内で管理するため、workerは1つに固定する。
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080","--workers","1","--no-access-log"]
