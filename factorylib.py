"""Independent source runtime with declarative profiles and presets."""

from __future__ import annotations

import base64
import json
import os
import random
import re
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import ALLOWED_KINDS, ConnectionProfile, RunSpec
from generation import (
    GenerationError,
    batch_limit,
    generate_record,
    map_json,
    record_key,
    sample_offsets,
    stream_payload,
    validate_generation,
)
from storage import ConfigStore

CONTRACT_VERSION = "source.preset.v2"


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, runtime, run_id, stop):
        self.runtime, self.run_id, self.stop = runtime, run_id, stop
        self.stats = {
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "deleted": 0,
            "files": 0,
            "enqueued": 0,
            "delivered": 0,
        }
        self.outputs = []
        self.started = time.monotonic()
        self.spec = None
        self.last_guard_check = 0
        self.last_burst = 0
        self.injected_faults = 0

    def check(self):
        if self.stop.is_set():
            raise JobCancelled()
        if (
            self.spec
            and time.monotonic() - self.started >= self.spec.max_duration_seconds
        ):
            raise JobCancelled()
        if shutil.disk_usage(self.runtime.data_dir).free < 2 * 1024**3:
            raise RuntimeError("disk_space_low")
        if time.monotonic() - self.last_guard_check > 2:
            self.last_guard_check = time.monotonic()
            for line in Path("/proc/meminfo").read_text().splitlines():
                if (
                    line.startswith("MemAvailable:")
                    and int(line.split()[1]) * 1024
                    < float(os.environ.get("MIN_AVAILABLE_GIB", "6")) * 1024**3
                ):
                    raise RuntimeError("host_memory_headroom_low")

    def wait(self, milliseconds):
        if self.stop.wait(milliseconds / 1000):
            raise JobCancelled()

    def progress(self, **increments):
        for name, value in increments.items():
            self.stats[name] = self.stats.get(name, 0) + value
        elapsed = max(0.001, time.monotonic() - self.started)
        self.stats["elapsed_seconds"] = round(elapsed, 3)
        self.stats["events_per_second"] = round(self.stats["processed"] / elapsed, 2)
        self.runtime.update(self.run_id, stats=self.stats, outputs=self.outputs[-10:])

    def inject(self, stage, batch):
        fault = self.spec.faults
        if (
            not fault.enabled
            or fault.action == "none"
            or fault.stage != stage
            or batch < fault.from_batch
            or (batch - fault.from_batch) % fault.every_batches
        ):
            return
        if fault.max_occurrences and self.injected_faults >= fault.max_occurrences:
            return
        self.injected_faults += 1
        self.progress(faults_injected=1)
        if fault.action == "fail":
            raise GenerationError(
                "異常シナリオによる意図的な停止: " + stage + " / batch " + str(batch)
            )
        end = time.monotonic() + fault.delay_ms / 1000
        while time.monotonic() < end:
            self.check()
            self.wait(min(200, max(0, (end - time.monotonic()) * 1000)))

    def pace(self, completed):
        if not self.spec:
            return
        if self.spec.burst_rows:
            boundary = completed // self.spec.burst_rows
            if boundary > self.last_burst:
                delay = (boundary - self.last_burst) * self.spec.burst_pause_ms
                self.last_burst = boundary
                end = time.monotonic() + delay / 1000
                while time.monotonic() < end:
                    self.check()
                    self.wait(min(200, max(0, (end - time.monotonic()) * 1000)))
        if self.spec.target_rate:
            due = (
                self.started
                + self.spec.initial_delay_seconds
                + completed / self.spec.target_rate
            )
            due += random.Random(self.spec.seed ^ completed).uniform(
                0, self.spec.jitter_ms / 1000
            )
            while time.monotonic() < due:
                self.check()
                self.wait(min(200, max(0, (due - time.monotonic()) * 1000)))


