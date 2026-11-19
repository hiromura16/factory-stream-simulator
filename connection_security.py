# モジュール読解: 接続用の証明書・鍵・設定ファイルの参照範囲とTLS構築を共通化する。
"""Bounded certificate/key/config paths and shared TLS construction."""

import os
import ssl
from pathlib import Path
from generation import GenerationError


# 読解 secret: 指定属性の秘密値を接続用に取り出す。未設定時は空文字とし、結果は表示用途に使わない。
def secret(p, name):
    value = getattr(p, name)
    return value.get_secret_value() if value else ""


# 読解 connection_file: 相対指定を接続ファイル領域の下で解決し、実体が領域外または指定のファイル種別と異なると拒否する。
def connection_file(value, *, directory=False):
    root = Path(
        os.environ.get(
            "CONNECTION_FILES_DIR",
            str(Path(os.environ.get("DATA_DIR", "./data")) / "connection-files"),
        )
    ).resolve()
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root) or not (
        path.is_dir() if directory else path.is_file()
    ):
        raise GenerationError(
            "証明書・鍵・設定ファイルはconnection-files領域に配置し、そのパスを指定してください"
        )
    return str(path)


# 読解 tls_context: 既定のTLS設定に必要なら専用CAとクライアント証明書を読み込む。検証モード以外の挙動を区別し、証明書だけで鍵がない設定は拒否する。
def tls_context(p):
    context = ssl.create_default_context(
        cafile=connection_file(p.tls_ca_file) if p.tls_ca_file else None
    )
    if p.ssl_mode != "verify":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    if p.tls_cert_file:
        if not p.tls_key_file:
            raise GenerationError("クライアント証明書と秘密鍵を両方指定してください")
        context.load_cert_chain(
            connection_file(p.tls_cert_file),
            connection_file(p.tls_key_file),
            secret(p, "tls_key_password") or None,
        )
    return context
