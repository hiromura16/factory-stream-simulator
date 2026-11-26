"""指定された操作をHTTP APIへ送る。管理認証を設定した環境ではBasic認証を使う。"""

import argparse
import base64
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

p = argparse.ArgumentParser(description="Factory source API client")
p.add_argument(
    "action", choices=["info", "preview", "start", "runs", "stop", "source", "retry"]
)
p.add_argument("--url", default="http://127.0.0.1:8080")
p.add_argument("--spec", type=Path)
p.add_argument("--run-id")
a = p.parse_args()
body = None
route = {
    "info": "/api/info",
    "preview": "/api/preview",
    "start": "/api/runs",
    "runs": "/api/runs",
    "stop": "/api/runs/" + str(a.run_id) + "/stop",
    "source": "/api/source",
    "retry": "/api/outbox/retry",
}[a.action]
if a.action in {"preview", "start", "stop", "retry"}:
    body = json.dumps(json.loads(a.spec.read_text()) if a.spec else {}).encode()
request = Request(
    a.url.rstrip("/") + route,
    data=body,
    headers={"Content-Type": "application/json"},
)
username = os.getenv("ADMIN_USERNAME", "")
password_file = os.getenv("ADMIN_PASSWORD_FILE", "")
if username or password_file:
    if not username or not password_file:
        p.error(
            "管理認証を使う場合は ADMIN_USERNAME と ADMIN_PASSWORD_FILE を指定してください"
        )
else:
    password_file = os.getenv("APP_PASSWORD_FILE", "")
    username = "operator"

if password_file:
    try:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        p.error("管理パスワードのファイルを読み取れません")
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    request.add_unredirected_header("Authorization", f"Basic {credentials}")
with urlopen(request, timeout=30) as r:
    print(json.dumps(json.load(r), ensure_ascii=False, indent=2))