class Runtime:
    def __init__(self, kind, handler, max_cycles):
        self.kind, self.handler, self.max_cycles = kind, handler, max_cycles
        self.data_dir = Path(os.environ.get("DATA_DIR", "./data")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = self.data_dir / "jobs.sqlite3"
        self.lock = threading.Lock()
        self.active = None
        self.thread = None
        self.stop = threading.Event()
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, spec TEXT NOT NULL, stats TEXT NOT NULL, outputs TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "UPDATE jobs SET status='interrupted', error='process_restarted' WHERE status IN ('running','stopping')"
            )

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def update(self, run_id, **values):
        values["updated_at"] = datetime.now(timezone.utc).isoformat()
        for key in ["stats", "outputs"]:
            if key in values:
                values[key] = json.dumps(values[key], ensure_ascii=False)
        if not set(values).issubset(
            {"status", "stats", "outputs", "error", "updated_at"}
        ):
            raise ValueError("Invalid job update")
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE id=?",
                [*values.values(), run_id],
            )

    @staticmethod
    def unpack(row):
        if row is None:
            raise HTTPException(404, "実行が見つかりません")
        value = dict(row)
        for key in ["spec", "stats", "outputs"]:
            value[key] = json.loads(value[key])
        return value

    def get(self, run_id):
        with self.connect() as conn:
            return self.unpack(
                conn.execute("SELECT * FROM jobs WHERE id=?", (run_id,)).fetchone()
            )

    def list(self):
        with self.connect() as conn:
            return [
                self.unpack(r)
                for r in conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 30"
                )
            ]

    def validate(self, spec):
        if spec.rows > self.max_cycles:
            raise HTTPException(422, f"1回の上限は{self.max_cycles}レコードです")

    def start(self, spec):
        self.validate(spec)
        with self.lock:
            if self.active:
                raise HTTPException(
                    409, "実行中です。完了または停止後に開始してください"
                )
            run_id = secrets.token_hex(12)
            now = datetime.now(timezone.utc).isoformat()
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        "running",
                        spec.model_dump_json(),
                        "{}",
                        "[]",
                        None,
                        now,
                        now,
                    ),
                )
            self.active, self.stop = run_id, threading.Event()
            self.thread = threading.Thread(
                target=self.execute, args=(run_id, spec, self.stop), daemon=True
            )
            self.thread.start()
            return self.get(run_id)

    def execute(self, run_id, spec, stop):
        ctx = JobContext(self, run_id, stop)
        ctx.spec = spec
        status, error = "completed", None
        try:
            if spec.initial_delay_seconds:
                ctx.wait(spec.initial_delay_seconds * 1000)
            self.handler(spec, ctx)
        except JobCancelled:
            status = "stopped"
        except GenerationError as exc:
            status, error = "failed", str(exc)
        except Exception as exc:
            # Exceptions from drivers may contain credentials or connection strings.
            safe_codes = {
                "target_event_missing",
                "event_identity_conflict",
                "run_size_limit",
                "outbox_size_limit",
                "disk_space_low",
                "landing_disk_space_low",
                "host_memory_headroom_low",
                "source_ownership_mismatch",
            }
            status, error = (
                "failed",
                str(exc) if str(exc) in safe_codes else type(exc).__name__,
            )
        finally:
            self.update(
                run_id,
                status=status,
                error=error,
                stats=ctx.stats,
                outputs=ctx.outputs[-10:],
            )
            with self.lock:
                self.active = None

    def cancel(self, run_id):
        with self.lock:
            if run_id != self.active:
                raise HTTPException(409, "実行中ではありません")
            self.update(run_id, status="stopping")
            self.stop.set()
        return self.get(run_id)


class RetryRequest(BaseModel):
    connection_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    limit: int = Field(default=1000, ge=1, le=1000000)
    batch_size: int = Field(default=100, ge=1, le=1000)


class UploadedConnectionFile(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,3}$",
    )
    content_base64: str = Field(max_length=1500000)


