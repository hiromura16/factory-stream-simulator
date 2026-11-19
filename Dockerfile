FROM python:3.12-slim@sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 1000 --create-home factory && mkdir /data && chown factory:factory /data
COPY --chown=factory:factory . .
USER factory
ENV DATA_DIR=/data
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz',timeout=2)"
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080","--workers","1","--no-access-log"]
