# 公開用表現と内部の秘密値を分け、接続先を変えた際の秘密値継承を制限する。
"""Persistent encrypted connection profiles and credential-free JSON presets."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from config import ConnectionProfile, RunSpec, SECRET_FIELDS


def credential_scope(profile):
    """接続先変更時に秘密値を引き継いでよいかを比較する属性群を返す。"""
    return tuple(
        getattr(profile, k)
        for k in (
            "kind",
            "host",
            "port",
            "database",
            "username",
            "service_name",
            "sid",
            "endpoint_url",
            "bucket",
            "url",
            "database_auth",
            "file_auth",
            "driver",
            "connection_method",
            "domain",
            "dsn",
            "unix_socket",
            "share",
        )
    )


class ConfigStore:
    """暗号化した接続履歴と、生成条件のプリセットをSQLiteへ保存する。"""
    def __init__(self, root):
        """保存領域と暗号鍵を準備する。既存DBの鍵欠落時は再発行せず停止する。"""
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / "config-v2.sqlite3"
        key_path = Path(
            os.environ.get("PROFILE_KEY_FILE", str(self.root / "connection-v2.key"))
        )
        if not key_path.exists():
            if self.db.exists():
                raise RuntimeError(
                    "接続設定の暗号鍵がありません。バックアップから復元してください"
                )
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(Fernet.generate_key())
        self.fernet = Fernet(key_path.read_bytes().strip())
        self.lock = threading.RLock()
        with self.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,encrypted BLOB NOT NULL,updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS profile_versions(id TEXT NOT NULL,revision INTEGER NOT NULL,encrypted BLOB NOT NULL,PRIMARY KEY(id,revision))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS presets(id TEXT PRIMARY KEY,spec TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )
        self.db.chmod(0o600)

    @contextmanager
    def connect(self):
        """トランザクションを管理し、成功・失敗のどちらでも接続を閉じる。"""
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get_profile(self, identity, revision=None):
        """最新または指定リビジョンを復号して返す。未登録ならKeyErrorにする。"""
        with self.connect() as conn:
            if revision is None:
                row = conn.execute(
                    "SELECT revision,encrypted FROM profiles WHERE id=?", (identity,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT revision,encrypted FROM profile_versions WHERE id=? AND revision=?",
                    (identity, revision),
                ).fetchone()
        if row is None:
            raise KeyError(identity)
        data = json.loads(self.fernet.decrypt(row["encrypted"]))
        return ConnectionProfile.model_validate(data), row["revision"]

    def profile_versions_of_kind(self, kind):
        """接続方式が一致する保存済みの版を返す。変更前の宛先も識別できる。"""
        with self.connect() as conn:
            for row in conn.execute("SELECT encrypted FROM profile_versions"):
                data = json.loads(self.fernet.decrypt(row["encrypted"]))
                if data.get("kind") == kind:
                    yield ConnectionProfile.model_validate(data)

    @staticmethod
    def public(profile, revision=None):
        """秘密値を除いた表示用情報を返し、設定の有無だけを別項目で示す。"""
        data = profile.model_dump(
            mode="json", exclude=set(SECRET_FIELDS) | {"clear_secrets", "headers"}
        )
        data["configured_secrets"] = [
            name for name in SECRET_FIELDS if getattr(profile, name)
        ]
        data["headers"] = {name: None for name in profile.headers}
        data["configured_headers"] = [
            name for name, value in profile.headers.items() if value
        ]
        if revision is not None:
            data["revision"] = revision
        return data

    def profiles(self):
        """名前順の接続一覧を、秘密値を含まない形式で返す。"""
        with self.connect() as conn:
            identities = [
                row[0]
                for row in conn.execute("SELECT id FROM profiles ORDER BY name,id")
            ]
        return [self.public(*self.get_profile(identity)) for identity in identities]

    def save_profile(self, profile):
        """接続を暗号化して履歴へ追記し、公開可能な表示用情報を返す。

        省略した秘密値を継承するのは接続スコープが同じ場合だけ。
        明示した削除指定は継承より優先し、旧リビジョンは保持する。
        """
        with self.lock:
            try:
                old, previous = self.get_profile(profile.id)
            except KeyError:
                old, previous = None, 0
            same_scope = old is not None and credential_scope(old) == credential_scope(
                profile
            )
            if (
                profile.connection_string
                and old
                and profile.connection_string != old.connection_string
            ):
                same_scope = False
            data = profile.model_dump(
                mode="json", exclude=set(SECRET_FIELDS) | {"headers"}
            )
            for name in SECRET_FIELDS:
                value = getattr(profile, name)
                if name in profile.clear_secrets:
                    value = None
                elif value is None and same_scope:
                    value = getattr(old, name)
                data[name] = value.get_secret_value() if value else None
            data["clear_secrets"] = []
            headers = {}
            for name, value in profile.headers.items():
                if value is None and same_scope:
                    value = old.headers.get(name)
                if value:
                    headers[name] = value.get_secret_value()
            data["headers"] = headers
            private = ConnectionProfile.model_validate(data)
            encrypted = self.fernet.encrypt(
                json.dumps(data, ensure_ascii=False).encode()
            )
            revision = previous + 1
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO profiles VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,name=excluded.name,kind=excluded.kind,encrypted=excluded.encrypted,updated_at=excluded.updated_at",
                    (
                        profile.id,
                        revision,
                        profile.name,
                        profile.kind,
                        encrypted,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute(
                    "INSERT INTO profile_versions VALUES(?,?,?)",
                    (profile.id, revision, encrypted),
                )
            return self.public(private, revision)

    def save_preset(self, identity, spec):
        """検証済みの生成条件を指定IDで保存する。既存IDは更新する。"""
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO presets VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET spec=excluded.spec,updated_at=excluded.updated_at",
                (
                    identity,
                    spec.model_dump_json(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {"id": identity, "name": spec.name, "spec": spec.model_dump(mode="json")}

    def get_preset(self, identity):
        """保存済みJSONを現行モデルで再検証して返す。未登録ならKeyErrorにする。"""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT spec FROM presets WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise KeyError(identity)
        spec = RunSpec.model_validate_json(row[0])
        return {"id": identity, "name": spec.name, "spec": spec.model_dump(mode="json")}

    def presets(self):
        """更新日時とIDの順に、保存済みプリセットを返す。"""
        with self.connect() as conn:
            identities = [
                row[0]
                for row in conn.execute("SELECT id FROM presets ORDER BY updated_at,id")
            ]
        return [self.get_preset(identity) for identity in identities]

    def seed_presets(self, directory, transform=None):
        """未登録IDだけを同梱JSONから補う。既存の利用者設定は上書きしない。"""
        for path in sorted(Path(directory).glob("*.json")):
            try:
                self.get_preset(path.stem)
            except KeyError:
                spec = RunSpec.model_validate_json(path.read_text())
                self.save_preset(path.stem, transform(spec) if transform else spec)
