"""アプリ内ヘルプ、OpenAPI、管理認証と利用者向けHTTPエラーを提供する。"""

import binascii
import json
import logging
import os
from base64 import b64decode
from hmac import compare_digest
from html import escape
from pathlib import Path

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from starlette.routing import get_route_path

from config import ConfigurationError
from generation import GenerationError
from operation_confirmation import CONFIRMATION_HEADER, POLICY

SOURCE_SECURITY = [{}, {"SourceBasic": []}, {"SourceBearer": []}, {"SourceApiKey": []}]
SOURCE_SCHEMES = {
    "SourceBasic": {
        "type": "http",
        "scheme": "basic",
        "description": "取得用プロファイルをBasicに設定した場合。",
    },
    "SourceBearer": {
        "type": "http",
        "scheme": "bearer",
        "description": "取得用プロファイルをBearerに設定した場合。",
    },
    "SourceApiKey": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "取得用プロファイルをAPIキーに設定した場合。",
    },
}
MESSAGES = {
    "extra_forbidden": "このキーは使用できません。",
    "missing": "必須項目です。",
    "json_invalid": "JSONの構文を確認してください。末尾のカンマやコメントは使えません。",
    "string_pattern_mismatch": "文字の使い方が指定の書式に合いません。",
    "string_too_short": "文字列が短すぎます。",
    "string_too_long": "文字列が長すぎます。",
    "int_parsing": "整数を指定してください。",
    "int_type": "整数を指定してください。",
    "float_parsing": "数値を指定してください。",
    "float_type": "数値を指定してください。",
    "bool_parsing": "true または false を指定してください。",
    "bool_type": "true または false を指定してください。",
    "list_type": "配列を指定してください。",
    "dict_type": "JSONオブジェクトを指定してください。",
    "literal_error": "設定で許可されている選択肢を指定してください。",
    "greater_than": "値が入力範囲の下限を超えるように指定してください。",
    "greater_than_equal": "値が入力範囲の下限以上になるように指定してください。",
    "less_than": "値が入力範囲の上限を下回るように指定してください。",
    "less_than_equal": "値が入力範囲の上限以下になるように指定してください。",
}
SUGGESTIONS = {
    "min": "minimum",
    "max": "maximum",
    "type": "data_type",
    "format_type": "format",
    "column": "name",
    "null_rate": "null_probability",
}
HISTORY_ERRORS = {
    "outbox_size_limit": "配送記録が上限に達しました。送信先と未配送件数を確認してください。",
    "run_size_limit": "実行中の出力が設定の上限に達しました。実行結果と容量上限を確認してください。",
    "storage_limit": "保存領域の上限に達しました。保持期間と設定上限を確認してください。",
    "host_memory_headroom_low": "ホストの空きメモリが不足しています。他の処理を終了するか、MIN_AVAILABLE_GIB を確認してください。",
    "NoSuchTableError": "対象テーブルが見つかりません。接続先とテーブル名を確認し、初回は「未作成のテーブルを作成」を使ってください。",
    "InvalidOperation": "数値の変換に失敗しました。数値の型と、欠測・異常ルールを見本で確認してください。",
    "IntegrityError": "DBの制約と書き込む行が一致しません。重複する主キーや空欄を確認してください。",
    "OperationalError": "データベースに接続できないか、操作を受け付けられません。接続テストと権限を確認してください。",
    "worker_start_failed": "実行を開始できませんでした。現在の実行状態とサーバーの空き容量を確認してください。",
    "process_restarted": "実行中にサーバーが再起動しました。出力や配送の状態を確認してください。",
    "landing_disk_space_low": "出力フォルダの空き容量を確認してください。",
    "disk_space_low": "保存先の空き容量が不足しています。容量を確認してください。",
    "PermissionError": "保存先を操作する権限がありません。パスと実行ユーザーの権限を確認してください。",
}


def display_location(path):
    """入力配列の0始まりの位置を、利用者が数える位置に変換する。"""
    if path and path[0] in {"body", "query", "path", "header"}:
        path = path[1:]
    pieces = []
    for key in path:
        if isinstance(key, int):
            pieces.append(f"{key + 1}番目")
        else:
            pieces.append(str(key))
    return " → ".join(pieces) or "設定全体"


