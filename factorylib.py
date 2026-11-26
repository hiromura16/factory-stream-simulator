# アダプターだけが方式固有の生成・送信を行い、例外の秘密情報はこの境界で外へ出さない。
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

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from operation_confirmation import CONFIRMATION_HEADER, install_operation_gate
from api_support import (
    display_location, history_error, install_error_handlers, install_help,
    management_credentials, unauthorized_management,
)
from config import ALLOWED_KINDS, ConnectionProfile, RunSpec
from generation import anomaly_warnings
from generation import (
    GenerationError,
    batch_limit,
    generate_record,
    sample_offsets,
    validate_generation,
)
from storage import ConfigStore
from stream_events import build_events, check_stream_profile, check_stream_topic

CONTRACT_VERSION = "source.preset.v2"


class JobCancelled(Exception):
    # 利用者の停止要求または実行時間上限による協調停止を表す。
    pass


class JobContext:
    """アダプターへ停止判定・進捗・負荷調整を提供する実行単位の状態。"""
    # 出力履歴や異常注入回数は実行間で共有せず、永続化はprogressに任せる。
    def __init__(self, runtime, run_id, stop):
        """runtime・run_id・停止イベントを受け取り、一実行の計数と単調時計を初期化する。"""
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
        """停止・時間・空き容量・メモリー余力を確認し、継続不能なら例外にする。"""
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
                    < float(os.environ.get("MIN_AVAILABLE_GIB", "1")) * 1024**3
                ):
                    raise RuntimeError("host_memory_headroom_low")

    def wait(self, milliseconds):
        """待機中も停止イベントを受け付ける。停止時は協調停止の例外にする。"""
        if self.stop.wait(milliseconds / 1000):
            raise JobCancelled()

    def progress(self, **increments):
        """実績を加算し、経過時間と直近の出力情報を実行履歴へ保存する。"""
        for name, value in increments.items():
            self.stats[name] = self.stats.get(name, 0) + value
        elapsed = max(0.001, time.monotonic() - self.started)
        self.stats["elapsed_seconds"] = round(elapsed, 3)
        self.stats["events_per_second"] = round(self.stats["processed"] / elapsed, 2)
        self.runtime.update(self.run_id, stats=self.stats, outputs=self.outputs[-10:])

    def inject(self, stage, batch):
        """段階とバッチ位置が一致する異常注入を、回数上限内で実行する。"""
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
        """完了件数に合わせてバースト休止と目標レートの待機を行う。"""
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
    """単一の実行枠とSQLite履歴を管理し、アダプターをワーカースレッドで動かす。"""
    def __init__(self, kind, handler, max_cycles):
        """履歴を初期化し、前プロセスの実行中レコードを中断状態にする。"""
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
        """実行履歴用トランザクションを開き、終了時に必ず接続を閉じる。"""
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
        """更新可能な列だけを受け付け、JSON項目を直列化して履歴を更新する。"""
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
        """履歴のJSON項目を復元する。対象がなければHTTP 404を返す。"""
        if row is None:
            raise HTTPException(404, "実行が見つかりません")
        value = dict(row)
        value["error_message"] = history_error(value.get("error"))
        for key in ["spec", "stats", "outputs"]:
            value[key] = json.loads(value[key])
        return value

    def get(self, run_id):
        """指定実行の保存済み状態を返す。処理の完了までは待たない。"""
        with self.connect() as conn:
            return self.unpack(
                conn.execute("SELECT * FROM jobs WHERE id=?", (run_id,)).fetchone()
            )

    def list(self):
        """新しい順で最大30件の実行履歴を返す。"""
        with self.connect() as conn:
            return [
                self.unpack(r)
                for r in conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT 30"
                )
            ]

    def validate(self, spec):
        """実行件数がランタイムの上限以内かを確認する。"""
        if spec.rows > self.max_cycles:
            raise HTTPException(422, f"1回の上限は{self.max_cycles}レコードです")

    def start(self, spec):
        """実行枠を排他確保し、履歴作成後にワーカースレッドを開始する。"""
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
        """アダプターの終了状態を保存し、最後に実行枠を解放する。

        ドライバー例外の本文は秘密値を含む可能性があるため、既知の安全な
        コード以外は例外の型名だけを記録する。
        """
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
            status, error = "failed", f"generation_error: {display_location(getattr(exc, 'path', ()))}　{exc}"
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
        """現在の実行だけに停止を要求する。即時ロールバックは保証しない。"""
        with self.lock:
            if run_id != self.active:
                raise HTTPException(409, "実行中ではありません")
            self.update(run_id, status="stopping")
            self.stop.set()
        return self.get(run_id)


