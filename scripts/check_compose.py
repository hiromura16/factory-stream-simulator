"""Compose補間だけを検証。起動・接続・秘密ファイル作成はしない。"""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy")
source = json.loads((ROOT / "compose.yaml").read_text())
# 実設定、Dockerクライアント設定、.envを参照しない検証用環境。
env = {k: os.environ[k] for k in ("PATH", "HOME", "DOCKER_HOST")
       if k in os.environ}
env.update(APP_PORT="18080", BIND_IP="127.0.0.1",
           LANDING_DIR="/tmp/simulator-check/landing",
           MQTT_DATA_DIR="/tmp/simulator-check/mqtt",
           MQTT_PASSWORD_FILE="/tmp/simulator-check/password")
with tempfile.TemporaryDirectory() as tmp:
    empty = Path(tmp) / "empty.env"
    empty.write_text("")
    for enabled in (False, True):
        values = {k: ("localhost,127.0.0.1,::1" if "no_proxy" == k.lower()
                      else "http://proxy.example.test:3128") for k in KEYS}
        current = dict(env)
        if enabled:
            current.update(values)
        result = subprocess.run(
            ["docker", "compose", "--env-file", str(empty),
             "-f", str(ROOT / "compose.yaml"), "config", "--format", "json"],
            env=current, check=True, capture_output=True, text=True)
        config = json.loads(result.stdout)
        app = config["services"]["app"]
        assert app["build"].get("args", {}) == (values if enabled else {})
        assert not set(KEYS).intersection(app.get("environment", {}))
        assert app["read_only"] is True
        assert app["ports"][0]["host_ip"] == "127.0.0.1"
        if "mqtt" in config["services"]:
            mqtt = config["services"]["mqtt"]
            assert "build" not in mqtt
            assert not set(KEYS).intersection(mqtt.get("environment", {}))
            assert mqtt["image"] == source["services"]["mqtt"]["image"]
        print("compose proxy=" + ("sample" if enabled else "unset") + ": OK")
