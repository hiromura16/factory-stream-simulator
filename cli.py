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
password = Path(os.environ["APP_PASSWORD_FILE"]).read_text().strip()
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
headers = {
    "Authorization": "Basic "
    + base64.b64encode(("operator:" + password).encode()).decode(),
    "Content-Type": "application/json",
}
with urlopen(
    Request(a.url.rstrip("/") + route, data=body, headers=headers), timeout=30
) as r:
    print(json.dumps(json.load(r), ensure_ascii=False, indent=2))