class CaptureMetadata(BaseModel):
    """ローカル記録の一覧行。本文は詳細取得まで返さない。"""

    id: int = Field(description="本文の取得に使う記録ID")
    profile_id: str = Field(description="記録専用だった送信先設定のID")
    record_key: str = Field(description="イベントの照合キー")
    topic: str = Field(description="このイベントのトピック")
    created_at: str = Field(description="保存したUTC日時（ISO 8601）")
    bytes: int = Field(description="保存された本文のUTF-8バイト数")


class CapturePage(BaseModel):
    """ローカル記録の一覧と、次のページを開くための位置。"""

    events: list[CaptureMetadata]
    next_before: int | None = Field(
        description="古い記録を読むときのbefore。最後のページではnull"
    )


class CaptureRecord(CaptureMetadata):
    """メタ情報に元の本文を添えたローカル記録。"""

    payload: str = Field(description="保存された元の本文。文字列なので、JSONとして扱う場合はデコードします")


class RetryRequest(BaseModel):
    connection_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    limit: int = Field(default=1000, ge=1, le=1000000)
    batch_size: int = Field(default=100, ge=1, le=1000)


# 復号後の実サイズ・ルート内判定はアップロード処理で別途行う。
class UploadedConnectionFile(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+){0,3}$",
    )
    content_base64: str = Field(max_length=1500000)