def bootstrap_profiles(kind, store):
    try:
        store.get_profile("default")
        return
    except KeyError:
        pass
    if kind == "sql":
        if os.environ.get("SQL_HOST"):
            file = Path(os.environ.get("SQL_PASSWORD_FILE", "/nonexistent"))
            secret = file.read_text().strip() if file.is_file() else None
            profile = ConnectionProfile(
                id="default",
                name="SQL Server 接続",
                kind="sqlserver",
                host=os.environ["SQL_HOST"],
                port=int(os.environ.get("SQL_PORT", "3510")),
                database=os.environ.get("SQL_DATABASE", "FactorySourceLab"),
                username=os.environ.get("SQL_USER", "factory_source_writer"),
                password=secret or None,
                ssl_mode="require",
            )
        else:
            profile = ConnectionProfile(
                id="default",
                name="ローカルSQLite",
                kind="sqlite",
                sqlite_path="demo.sqlite3",
                ssl_mode="off",
            )
    elif kind == "files":
        directory = os.environ.get(
            "LANDING_DIR",
            str(Path(os.environ.get("DATA_DIR", "./data")).resolve() / "exports"),
        )
        profile = ConnectionProfile(
            id="default",
            name="ローカル ランディング",
            kind="local",
            directory=directory,
            ssl_mode="off",
        )
    elif os.environ.get("MQTT_HOST"):
        file = Path(os.environ.get("MQTT_PASSWORD_FILE", "/nonexistent"))
        profile = ConnectionProfile(
            id="default",
            name="MQTT 接続",
            kind="mqtt",
            host=os.environ["MQTT_HOST"],
            port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USERNAME", ""),
            password=file.read_text().strip() if file.is_file() else None,
            topic=os.environ.get("MQTT_TOPIC", "data/events"),
            ssl_mode="verify"
            if os.environ.get("MQTT_TLS", "").lower() == "true"
            else "off",
        )
    else:
        profile = ConnectionProfile(
            id="default", name="ローカル記録", kind="capture", ssl_mode="off"
        )
    store.save_profile(profile)