def validation_message(error, body):
    """生の入力・値・例外文を含めずに、安全な場所と修正の目安を返す。"""
    location = error["loc"]
    kind = error["type"]
    message = MESSAGES.get(kind, "値や設定の組み合わせを確認してください。")
    if kind == "value_error":
        cause = error.get("ctx", {}).get("error")
        if isinstance(cause, (ConfigurationError, GenerationError)):
            message = str(cause)
    candidate = (
        SUGGESTIONS.get(location[-1])
        if location and kind == "extra_forbidden"
        else None
    )
    if candidate:
        message += (
            f" 「{candidate}」など正式なキーを設定リファレンスで確認してください。"
        )
    label = "JSON構文" if kind == "json_invalid" else display_location(location)
    if kind != "json_invalid" and isinstance(body, dict):
        value = body
        # 行番号だけで探さずに済むよう、既知の項目名を補足する。
        for part in location[1:-1]:
            if isinstance(value, dict) and isinstance(part, str):
                value = value.get(part)
            elif (
                isinstance(value, list)
                and isinstance(part, int)
                and 0 <= part < len(value)
            ):
                value = value[part]
            else:
                break
            if isinstance(part, int) and isinstance(value, dict):
                field = value.get("name")
                if (
                    isinstance(field, str)
                    and field.isascii()
                    and field.isidentifier()
                    and len(field) <= 63
                ):
                    label += f"（{field}）"
    return {"loc": location, "location": label, "type": kind, "code": kind, "msg": message}


def history_error(code):
    """履歴の互換用コードを維持しつつ人が取れる対処を示す。"""
    if not code:
        return None
    if code.startswith("generation_error: "):
        return code.removeprefix("generation_error: ")
    if code in HISTORY_ERRORS:
        return HISTORY_ERRORS[code]
    return "処理を完了できませんでした。対象の設定・接続テストと実行結果を確認してください。"