# 秘密値ファイルを読む分岐があり、単なる表示用関数ではない。実接続はここでは行わない。
def bootstrap_profiles(kind, store):
    """defaultが保存済みなら何も変更しない。未登録時だけ種類と環境設定から初期接続を保存する。"""
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
    """接続保存・プリセット・実行管理を組み合わせてアプリを構築する。

    構築時に保存領域を初期化するため、純粋なスキーマ取得関数ではない。
    """
    root = Path(__file__).resolve().parent
    store = ConfigStore(Path(os.environ.get("DATA_DIR", "./data")) / "settings")
    bootstrap_profiles(kind, store)

    # 入力specを変更して返す。保存済みプリセットにはseed_presets側で再適用しない。
    def initial_preset(spec):
        """初期SQL Server接続が同梱の検証DBを指す場合だけ、未指定schemaをsyntheticへ補完する。"""
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

    # 秘密値は接続オブジェクト内に保持し、処理例外はRuntime側へ伝える。
    def dispatch(spec, ctx):
        """実行時に指定リビジョンの接続を読み、taskに応じて生成か再送のアダプターを呼ぶ。"""
        profile, _ = store.get_profile(spec.connection_id, spec.connection_revision)
        (adapter.retry if spec.task == "retry" else adapter.handle)(
            spec, ctx, profile, store
        )

    runtime = Runtime(kind, dispatch, 100000000)

    # 待機期限後の強制終了やDBロールバックはこの関数では行わない。
    @asynccontextmanager
    async def lifespan(app):
        """アプリ終了時に停止イベントを立て、実行中スレッドを最大20秒待つ。"""
        yield
        runtime.stop.set()
        if runtime.thread:
            runtime.thread.join(timeout=20)

    app = FastAPI(title=title, version="0.3.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime = runtime
    app.state.config_store = store
    app.state.kind = kind

    # 秘密値を含み得るリクエスト本文や入力値をそのまま応答へ転載しない。
    # 正常応答にはブラウザー向け安全ヘッダーを付ける。本文の全受信サイズを測る処理ではない。
    credentials = management_credentials()
    install_error_handlers(app)

    @app.middleware("http")
    async def protect(request: Request, call_next):
        denied = unauthorized_management(request, credentials, False)
        if denied is not None:
            return denied
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
    install_help(app, root, False, kind, credentials)
    gate = install_operation_gate(app, kind, store, RunSpec, RetryRequest)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(root / "static/index.html")

    @app.get(
        "/healthz",
        summary='動作確認',
        tags=['動作確認・監視'],
    )
    def health():
        """アプリがHTTPに応答することを示します。接続先や下流の処理結果は別に確認します。"""
        return {"status": "ok", "service": kind, "version": "0.3.0"}

    # 未登録は404、方式不一致は422に変換し、呼出先へ無検査の接続を渡さない。
    def profile(identity, revision=None):
        """IDと任意リビジョンで接続を読み、現在のツールが許可する方式か検査して版と共に返す。"""
        try:
            value, version = store.get_profile(identity, revision)
        except KeyError:
            raise HTTPException(404, "接続プロファイルが見つかりません") from None
        if value.kind not in ALLOWED_KINDS[kind]:
            raise HTTPException(422, "このツールでは使用できない接続方式です")
        return value, version

    def resolve_stream_destination(spec, expected_revision):
        """ブラウザー指定時にだけ現行版と照合し、同じ接続情報を確定する。"""
        if expected_revision is None:
            return profile(spec.connection_id, spec.connection_revision)
        try:
            selected, current = profile(spec.connection_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(409, "接続先が変更されました。再確認してください") from None
            raise
        if current != expected_revision or spec.connection_revision != expected_revision:
            raise HTTPException(409, "接続先が変更されました。再確認してください")
        return selected, current

    # 利用者向け生成例外以外の型エラー詳細は一般化して422を返す。全行保証ではない。
    def checked(spec):
        """生成条件を代表位置で検証し、ツール違いの再送・ファイル破損指定を拒否する。"""
        if kind != "stream" and spec.task != "generate":
            raise HTTPException(422, "再送はストリームツールだけで使用できます")
        if (
            kind != "files"
            and spec.faults.enabled
            and spec.faults.artifact_mode != "none"
        ):
            raise HTTPException(422, "不正ファイルの生成設定はファイルツール専用です")
        try:
            validate_generation(spec, kind=kind)
        except GenerationError:
            raise
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(
                422,
                "生成ルールの型・範囲・日時を確認してください",
            ) from None
        return spec

    # ドライバー由来の本文には秘密値が含まれ得るので、型名だけを外部へ返す。
    def safe_call(callback, *args):
        """指定処理を呼び、HTTP例外は維持し、生成検証は422・接続処理失敗は503へ変換する。"""
        try:
            return callback(*args)
        except HTTPException:
            raise
        except GenerationError:
            raise
        except Exception as exc:
            raise HTTPException(
                503,
                f"接続先の処理に失敗しました ({type(exc).__name__})。接続情報・権限・対象の構造を確認してください。",
            ) from None

    # 保存済みdefault接続を参照するが、秘密値そのものは応答へ含めない。
    @app.get(
        "/api/info",
        summary='アプリ情報・既定値',
        tags=['動作確認・監視'],
    )
    def information():
        """このアプリに適用される設定、既定値、接続先の案内を返します。秘密情報は含みません。"""
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
            "version": "0.3.0",
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

    # HELPの登録漏れを隠して空説明へ置換せず、モデルとの整合性を維持する。
    @app.get(
        "/api/schemas",
        summary='設定スキーマを取得',
        tags=['設定・ひな型'],
    )
    def schemas():
        """実行ひな型と接続設定のJSON Schemaを返します。項目の型や候補、エディター補完に利用できます。"""
        from helptext import annotated_schemas

        return annotated_schemas(kind)

    # 対象はstore配下の既定領域か明示設定であり、成果物のlandingとは別管理する。
    def files_root():
        """接続補助ファイルの保存ディレクトリを設定から正規化し、必要なら作成して返す。"""
        path = Path(
            os.environ.get(
                "CONNECTION_FILES_DIR", str(store.root.parent / "connection-files")
            )
        ).resolve()
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    # シンボリックリンクと本文は返さず、秘密値を含み得るファイル内容を露出しない。
    @app.get(
        "/api/connection-files",
        summary='接続補助ファイルの一覧',
        tags=['接続・公開設定'],
    )
    def connection_files():
        """保存したファイルの相対名と大きさを返します。本文は返しません。"""
        root = files_root()
        return {
            "files": [
                {"name": str(p.relative_to(root)), "bytes": p.stat().st_size}
                for p in root.rglob("*")
                if p.is_file() and not p.is_symlink()
            ][:200]
        }

    # 一時名を排他的に作り同期後に置換する。既存同名ファイルの更新は許される。
    @app.post(
        "/api/connection-files",
        summary='接続補助ファイルを配置',
        tags=['接続・公開設定'],
    )
    def upload_connection_file(value: UploadedConnectionFile):
        """相対名とBase64を含むJSONを受け付けます。デコード後1MiBまで。同名は置き換え、ファイルは権限600で保存します。"""
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

    # 秘密値の除外はstore.profilesの表示用変換で行う。
    @app.get(
        "/api/connections",
        summary='接続先一覧',
        tags=['接続・公開設定'],
    )
    def connections():
        """利用できる接続先と版を返します。資格情報は値を返さず設定済みとして区別します。"""
        return {
            "connections": [
                p for p in store.profiles() if p["kind"] in ALLOWED_KINDS[kind]
            ]
        }

    # 認証情報の継承・削除・リビジョン追加はConfigStoreに集約する。
    @app.post(
        "/api/connections",
        summary='接続先を保存',
        tags=['接続・公開設定'],
    )
    def save_connection(value: ConnectionProfile):
        """指定したIDで接続情報を保存します。既存の秘密値は同じ認証設定でのみ引き継ぎます。"""
        if value.kind not in ALLOWED_KINDS[kind]:
            raise HTTPException(422, "このツールでは使用できない接続方式です")
        return store.save_profile(value)

    # 秘密値やヘッダー値をエクスポートする経路にはしない。
    @app.get(
        "/api/connections/{identity}/export",
        summary='接続先を書き出す',
        tags=['接続・公開設定'],
    )
    def export_connection(identity: str):
        """パスワードやトークン、認証ヘッダーを除外して指定IDの接続設定を返します。"""
        value, revision = profile(identity)
        result = store.public(value)
        for key in ["configured_secrets", "configured_headers"]:
            result.pop(key, None)
        return result

    # 実接続を伴い得るため、プレビューとは異なる操作である。
    @app.post(
        "/api/connections/{identity}/test",
        summary='接続先を試験',
        tags=['接続・公開設定'],
    )
    def test_connection(identity: str):
        """保存済みIDで接続先へアクセスします。接続先の種類に応じて疎通と利用可能な情報を返します。"""
        value, _ = profile(identity)
        return safe_call(adapter.test_connection, value)

    @app.get(
        "/api/presets",
        summary='ひな型一覧',
        tags=['設定・ひな型'],
    )
    def presets():
        """同梱・保存済みのひな型と内容を返します。読み取りで生成や実行は始まりません。"""
        return {"presets": store.presets()}

    # 生成条件の検証は接続先に書き込む試験を意味しない。
    @app.post(
        "/api/presets/{identity}",
        summary='ひな型を保存',
        tags=['設定・ひな型'],
    )
    def save_preset(identity: str, spec: RunSpec):
        """IDは英数字・下線・ハイフンで64文字以内です。JSONを検証し、同じIDならひな型を更新します。"""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
            raise HTTPException(
                422, "プリセットIDは英数字・ハイフン・下線で指定してください"
            )
        return store.save_preset(identity, checked(spec))

    @app.get(
        "/api/presets/{identity}/export",
        summary='指定ひな型を書き出す',
        tags=['設定・ひな型'],
        responses={404: {'description': '指定したひな型が見つかりません'}},
    )
    def export_preset(identity: str):
        """保存されたIDの設定JSONを返します。未登録のIDは404です。"""
        try:
            return store.get_preset(identity)["spec"]
        except KeyError:
            raise HTTPException(404, "プリセットが見つかりません") from None

    # 接続・書込み・送信は行わない。表示サンプルの成功を全行や下流成功と扱わない。
    @app.post(
        "/api/preview",
        summary='実行前に生成の見本を見る',
        tags=['設定・ひな型'],
    )
    def preview(spec: RunSpec, expected_revision: int | None = Header(
            default=None, alias="X-Expected-Connection-Revision", ge=1
        )):
        """入力を検証し、先頭や異常条件の境界で合成した値を records に返します。writes は false です。実行先へ出力しません。"""
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
        messages = []
        target = None
        revision = None
        if kind == "stream":
            try:
                target, revision = resolve_stream_destination(spec, expected_revision)
            except HTTPException as exc:
                # 未登録の接続先を参照する設定も、本文はローカルで確認できる。
                if exc.status_code != 404:
                    raise
        for i, row in enumerate(records):
            try:
                if kind == "stream":
                    if target:
                        check_stream_profile(spec, target.kind)
                    items = build_events(
                        spec, row, spec.start_sequence + offsets[i],
                        target.topic if target else None,
                    )
                    if target:
                        check_stream_topic(target.kind, items[0]["topic"])
                    payload = json.loads(items[0]["payload"])
                    messages.append({
                        "sequence": spec.start_sequence + offsets[i],
                        "topic": items[0]["topic"],
                        "payload": items[0]["payload"],
                        "bytes": len(items[0]["payload"].encode("utf-8")),
                        "duplicate": len(items) > 1,
                    })
                else:
                    payload = row
            except GenerationError:
                raise
            payloads.append(payload)
        return {
            "sample_sequences": [spec.start_sequence + i for i in offsets],
            "anomaly_hits": anomaly_hits,
            "warnings": anomaly_warnings(spec),
            "validated_spec": spec.model_dump(mode="json"),
            "compact_spec": {"version": spec.version, **spec.model_dump(mode="json", exclude_defaults=True)},
            "writes": False,
            "records": records,
            "json_payloads": payloads,
            **(
                {"stream_messages": messages, "connection_revision": revision}
                if kind == "stream"
                else {}
            ),
            "rows": spec.rows,
            "effective_batch_limit": batch_limit(spec, spec.batch_size, kind=kind),
            "estimated_seconds": round(
                spec.rows * (1 + spec.stream.duplicate_rate if kind == "stream" else 1)
                / spec.target_rate,
                2,
            )
            if spec.target_rate
            else None,
            "note": "プレビューでは接続・書き込み・送信しません。正常位置と異常条件の開始位置を含むサンプルを表示します。目標速度は性能保証ではありません。",
        }

    # HTTP 202は受付であり、生成や配送の完了を意味しない。
    @app.post(
        "/api/runs", status_code=202,
        summary='新しい実行を受け付ける',
        tags=['実行・出力'],
        responses={409: {'description': '実行枠または接続設定を確認してください'}},
    )
    def start(request: Request, spec: RunSpec, expected_revision: int | None = Header(
            default=None, alias="X-Expected-Connection-Revision", ge=1
        )):
        """現在の接続先の版でバックグラウンド実行を作ります。202は受付です。応答の id を run_id に指定して履歴を確認します。"""
        checked(spec)
        if kind == "stream":
            selected, revision = resolve_stream_destination(spec, expected_revision)
            safe_call(check_stream_profile, spec, selected.kind)
        else:
            _, revision = profile(spec.connection_id, spec.connection_revision)
        operation = gate.assess("/api/runs", spec, revision)
        gate.require(operation, request.headers.get(CONFIRMATION_HEADER))
        return runtime.start(spec.model_copy(update={"connection_revision": revision}))

    @app.get(
        "/api/runs",
        summary='実行履歴の一覧',
        tags=['実行・出力'],
    )
    def runs():
        """稼働中も含めた履歴を返します。この要求から新規ジョブは作りません。"""
        return {"runs": runtime.list()}

    @app.get(
        "/api/runs/{run_id}",
        summary='実行結果を取得',
        tags=['実行・出力'],
        responses={404: {'description': '指定した実行が見つかりません'}},
    )
    def run(run_id: str):
        """指定したジョブの状態、件数、出力を取得します。指定のIDが存在しない場合は404です。"""
        return runtime.get(run_id)

    @app.post(
        "/api/runs/{run_id}/stop",
        summary='実行の停止を要求',
        tags=['実行・出力'],
        responses={404: {'description': '指定した実行が見つかりません'}},
    )
    def stop(run_id: str):
        """実行は停止可能な境界で終了します。確定済みのバッチや部分出力が残る場合があります。"""
        return runtime.cancel(run_id)

    # 後者は外部I/Oを伴い得るため、単なる保存設定一覧とは区別する。
    @app.get(
        "/api/source",
        summary='出力側の状態を調べる',
        tags=['実行・出力'],
    )
    def source():
        """ストリームは配送集計、SQLとファイルは既定接続の疎通結果を返します。疎通確認は接続先へアクセスします。"""
        if kind == "stream":
            return adapter.summary()
        value, _ = profile("default")
        return safe_call(adapter.test_connection, value)

    # 秘密値やジョブ本文はメトリクスへ含めない。
    @app.get(
        "/metrics", response_class=PlainTextResponse,
        summary='Prometheus向けメトリクス',
        tags=['動作確認・監視'],
    )
    def metrics():
        """生成や実行状態のカウンターをPrometheus向けテキストで返します。"""
        with runtime.connect() as conn:
            rows = conn.execute(
                "SELECT status,count(*) FROM jobs GROUP BY status"
            ).fetchall()
        return "# TYPE source_jobs gauge\n" + "".join(
            f'source_jobs{{service="{kind}",status="{r[0]}"}} {r[1]}\n' for r in rows
        )

    if kind == "sql":

        # 接続プロファイルを解決し、失敗の詳細はsafe_callで一般化する。
        @app.post(
            "/api/table/prepare",
            summary='未作成テーブルを作る',
            tags=['実行・出力'],
        )
        def prepare(spec: RunSpec):
            """指定先にテーブルが存在しない場合にDDLを実行します。書き込むDB・スキーマ・テーブルを確認して指定します。"""
            checked(spec)
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.prepare_table, value, spec)

        @app.post(
            "/api/table/inspect",
            summary='既存テーブルの列を取得',
            tags=['実行・出力'],
        )
        def inspect_table(spec: RunSpec):
            """接続先のテーブルから列や主キーを調べます。テーブルの作成や行の書き込みは行いません。"""
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.inspect_table, value, spec)

        @app.post(
            "/api/table/ddl",
            summary='テーブル作成SQLを表示',
            tags=['実行・出力'],
        )
        def ddl(spec: RunSpec):
            """対象接続のSQL方言に合うCREATE TABLE文を返します。DDLの適用はテーブル作成操作で行います。"""
            value, _ = profile(spec.connection_id, spec.connection_revision)
            return safe_call(adapter.ddl, value, spec)

    if kind == "files":

        # リモート成果物の読出しを伴い得るが、再生成はしない。
        @app.get(
            "/api/runs/{run_id}/image",
            summary='生成済み画像を取得',
            tags=['実行・出力'],
            response_class=Response,
            responses={200: {'description': '生成済み画像を取得', 'content': {'image/png': {'schema': {'type': 'string', 'format': 'binary'}}, 'image/jpeg': {'schema': {'type': 'string', 'format': 'binary'}}}}, 404: {'description': '指定した画像が見つかりません'}},
        )
        def image(run_id: str):
            """保存済みの成果物を読みます。保存方式に応じてPNGまたはJPEGを返します。新規生成はしません。"""
            return safe_call(adapter.artifact, runtime.get(run_id), store)

    if kind == "stream":

        @app.get(
            "/api/outbox/capture",
            tags=["ローカル記録"],
            summary="ローカル記録の一覧",
            response_model=CapturePage,
        )
        def captured_events(
            limit: int = Query(default=25, ge=1, le=100, description="表示する上限件数"),
            before: int | None = Query(default=None, ge=1, le=2**63 - 1, description="前の応答の next_before"),
        ):
            """ローカル記録のID・時刻・トピック・サイズを新しい順に返す。"""
            rows = list(adapter.capture_rows(store, limit + 1, before=before))
            return {
                "events": rows[:limit],
                "next_before": rows[limit - 1]["id"] if len(rows) > limit else None,
            }

        @app.get(
            "/api/outbox/capture/download",
            tags=["ローカル記録"],
            summary="ローカル記録をJSONLでダウンロード",
            response_class=StreamingResponse,
            responses={200: {"content": {"application/x-ndjson": {"schema": {"type": "string"}}}}},
        )
        def download_captured_events(
            limit: int = Query(default=25, ge=1, le=100, description="出力する上限件数"),
            before: int | None = Query(default=None, ge=1, le=2**63 - 1, description="前の一覧応答の next_before"),
        ):
            """1行1イベントで書き出す。payloadには保存した本文を文字列で含める。"""
            rows = adapter.capture_rows(store, limit, before=before, include_payload=True)
            # Fetch once before sending headers so storage errors can still return an HTTP error.
            first = next(rows, None)

            def json_lines():
                try:
                    if first is not None:
                        yield json.dumps(first, ensure_ascii=False) + "\n"
                    for row in rows:
                        yield json.dumps(row, ensure_ascii=False) + "\n"
                finally:
                    rows.close()

            return StreamingResponse(
                json_lines(),
                media_type="application/x-ndjson",
                headers={"Content-Disposition": 'attachment; filename="stream-capture.jsonl"'},
            )

        @app.get(
            "/api/outbox/capture/{row_id}",
            tags=["ローカル記録"],
            summary="ローカル記録の本文",
            response_model=CaptureRecord,
            responses={404: {"description": "ローカル記録が見つからない"}},
        )
        def captured_event(row_id: int):
            """指定したローカル記録1件に元の本文を添えて返す。"""
            if not 1 <= row_id <= 2**63 - 1:
                raise HTTPException(422, "記録IDを確認してください")
            rows = list(adapter.capture_rows(store, 1, row_id=row_id, include_payload=True))
            if not rows:
                raise HTTPException(404, "ローカル記録が見つかりません")
            return rows[0]

        @app.get(
            "/api/outbox",
            summary='配送の集計を取得',
            tags=['実行・出力'],
        )
        def outbox():
            """送信待ち・配送済みなどの件数を返します。配送や再送は開始しません。"""
            return adapter.summary()

        # 未配送データの抽出と宛先一致確認はアダプター側で行う。
        @app.post(
            "/api/outbox/retry", status_code=202,
            summary='未配送イベントの再送を受け付ける',
            tags=['実行・出力'],
        )
        def retry(request: Request, value: RetryRequest):
            """対象の接続と版を照合し、指定上限の再送ジョブを作ります。202の後に実行結果を確認します。"""
            _, revision = profile(value.connection_id)
            operation = gate.assess("/api/outbox/retry", value, revision)
            gate.require(operation, request.headers.get(CONFIRMATION_HEADER))
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
