# モジュール読解: Pydanticによるv2入力契約。識別子・範囲・方式の組合せを検証し、JSON Schemaの起点になる。
# 検証モデルと接続試験は分離する。クラス説明は公開schemaを変えないようコメントで記す。
"""Versioned, domain-independent connection and generation contracts."""

from __future__ import annotations

import math
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]{0,62}$"
PROFILE_ID = r"^[A-Za-z0-9_-]{1,64}$"
SECRET_FIELDS = (
    "password",
    "access_key",
    "secret_key",
    "session_token",
    "bearer_token",
    "api_key",
    "connection_string",
    "db_access_token",
    "wallet_password",
    "tls_key_password",
    "ssh_private_key",
    "ssh_key_password",
    "nats_token",
)
DATABASE_KINDS = {"sqlserver", "oracle", "postgresql", "mysql", "mariadb", "sqlite"}
ALLOWED_KINDS = {
    "sql": DATABASE_KINDS,
    "files": {"local", "s3", "smb", "nfs", "ftp", "sftp"},
    "stream": {"mqtt", "http", "capture", "kafka", "amqp", "nats", "websocket"},
}


# 未知の設定キーと非有限数を共通で拒否する。モデルの説明は公開schemaを変えないコメントとする。
# 読解 Model: 設定モデルの共通基底。未知キーを拒否し、非有限数を許可しない。
# 入力契約に影響する設定なので説明のためにmodel_configを緩めない。
class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# 接続方式と認証情報を保持する入力契約。保存・表示時の秘密値処理はstorage側が担う。
# 読解 ConnectionProfile: 方式・宛先・認証・TLSなどの接続契約。秘密値はSecretStrで受ける。
# 入力検証と疎通確認は別段階であり、モデル生成だけで外部接続しない。
class ConnectionProfile(Model):
    id: str = Field(pattern=PROFILE_ID)
    name: str = Field(min_length=1, max_length=120)
    kind: Literal[
        "sqlserver",
        "oracle",
        "postgresql",
        "mysql",
        "mariadb",
        "sqlite",
        "local",
        "s3",
        "mqtt",
        "http",
        "capture",
        "smb",
        "nfs",
        "ftp",
        "sftp",
        "kafka",
        "amqp",
        "nats",
        "websocket",
    ]
    driver: Literal[
        "auto",
        "pymssql",
        "pyodbc",
        "oracledb_thin",
        "oracledb_thick",
        "psycopg",
        "pymysql",
    ] = "auto"
    database_auth: Literal[
        "password",
        "windows_password",
        "kerberos",
        "client_certificate",
        "external",
        "entra_service_principal",
        "entra_managed_identity",
        "access_token",
    ] = "password"
    connection_method: Literal["host", "dsn", "service", "unix_socket", "raw"] = "host"
    domain: str = Field(default="", max_length=255)
    dsn: str = Field(default="", max_length=255)
    connection_string: SecretStr | None = None
    db_access_token: SecretStr | None = None
    odbc_driver: str = Field(default="ODBC Driver 18 for SQL Server", max_length=128)
    unix_socket: str = Field(default="", max_length=1024)
    config_dir: str = Field(default="", max_length=1024)
    wallet_location: str = Field(default="", max_length=1024)
    wallet_password: SecretStr | None = None
    tls_ca_file: str = Field(default="", max_length=1024)
    tls_cert_file: str = Field(default="", max_length=1024)
    tls_key_file: str = Field(default="", max_length=1024)
    tls_key_password: SecretStr | None = None
    driver_options: dict[str, str | int | bool] = Field(
        default_factory=dict, max_length=30
    )
    share: str = Field(default="", max_length=255)
    file_auth: Literal["password", "kerberos", "ssh_key", "anonymous"] = "password"
    ssh_private_key: SecretStr | None = None
    ssh_key_password: SecretStr | None = None
    ssh_key_file: str = Field(default="", max_length=1024)
    ssh_known_hosts: str = Field(default="", max_length=1024)
    ssh_host_key_policy: Literal["known_hosts", "sha256", "accept_any"] = "known_hosts"
    ssh_host_key_sha256: str = Field(default="", max_length=128)
    ftp_tls_mode: Literal["explicit", "implicit"] = "explicit"
    ftp_passive: bool = True
    ftp_encoding: str = Field(default="utf-8", max_length=64)
    smb_encrypt: bool = True
    nfs_expected_source: str = Field(default="", max_length=1024)
    kafka_sasl_mechanism: Literal["none", "PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"] = (
        "none"
    )
    bootstrap_servers: str = Field(default="", max_length=2048)
    amqp_virtual_host: str = Field(default="/", max_length=255)
    amqp_exchange: str = Field(default="", max_length=255)
    amqp_declare_queue: bool = False
    nats_token: SecretStr | None = None
    nats_credentials_file: str = Field(default="", max_length=1024)
    nats_jetstream: bool = False
    websocket_subprotocols: list[str] = Field(default_factory=list, max_length=20)
    websocket_ack: Literal["none", "text", "json"] = "none"
    host: str = Field(default="", max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=255)
    password: SecretStr | None = None
    service_name: str = Field(default="", max_length=255)
    sid: str = Field(default="", max_length=255)
    ssl_mode: Literal["off", "require", "verify"] = "require"
    directory: str = Field(default="", max_length=1024)
    sqlite_path: str = Field(default="", max_length=1024)
    endpoint_url: str = Field(default="", max_length=2048)
    bucket: str = Field(default="", max_length=255)
    prefix: str = Field(default="", max_length=1024)
    region: str = Field(default="auto", max_length=128)
    access_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    session_token: SecretStr | None = None
    url: str = Field(default="", max_length=2048)
    auth_mode: Literal["none", "basic", "bearer", "api_key"] = "none"
    bearer_token: SecretStr | None = None
    api_key: SecretStr | None = None
    api_key_header: str = Field(default="X-API-Key", pattern=r"^[A-Za-z0-9-]{1,64}$")
    topic: str = Field(default="data/events", min_length=1, max_length=512)
    qos: int = Field(default=1, ge=0, le=2)
    mqtt_version: Literal["3.1.1", "5"] = "3.1.1"
    client_id: str = Field(default="", max_length=128)
    keepalive: int = Field(default=30, ge=5, le=3600)
    retain: bool = False
    http_method: Literal["POST", "PUT", "PATCH"] = "POST"
    content_type: str = Field(default="", max_length=128, pattern=r"^[^\r\n]*$")
    headers: dict[str, SecretStr | None] = Field(default_factory=dict, max_length=30)
    delivery_attempts: int = Field(default=1, ge=1, le=10)
    retry_backoff_ms: int = Field(default=500, ge=0, le=60000)
    timeout_seconds: int = Field(default=15, ge=1, le=120)
    clear_secrets: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def valid_destination(self):
        """接続方式に必要な項目と組合せを検査する。実接続の可否は確認しない。"""
        if (
            (
                self.kind in DATABASE_KINDS - {"sqlite"}
                and self.connection_method == "host"
            )
            or self.kind in {"mqtt", "smb", "ftp", "sftp", "amqp", "nats"}
            or (self.kind == "kafka" and not self.bootstrap_servers)
        ):
            if not self.host or any(c in self.host for c in "/@?# \r\n"):
                raise ValueError("ホスト名またはIPアドレスを指定してください")
        if (
            self.kind == "oracle"
            and self.connection_method == "host"
            and not (self.service_name or self.sid)
        ):
            raise ValueError("Oracleのサービス名またはSIDが必要です")
        if self.service_name and self.sid:
            raise ValueError("Oracleのサービス名とSIDはどちらか一方を指定してください")
        if (
            self.kind in {"sqlserver", "postgresql", "mysql", "mariadb"}
            and not self.database
        ):
            raise ValueError("データベース名が必要です")
        if self.kind == "sqlite" and not self.sqlite_path:
            raise ValueError("SQLiteファイルを指定してください")
        if self.kind in {"local", "nfs"} and not self.directory:
            raise ValueError("出力ディレクトリが必要です")
        if self.kind == "s3" and not self.bucket:
            raise ValueError("バケット名が必要です")
        for value, required in [
            (self.url if self.kind == "http" else "", self.kind == "http"),
            (self.endpoint_url if self.kind == "s3" else "", False),
        ]:
            if required or value:
                parsed = urlsplit(value)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.fragment
                ):
                    raise ValueError("認証情報を含まないHTTP(S) URLを指定してください")
        if self.kind == "mqtt" and (
            "\x00" in self.topic or any(c in self.topic for c in "#\n\r+")
        ):
            raise ValueError("送信用トピックにワイルドカードは使用できません")
        if any(
            name not in SECRET_FIELDS and name != "nats_token"
            for name in self.clear_secrets
        ):
            raise ValueError("認証情報の削除対象を確認してください")
        if self.kind in DATABASE_KINDS - {"sqlite"}:
            auth = {
                "sqlserver": {
                    "password",
                    "windows_password",
                    "kerberos",
                    "entra_service_principal",
                    "entra_managed_identity",
                    "access_token",
                },
                "oracle": {"password", "external", "access_token"},
                "postgresql": {
                    "password",
                    "kerberos",
                    "client_certificate",
                    "external",
                    "access_token",
                },
                "mysql": {"password", "client_certificate", "external"},
                "mariadb": {"password", "client_certificate", "external"},
            }
            methods = {
                "sqlserver": {"host", "dsn", "raw"},
                "oracle": {"host", "dsn", "raw"},
                "postgresql": {"host", "service", "unix_socket", "raw"},
                "mysql": {"host", "unix_socket", "raw"},
                "mariadb": {"host", "unix_socket", "raw"},
            }
            if (
                self.database_auth not in auth[self.kind]
                or self.connection_method not in methods[self.kind]
            ):
                raise ValueError(
                    "選択したDBに対応する認証方式・接続方法を選んでください"
                )
            if self.connection_method in {"dsn", "service"} and not self.dsn:
                raise ValueError("DSN・TNSエイリアスまたはサービス名を指定してください")
            if self.connection_method == "unix_socket" and not self.unix_socket:
                raise ValueError("Unixソケットのパスを指定してください")
        if self.kind == "smb" and not self.share:
            raise ValueError("SMB共有名を指定してください")
        if self.kind == "websocket":
            parsed = urlsplit(self.url)
            if (
                parsed.scheme not in {"ws", "wss"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError(
                    "認証情報を含まないws://またはwss:// URLを指定してください"
                )
        import re

        for name in self.headers:
            if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name) or name.lower() in {
                "authorization",
                "cookie",
                "proxy-authorization",
                "host",
                "content-length",
            }:
                raise ValueError(
                    "このHTTPヘッダーは認証設定または本文設定で指定してください"
                )
        return self


# 読解 Condition: 先行する項目の値を比較し、成立時に置換する条件。任意の式やコードは受け付けない。
class Condition(Model):
    field: str = Field(pattern=IDENTIFIER)
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in"] = "eq"
    value: Any = None
    then_value: Any = None


# 定義順に評価する一項目の生成規則。参照先は先行する項目である必要がある。
# 読解 FieldRule: 一項目の型・生成方法・参照・条件・NULL率をまとめる。
# 先行項目を参照する順序と、型変換時の範囲検査を生成エンジンと共有する。
class FieldRule(Model):
    name: str = Field(pattern=IDENTIFIER)
    data_type: Literal[
        "string", "integer", "number", "decimal", "boolean", "datetime", "json"
    ] = "string"
    generator: Literal[
        "record_id",
        "uuid",
        "sequence",
        "integer",
        "uniform",
        "normal",
        "choice",
        "boolean",
        "constant",
        "template",
        "timestamp",
        "reference",
        "sum",
        "difference",
        "product",
        "ratio",
    ] = "constant"
    primary_key: bool = False
    length: int = Field(default=255, ge=1, le=4000)
    precision: int = Field(default=18, ge=1, le=38)
    scale: int = Field(default=3, ge=0, le=18)
    minimum: int | float | str = 0
    maximum: int | float | str = 100
    mean: int | float | str = 50
    stddev: int | float | str = 5
    start: int | float | str = 0
    step: int | float | str = 1
    group_size: int | str = 1
    modulo: int | str = 0
    probability: float | str = 0.5
    choices: list[Any] | str = Field(default_factory=list)
    weights: list[float] = Field(default_factory=list)
    value: Any = None
    template: str = Field(default="{sequence}", max_length=2048)
    sources: list[str] = Field(default_factory=list, max_length=32)
    null_probability: float = Field(default=0, ge=0, le=1)
    condition: Condition | None = None

    @model_validator(mode="after")
    def valid_rule(self):
        """精度・主キーのNULL率・派生値の参照元について矛盾を拒否する。"""
        if self.scale > self.precision:
            raise ValueError("小数桁数は精度以下にしてください")
        if self.primary_key and self.null_probability:
            raise ValueError("主キーにNULL率は指定できません")
        if (
            self.generator in {"reference", "sum", "difference", "product", "ratio"}
            and not self.sources
        ):
            raise ValueError("参照元の項目が必要です")
        return self


# 読解 SqlOptions: SQL出力のschema・表・操作種別を制限する入力。自由なSQL本文は受け付けない。
class SqlOptions(Model):
    schema_name: str = Field(default="", pattern=r"^$|" + IDENTIFIER)
    table: str = Field(default="sample_records", pattern=IDENTIFIER)
    operation: Literal["insert", "upsert", "update", "delete"] = "upsert"


# 読解 ImageOptions: 疑似画像の寸法・模様・色・欠陥率を定義する。実画像の読込み指定ではない。
class ImageOptions(Model):
    width: int = Field(default=320, ge=32, le=4096)
    height: int = Field(default=240, ge=32, le=4096)
    format: Literal["png", "jpeg"] = "png"
    pattern: Literal["grid", "gradient", "dots"] = "grid"
    noise: int = Field(default=0, ge=0, le=64)
    defect_probability: float = Field(default=0.05, ge=0, le=1)
    every: int = Field(default=1, ge=1, le=1000000)
    quality: int = Field(default=90, ge=10, le=100)
    background: str = Field(default="#182a3a", pattern=r"^#[0-9A-Fa-f]{6}$")
    foreground: str = Field(default="#55a69b", pattern=r"^#[0-9A-Fa-f]{6}$")
    defect_color: str = Field(default="#ef463c", pattern=r"^#[0-9A-Fa-f]{6}$")


# 読解 FileOptions: 出力形式・分割・命名・符号化・完了通知の設定。
# 各形式で使わない項目も共通契約に保持し、書出し処理側で方式別に使う。
class FileOptions(Model):
    formats: list[Literal["json", "csv", "image"]] = Field(
        # コールバック: モデル生成ごとに新しい形式リストを返し、可変値を別実行と共有しない。
        default_factory=lambda: ["json", "csv", "image"], min_length=1, max_length=3
    )
    records_per_file: int = Field(default=100, ge=1, le=10000)
    path_template: str = Field(default="{run_key}/{job_id}", max_length=512)
    filename_template: str = Field(
        default="{sequence:010d}-{record_id}", max_length=256
    )
    json_mode: Literal["array", "object", "jsonl"] = "array"
    json_pretty: bool = False
    json_template: Any = None
    compression: Literal["none", "gzip"] = "none"
    csv_delimiter: str = Field(default=",", min_length=1, max_length=1)
    csv_quotechar: str = Field(default='"', min_length=1, max_length=1)
    csv_quoting: Literal["minimal", "all", "nonnumeric"] = "minimal"
    csv_header: bool = True
    csv_null_value: str = Field(default="", max_length=255)
    csv_newline: Literal["LF", "CRLF"] = "LF"
    csv_encoding: Literal["utf-8", "utf-8-sig"] = "utf-8-sig"
    write_sidecars: bool = True
    write_manifest: bool = True
    image: ImageOptions = Field(default_factory=ImageOptions)


# 読解 StreamOptions: 本文テンプレート・メタ情報・配送先テンプレートと再試行上書き条件を保持する。
# 任意の接続先URLを生成行から変更する設定ではない。
class StreamOptions(Model):
    envelope: bool = True
    metadata_key: str = Field(default="_source", pattern=IDENTIFIER)
    http_body: Literal["array", "single", "ndjson"] = "array"
    topic_template: str = Field(default="", max_length=512)
    payload_template: Any = None
    message_size_bytes: int = Field(default=0, ge=0, le=65536)
    duplicate_rate: float = Field(default=0, ge=0, le=1)
    delivery_attempts: int | None = Field(default=None, ge=1, le=10)
    retry_backoff_ms: int | None = Field(default=None, ge=0, le=60000)


# 読解 default_fields: 新しいRunSpec用に標準の識別子・通番・値・状態・日時の項目を返す。
# 呼出しごとに新しいFieldRule群を作り、実行間で可変モデルを共有しない。
def default_fields():
    return [
        FieldRule(name="id", generator="record_id", primary_key=True, length=64),
        FieldRule(name="sequence_no", data_type="integer", generator="sequence"),
        FieldRule(
            name="entity_no",
            data_type="integer",
            generator="integer",
            minimum=1,
            maximum="$entity_count",
        ),
        FieldRule(
            name="entity_id",
            generator="template",
            template="ENTITY-{entity_no:05d}",
            length=64,
        ),
        FieldRule(name="status", generator="choice", choices="$statuses", length=32),
        FieldRule(
            name="value",
            data_type="number",
            generator="normal",
            mean="$value_mean",
            stddev="$value_stddev",
        ),
        FieldRule(
            name="event_time",
            data_type="datetime",
            generator="timestamp",
            start="$start_time",
            group_size="$entity_count",
        ),
    ]


# 読解 Predicate: 異常適用の条件となる項目・比較方法・値を保持する。比較対象は生成済みの行である。
class Predicate(Model):
    field: str = Field(pattern=IDENTIFIER)
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in"] = "eq"
    value: Any = None


# 通常の型検査を迂回する異常値は、bypass_validationの明示指定に限る。
# 読解 AnomalyRule: 適用位置・間隔・確率・条件と値の変形方法を宣言する。
# 検証迂回を明示した場合だけ、通常の型制約に反する試験データを許す。
class AnomalyRule(Model):
    name: str = Field(default="異常注入", min_length=1, max_length=120)
    enabled: bool = True
    field: str = Field(pattern=IDENTIFIER)
    operation: Literal[
        "set",
        "add",
        "multiply",
        "ramp",
        "freeze",
        "null",
        "copy_from",
        "timestamp_shift",
        "omit",
    ] = "set"
    value: Any = None
    from_row: int = Field(default=0, ge=0, le=100000000)
    to_row: int | None = Field(default=None, ge=0, le=100000000)
    every: int = Field(default=1, ge=1, le=100000000)
    probability: float = Field(default=1, ge=0, le=1)
    when: Predicate | None = None
    bypass_validation: bool = False

    @model_validator(mode="after")
    def valid_range(self):
        """異常適用の終了位置が開始位置より前になる指定を拒否する。"""
        if self.to_row is not None and self.to_row < self.from_row:
            raise ValueError("異常終了位置は開始位置以上にしてください")
        return self


# データの異常値とは別に、処理段階での停止・遅延や成果物破損を試験する設定。
# 読解 FaultOptions: 処理段階での停止・遅延と成果物破損を指定する。
# 件数・頻度・上限で制限し、実行時のenabled判定なしには適用しない。
class FaultOptions(Model):
    enabled: bool = False
    stage: Literal["before_batch", "after_write"] = "before_batch"
    action: Literal["none", "fail", "delay"] = "none"
    from_batch: int = Field(default=1, ge=1, le=100000000)
    every_batches: int = Field(default=1, ge=1, le=100000000)
    max_occurrences: int = Field(default=1, ge=0, le=1000000)
    delay_ms: int = Field(default=1000, ge=0, le=60000)
    artifact_mode: Literal[
        "none",
        "truncate_json",
        "invalid_json_utf8",
        "csv_header_mismatch",
        "truncate_image",
        "wrong_image_extension",
        "manifest_checksum_mismatch",
    ] = "none"


# 生成と再送に共通のv2入力契約。接続リビジョンを指定すれば保存済み履歴を参照する。
# 読解 RunSpec: 生成または再送の一実行を表すv2契約。件数・負荷・出力容量と各出力方式の設定を持つ。
# 接続情報そのものではなくIDと任意リビジョンを参照し、モデル検証は外部I/Oを行わない。
class RunSpec(Model):
    version: Literal[2] = 2
    name: str = Field(default="カスタムデータ", min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    connection_id: str = Field(default="default", pattern=PROFILE_ID)
    connection_revision: int | None = Field(default=None, ge=1)
    run_key: str = Field(default="trial-001", pattern=PROFILE_ID)
    seed: int = Field(default=42, ge=0, le=2147483647)
    rows: int = Field(default=30, ge=1, le=100000000)
    target_rate: int = Field(default=10, ge=0, le=1000000)
    batch_size: int = Field(default=1000, ge=1, le=10000)
    start_sequence: int = Field(default=0, ge=0, le=1000000000)
    max_duration_seconds: int = Field(default=3600, ge=1, le=86400)
    max_output_mb: int = Field(default=1024, ge=1, le=1048576)
    initial_delay_seconds: float = Field(default=0, ge=0, le=3600)
    jitter_ms: int = Field(default=0, ge=0, le=60000)
    burst_rows: int = Field(default=0, ge=0, le=1000000)
    burst_pause_ms: int = Field(default=0, ge=0, le=3600000)
    parameters: dict[str, Any] = Field(
        # コールバック: モデル生成ごとに新しい既定パラメーター辞書を返し、可変値を別実行と共有しない。
        default_factory=lambda: {
            "entity_count": 10,
            "statuses": ["ok", "warning", "stopped"],
            "value_mean": 50,
            "value_stddev": 5,
            "start_time": "2026-11-13T00:00:00+09:00",
        },
        max_length=100,
    )
    fields: list[FieldRule] = Field(
        default_factory=default_fields, min_length=1, max_length=100
    )
    sql: SqlOptions = Field(default_factory=SqlOptions)
    files: FileOptions = Field(default_factory=FileOptions)
    stream: StreamOptions = Field(default_factory=StreamOptions)
    anomalies: list[AnomalyRule] = Field(default_factory=list, max_length=64)
    faults: FaultOptions = Field(default_factory=FaultOptions)
    task: Literal["generate", "retry"] = "generate"

    @property
    def cycles(self):
        """既存の呼出側に対して、生成件数をcycles名でも提供する。"""
        return self.rows

    @model_validator(mode="after")
    def valid_dataset(self):
        """項目名・メタ情報名の衝突と非有限パラメーターを拒否する。"""
        names = [f.name.casefold() for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("項目名は重複できません")
        if self.stream.envelope and self.stream.metadata_key in {
            f.name for f in self.fields
        }:
            raise ValueError("ストリームのメタデータ名と生成項目名が重複しています")
        for value in self.parameters.values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("パラメーターには有限の数を指定してください")
        return self
