# 読解: 固定digestのPythonベースを使い、同じタグの内容変更に依存しない。
FROM python:3.12-slim@sha256:05a994d2344eb364cc186910f4fc8786a38215f39f00d0acc25bff33a08f4177
# 読解: ビルドまたは実行時の既定環境を設定する。外部認証値はここに埋め込まない。
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# 読解: 以後のコピー・起動の作業ディレクトリをアプリ領域に固定する。
WORKDIR /app
# 読解: 依存一覧またはアプリ資材を取り込む。所有者指定は非特権起動の書込境界に合わせる。
COPY requirements.txt .
# 読解: ビルド段階の依存導入または専用利用者・保存先の準備。アプリ実行時の処理ではない。
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 1000 --create-home factory && mkdir /data && chown factory:factory /data
# 読解: 依存一覧またはアプリ資材を取り込む。所有者指定は非特権起動の書込境界に合わせる。
COPY --chown=factory:factory . .
# 読解: ここからは非特権利用者で実行する。管理権限をアプリへ引き継がない。
USER factory
# 読解: ビルドまたは実行時の既定環境を設定する。外部認証値はここに埋め込まない。
ENV DATA_DIR=/data
# 読解: コンテナ内の待受ポートを記述する。ホスト公開の指定はCompose側で行う。
EXPOSE 8080
# 読解: ローカルのhealthzを定期確認する。下流システムの到達確認までは行わない。
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/healthz',timeout=2)"
# 読解: ASGIを単一workerで起動し、プロセス内の単一実行枠と整合させる。
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080","--workers","1","--no-access-log"]