def create_app(kind, title, adapter):
    root = Path(__file__).resolve().parent
    store = ConfigStore(Path(os.environ.get("DATA_DIR", "./data")) / "settings")
    bootstrap_profiles(kind, store)

    def initial_preset(spec):
        current, _ = store.get_profile("default")
        if (
            kind == "sql"
            and current.kind == "sqlserver"
            and current.database == "FactorySourceLab"
            and not spec.sql.schema_name
        ):
            spec.sql.schema_name = "synthetic"
        return spec

    store.seed_presets(root / "presets", initial_preset)

    def dispatch(spec, ctx):
        profile, _ = store.get_profile(spec.connection_id, spec.connection_revision)
        (adapter.retry if spec.task == "retry" else adapter.handle)(
            spec, ctx, profile, store
        )

    runtime = Runtime(kind, dispatch, 100000000)

    @asynccontextmanager
    async def lifespan(app):
        yield
        runtime.stop.set()
        if runtime.thread:
            runtime.thread.join(timeout=20)

    app = FastAPI(title=title, version="0.2.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.config_store = store
    app.state.kind = kind

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo request bodies: connection forms contain write-only credentials.
        return JSONResponse(
            {
                "detail": [
                    {"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
                    for e in exc.errors()
                ]
            },
            status_code=422,
        )

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and (
                urlsplit(origin).netloc != request.headers.get("host")
                or urlsplit(origin).scheme != request.url.scheme
            ):
                return JSONResponse(
                    {"detail": "別サイトからの操作は許可されていません"}, 403
                )
            if (
                request.headers.get("content-type", "").split(";", 1)[0]
                != "application/json"
            ):
                return JSONResponse({"detail": "application/jsonが必要です"}, 415)
            try:
                too_large = (
                    int(request.headers.get("content-length", "0")) > 2 * 1024 * 1024
                )
            except ValueError:
                return JSONResponse({"detail": "Content-Lengthが不正です"}, 400)
            if too_large:
                return JSONResponse({"detail": "設定JSONは2MiB以下にしてください"}, 413)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Cache-Control": "no-store",
            }
        )
        return response

    app.mount("/static", StaticFiles(directory=root / "static"), name="static")

    @app.get("/")
    def index():
        return FileResponse(root / "static/index.html")

    @app.get("/healthz")
    def health():
        return {"status": "ok", "service": kind, "version": "0.2.0"}

    def profile(identity, revision=None):
        try:
            value, version = store.get_profile(identity, revision)
        except KeyError:
            raise HTTPException(404, "接続プロファイルが見つかりません") from None
        if value.kind not in ALLOWED_KINDS[kind]:
            raise HTTPException(422, "このツールでは使用できない接続方式です")
        return value, version

    def checked(spec):
        if kind != "stream" and spec.task != "generate":
            raise HTTPException(422, "再送はストリームツールだけで使用できます")
        if (
            kind != "files"
            and spec.faults.enabled
            and spec.faults.artifact_mode != "none"
        ):
            raise HTTPException(422, "不正ファイルの生成設定はファイルツール専用です")
        try:
            validate_generation(spec)
        except (ValueError, TypeError, OverflowError) as exc:
            raise HTTPException(
                422,
                str(exc)
                if isinstance(exc, GenerationError)
                else "生成ルールの型・範囲・日時を確認してください",
            ) from None
        return spec

    def safe_call(callback, *args):
        try:
            return callback(*args)
        except HTTPException:
            raise
        except GenerationError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception as exc:
            raise HTTPException(
                503,
                f"接続先の処理に失敗しました ({type(exc).__name__})。接続情報・権限・対象の構造を確認してください。",
            ) from None

    @app.get("/api/info")
    def information():
        from helptext import CONNECTION_HELP

        default = RunSpec()
        default_profile, _ = profile("default")
        if (
            kind == "sql"
            and default_profile.kind == "sqlserver"
            and default_profile.database == "FactorySourceLab"
        ):
            default.sql.schema_name = "synthetic"
        return {
            "kind": kind,
            "title": title,
            "version": "0.2.0",
            "contract_version": CONTRACT_VERSION,
            "max_rows": 100000000,
            "defaults": default.model_dump(mode="json"),
            "connection_kinds": sorted(ALLOWED_KINDS[kind]),
            "connection_help": {
                k: {
                    "label": CONNECTION_HELP[k][0],
                    "description": CONNECTION_HELP[k][1],
                }
                for k in ALLOWED_KINDS[kind]
            },
        }

    @app.get("/api/schemas")
    def schemas():
        from helptext import annotated_schemas

        return annotated_schemas(kind)

    def files_root():
        path = Path(
            os.environ.get(
                "CONNECTION_FILES_DIR", str(store.root.parent / "connection-files")
            )
        ).resolve()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @app.get("/api/connection-files")
    def connection_files():
        root = files_root()
        return {
            "files": [
                {"name": str(p.relative_to(root)), "bytes": p.stat().st_size}
                for p in root.rglob("*")
                if p.is_file() and not p.is_symlink()
            ][:200]
        }

    @app.post("/api/connection-files")
    def upload_connection_file(value: UploadedConnectionFile):
        root = files_root()
        target = (root / value.name).resolve()
        if not target.is_relative_to(root) or any(
            part in {".", ".."} for part in Path(value.name).parts
        ):
            raise HTTPException(422, "ファイル名を確認してください")
        try:
            content = base64.b64decode(value.content_base64, validate=True)
        except ValueError:
            raise HTTPException(422, "Base64データが不正です") from None
        if len(content) > 1024 * 1024:
            raise HTTPException(413, "接続用ファイルは1MiB以下にしてください")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = target.with_name(target.name + ".upload-" + secrets.token_hex(8))
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return {"name": value.name, "bytes": len(content), "permissions": "600"}

    @app.get("/api/connections")
    def connections():
        return {
            "connections": [
                p for p in store.profiles() if p["kind"] in ALLOWED_KINDS[kind]
            ]
        }

    @app.post("/api/connections")
    def save_connection(value: ConnectionProfile):
        if value.kind not in ALLOWED_KINDS[kind]:
            raise HTTPException(422, "このツールでは使用できない接続方式です")
        return store.save_profile(value)

    @app.get("/api/connections/{identity}/export")
    def export_connection(identity: str):
        value, revision = profile(identity)
        result = store.public(value)
        for key in ["configured_secrets", "configured_headers"]:
            result.pop(key, None)
        return result

    @app.post("/api/connections/{identity}/test")
    def test_connection(identity: str):
        value, _ = profile(identity)
        return safe_call(adapter.test_connection, value)

    @app.get("/api/presets")
    def presets():
        return {"presets": store.presets()}

    @app.post("/api/presets/{identity}")
    def save_preset(identity: str, spec: RunSpec):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
            raise HTTPException(
                422, "プリセットIDは英数字・ハイフン・下線で指定してください"
            )
        return store.save_preset(identity, checked(spec))

    @app.get("/api/presets/{identity}/export")
    def export_preset(identity: str):
        try:
            return store.get_preset(identity)["spec"]
        except KeyError:
            raise HTTPException(404, "プリセットが見つかりません") from None

    @app.post("/api/preview")
    def preview(spec: RunSpec):
        checked(spec)
        offsets = sorted(set(list(range(min(3, spec.rows))) + sample_offsets(spec)))[
            :12
        ]
        records = []
        anomaly_hits = []
        for offset in offsets:
            hits = []
            records.append(
                generate_record(spec, spec.start_sequence + offset, trace=hits)
            )
            anomaly_hits.append(hits)
        payloads = []
        for i, row in enumerate(records):
            meta = {
                "record_key": record_key(spec, spec.start_sequence + offsets[i]),
                "sequence": spec.start_sequence + offsets[i],
                "run_key": spec.run_key,
            }
            template = (
                spec.stream.payload_template
                if kind == "stream"
                else spec.files.json_template
            )
            try:
                payload = (
                    stream_payload(spec, row, spec.start_sequence + offsets[i])
                    if kind == "stream"
                    else map_json(template, row, spec.parameters, meta)
                )
            except GenerationError as exc:
                raise HTTPException(422, str(exc)) from None
            payloads.append(payload)
        return {
            "sample_sequences": [spec.start_sequence + i for i in offsets],
            "anomaly_hits": anomaly_hits,
            "validated_spec": spec.model_dump(mode="json"),
            "writes": False,
            "records": records,
            "json_payloads": payloads,
            "rows": spec.rows,
            "effective_batch_limit": batch_limit(spec, spec.batch_size),
            "estimated_seconds": round(spec.rows / spec.target_rate, 2)
            if spec.target_rate
            else None,
            "note": "プレビューでは接続・書き込み・送信しません。正常位置と異常条件の開始位置を含むサンプルを表示します。目標速度は性能保証ではありません。",
        }

    @app.post("/api/runs", status_code=202)
    def start(spec: RunSpec):
        checked(spec)
        _, revision = profile(spec.connection_id, spec.connection_revision)
        return runtime.start(spec.model_copy(update={"connection_revision": revision}))

    @app.get("/api/runs")
    def runs():
        return {"runs": runtime.list()}

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        return runtime.get(run_id)

    @app.post("/api/runs/{run_id}/stop")
    def stop(run_id: str):
        return runtime.cancel(run_id)

    @app.get("/api/source")
    def source():
        if kind == "stream":
            return adapter.summary()
        value, _ = profile("default")
        return safe_call(adapter.test_connection, value)

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        with runtime.connect() as conn:
            rows = conn.execute(
                "SELECT status,count(*) FROM jobs GROUP BY status"
            ).fetchall()
        return "# TYPE source_jobs gauge\n" + "".join(
            f'source_jobs{{service="{kind}",status="{r[0]}"}} {r[1]}\n' for r in rows
        )

    if kind == "sql":

        @app.post("/api/table/prepare")
        def prepare(spec: RunSpec):
            checked(spec)
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.prepare_table, value, spec)

        @app.post("/api/table/inspect")
        def inspect_table(spec: RunSpec):
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.inspect_table, value, spec)

        @app.post("/api/table/ddl")
        def ddl(spec: RunSpec):
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.ddl, value, spec)

    if kind == "files":

        @app.get("/api/runs/{run_id}/image")
        def image(run_id: str):
            return safe_call(adapter.artifact, runtime.get(run_id), store)

    if kind == "stream":

        @app.get("/api/outbox")
        def outbox():
            return adapter.summary()

        @app.post("/api/outbox/retry", status_code=202)
        def retry(value: RetryRequest):
            _, revision = profile(value.connection_id)
            spec = RunSpec(
                name="未配送データの再送",
                connection_id=value.connection_id,
                connection_revision=revision,
                rows=value.limit,
                batch_size=value.batch_size,
                target_rate=0,
                task="retry",
            )
            return runtime.start(spec)

    return app
