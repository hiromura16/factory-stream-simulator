"""Create private local settings without printing or overwriting credentials."""

import argparse
import json
import os
import secrets
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--private-dir", type=Path, required=True)
p.add_argument("--data-dir", type=Path, required=True)
p.add_argument("--env-file", type=Path, default=Path(".env"))
a = p.parse_args()
a.private_dir = a.private_dir.expanduser().resolve()
a.data_dir = a.data_dir.expanduser().resolve()
a.private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
a.data_dir.mkdir(parents=True, exist_ok=True)
if a.env_file.exists():
    raise SystemExit("Existing env file preserved; edit it explicitly")
for name in ["mqtt-password", "http-token"]:
    f = a.private_dir / name
    if not f.exists():
        fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as out:
            out.write(secrets.token_urlsafe(32) + "\n")
root = Path(__file__).resolve().parent.parent
text = (root / ".env.example").read_text()
text = text.replace(
    "/absolute/private/sql-writer-password", str(a.private_dir / "sql-writer-password")
)
text = text.replace(
    "/absolute/private/mqtt-password", str(a.private_dir / "mqtt-password")
)
text = text.replace("/absolute/private/http-token", str(a.private_dir / "http-token"))
text = text.replace("/absolute/factory-data/landing", str(a.data_dir / "landing"))
text = text.replace("/absolute/factory-data/mqtt", str(a.data_dir / "mqtt"))
for folder in ["landing", "mqtt"]:
    (a.data_dir / folder).mkdir(exist_ok=True)
fd = os.open(a.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as out:
    out.write(text)
print(
    json.dumps(
        {
            "env_file": str(a.env_file.resolve()),
            "login_required": False,
        },
        ensure_ascii=False,
    )
)
print("VM内の既定URL: ブラウザーで http://127.0.0.1:3562/ を開きます。APP_PORTを変更した場合はその番号を使います。")