def install_error_handlers(app):
    """設定エラーを位置付きJSONで返し、予期しない例外の詳細を隠す。"""

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        issues = [validation_message(error, exc.body) for error in exc.errors()]
        return JSONResponse({"detail": issues}, status_code=422)

    @app.exception_handler(GenerationError)
    async def generation_error(request, exc):
        path = ("body", *getattr(exc, "path", ()))
        return JSONResponse(
            {
                "detail": [
                    {
                        "loc": path,
                        "location": display_location(path),
                        "type": "invalid_generation",
                        "code": getattr(exc, "code", "invalid_generation"),
                        "msg": str(exc),
                    }
                ]
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse(
            {
                "detail": "サーバー内部でエラーが発生しました。再実行前に設定と実行状況を確認してください。"
            },
            status_code=500,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )


def management_credentials():
    """設定時だけ管理ログイン用の資格情報をファイルから読み込む。"""
    username = os.getenv("ADMIN_USERNAME", "")
    secret_path = os.getenv("ADMIN_PASSWORD_FILE", "")
    if not username and not secret_path:
        return None
    if not username or ":" in username or not secret_path:
        raise ValueError(
            "管理認証には有効なADMIN_USERNAMEとADMIN_PASSWORD_FILEが必要です"
        )
    with Path(secret_path).open("rb") as secret_file:
        password = secret_file.read(4097).rstrip(b"\r\n")
    if not password or len(password) > 4096 or b"\n" in password or b"\r" in password:
        raise ValueError("管理パスワードファイルには空でない1行が必要です")
    return username.encode("utf-8") + b":" + password


def unauthorized_management(request, credentials, studio):
    """管理操作を拒否する場合だけ401応答を返す。"""
    path = get_route_path(request.scope)
    if credentials is None or path == "/healthz":
        return None
    if studio and path.startswith("/source/"):
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic":
        try:
            supplied = b64decode(token, validate=True)
        except (ValueError, binascii.Error):
            supplied = b""
        if compare_digest(supplied, credentials):
            return None
    return JSONResponse(
        {"detail": "管理画面・管理APIの認証が必要です。"},
        status_code=401,
        headers={
            "WWW-Authenticate": 'Basic realm="Factory Studio", charset="UTF-8"',
            "Cache-Control": "no-store",
        },
    )


def annotate_openapi_properties(schema, kind, studio):
    """Use the app's field reference for OpenAPI without changing its validation schema."""
    if studio:
        from studio import schemas as annotated_schemas
    else:
        from helptext import annotated_schemas
    sections = annotated_schemas(kind)
    known = {}
    for section in sections.values():
        if section.get("title"):
            known[section["title"]] = section
        known.update(section.get("$defs", {}))
    for key, target in schema.items():
        source = known.get(target.get("title", key), {}).get("properties", {})
        for name, prop in target.get("properties", {}).items():
            description = source.get(name, {}).get("description")
            if description and not prop.get("description"):
                prop["description"] = description


def install_help(app, root, studio, kind, credentials):
    """同梱のヘルプとSwaggerを登録し、実際のルートのスキーマを補足する。"""
    port = os.getenv("APP_PORT", "")
    if port.isascii() and port.isdecimal():
        logging.getLogger("uvicorn.error").info(
            "VM内の管理画面既定URL http://127.0.0.1:%s/", port
        )

    for name, directory in (
        ("images", "docs/images"),
        ("examples", "docs/examples"),
        ("preset-files", "presets"),
    ):
        app.mount(
            f"/help/{name}",
            StaticFiles(directory=root / directory),
            name=f"help-{name}",
        )
    app.mount(
        "/help", StaticFiles(directory=root / "docs/help-site", html=True), name="help"
    )

    @app.get("/docs", include_in_schema=False)
    def swagger(request: Request):
        """Swaggerの表示に使う資材を同一サーバーから返す。"""
        prefix = request.scope.get("root_path", "").rstrip("/")
        return get_swagger_ui_html(
            openapi_url=prefix + app.openapi_url,
            title=f"{app.title} | Swagger UI",
            swagger_js_url=prefix + "/static/swagger/swagger-ui-bundle.js",
            swagger_css_url=prefix + "/static/swagger/swagger-ui.css",
            swagger_favicon_url="data:,",
            swagger_ui_parameters={
                "filter": True,
                "docExpansion": "none",
                "showExtensions": False,
                "validatorUrl": None,
            },
        )

    @app.get("/redoc", include_in_schema=False)
    def redoc(request: Request):
        """ReDocも同梱の静的ファイルを使って表示する。"""
        prefix = request.scope.get("root_path", "").rstrip("/")
        source = escape(prefix + app.openapi_url, quote=True)
        asset = escape(prefix + "/static/redoc/redoc.standalone.js", quote=True)
        title = escape(f"{app.title} | ReDoc")
        return HTMLResponse(
            f'''<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>{title}</title>
  <script type="module" src="{asset}"></script>
</head>
<body style="margin:0"><redoc spec-url="{source}" disable-telemetry="true"></redoc></body>
</html>
''',
            headers={
                "Content-Security-Policy": "connect-src 'self'; img-src 'self' data:"
            },
        )

    build_openapi = app.openapi

    def openapi():
        """取得用と管理用の認証を分け、見本の入力例を実際の契約に載せる。"""
        schema = build_openapi()
        if schema.get("externalDocs"):
            return schema
        schema["externalDocs"] = {
            "description": "日本語のAPIガイド",
            "url": "/help/api.html",
        }
        components = schema.setdefault("components", {})
        annotate_openapi_properties(components.get("schemas", {}), kind, studio)
        security = components.setdefault("securitySchemes", {})
        if studio:
            security.update(SOURCE_SCHEMES)
        if credentials is not None:
            security["ManagementBasic"] = {
                "type": "http",
                "scheme": "basic",
                "description": "管理画面と管理APIの認証。",
            }
        for path, methods in schema["paths"].items():
            for method, operation in methods.items():
                if method not in {"get", "post", "patch", "put", "delete"}:
                    continue
                if path.startswith("/source/"):
                    operation.setdefault("security", SOURCE_SECURITY)
                    operation.setdefault("tags", ["公開データの取得"])
                    operation["responses"].setdefault(
                        "401", {"description": "取得用の認証が必要です"}
                    )
                    operation["responses"].setdefault(
                        "503", {"description": "公開データや取得設定の準備が必要です"}
                    )
                elif credentials is not None and path != "/healthz":
                    operation["security"] = [{"ManagementBasic": []}]
                    operation["responses"].setdefault(
                        "401", {"description": "管理用の認証が必要です"}
                    )
                if method == "post" and path in POLICY[kind]:
                    operation.setdefault("parameters", []).append({
                        "name": CONFIRMATION_HEADER, "in": "header", "required": False,
                        "description": "確認が必要な操作では計画APIが返すトークンを指定します。",
                        "schema": {"type": "string"},
                    })
                    operation["responses"]["428"] = {
                        "description": (
                            "実行前の確認エラーです。detail[0].code で未確認（confirmation_required）、"
                            "無効・使用済み（confirmation_invalid）、期限切れ（confirmation_expired）、"
                            "操作や前提の不一致（confirmation_mismatch）を区別できます。"
                        ),
                    }
                if method == "delete" and path == "/api/preset-editor/{identity}":
                    operation["responses"].setdefault("403", {"description": "操作元または権限が許可されていません"})
                elif method != "get":
                    if "requestBody" not in operation:
                        operation["requestBody"] = {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"},
                                    "example": {},
                                }
                            },
                        }
                    for code, label in {
                        "403": "操作元または権限が許可されていません",
                        "413": "リクエストが上限を超えました",
                        "415": "application/jsonが必要です",
                    }.items():
                        operation["responses"].setdefault(code, {"description": label})
                if "422" in operation["responses"]:
                    operation["responses"]["422"] = {
                        "description": "設定・入力のエラー。detailは説明文または位置付きの配列です。",
                        "content": {
                            "application/json": {
                                "example": {
                                    "detail": [
                                        {
                                            "loc": ["body", "fields", 0, "min"],
                                            "location": "fields → 1番目 → min",
                                            "type": "extra_forbidden",
                                            "msg": "このキーは使用できません。",
                                        }
                                    ],
                                }
                            }
                        },
                    }
        example = root / "docs/examples" / f"{kind}-beginner.json"
        body = schema["paths"]["/api/preview"]["post"]["requestBody"]["content"][
            "application/json"
        ]
        body["examples"] = {
            "beginner": {
                "summary": "少量の合成データを確認",
                "value": json.loads(example.read_text()),
            }
        }
        return schema

    app.openapi = openapi
