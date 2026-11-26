"""Factoryアプリへの接続を起動時の登録先に限定する、stdio MCPサーバー。"""

import argparse
import json
import sys
from pathlib import Path

from cli import (
    APP_PORTS,
    MAX_INPUT,
    ClientError,
    FactoryClient,
    credentials_from_env,
    discard_approval,
    read_approval,
    read_json,
)

VERSIONS = ("2025-11-25", "2025-06-18")
VERSION = "0.3.0"
OPERATIONS = {
    "list_presets": ("ひな型のIDと名前を一覧表示します。", {}, [], True),
    "get_preset": (
        "指定したひな型のJSONを取得します。",
        {
            "preset_id": {"type": "string", "description": "ひな型ID"},
        },
        ["preset_id"],
        True,
    ),
    "validate_template": (
        "書き込みや配信をせずアプリでひな型を検証します。",
        {
            "spec": {"type": "object", "description": "アプリのひな型JSON"},
        },
        ["spec"],
        True,
    ),
    "preview": (
        "見本の行を返します。出力、送信、公開は開始しません。",
        {
            "spec": {"type": "object", "description": "アプリのひな型JSON"},
        },
        ["spec"],
        True,
    ),
    "get_status": (
        "実行状態と件数だけを取得します。",
        {
            "run_id": {
                "type": "string",
                "description": "ジョブ形式の実行ID。省略時は履歴一覧",
            },
        },
        [],
        True,
    ),
    "start": (
        "既定はプレビューです。開始にはexecuteと人が発行した確認ファイルが必要です。",
        {
            "spec": {"type": "object", "description": "アプリのひな型JSON"},
            "execute": {
                "type": "boolean",
                "default": False,
                "description": "人が確認した場合のみtrue",
            },
            "profile_revision": {
                "type": "integer",
                "minimum": 1,
                "description": "ログの開始時に使うプロファイルの版",
            },
        },
        ["spec"],
        False,
    ),
    "stop": (
        "executeを明示して停止します。ジョブ形式では実行IDが必要です。",
        {
            "run_id": {"type": "string", "description": "ジョブ形式の実行ID"},
            "execute": {
                "type": "boolean",
                "default": False,
                "description": "停止を明示する場合だけtrue",
            },
        },
        ["execute"],
        False,
    ),
}
STATUS_KEYS = frozenset(
    {
        "id",
        "run_id",
        "status",
        "tick",
        "produced",
        "requests",
        "elapsed_seconds",
        "created_at",
        "started_at",
        "finished_at",
        "processed",
        "generated",
        "written",
        "sent",
        "failed",
        "inserted",
        "updated",
        "deleted",
        "total",
        "total_rows",
    }
)


class RpcError(Exception):
    """不正なJSON-RPC要求に返すエラー。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def load_targets(config_path):
    """運用者が起動時に指定したURLとファイルだけを使う。"""
    data = read_json(config_path)
    if (
        not isinstance(data, dict)
        or set(data) != {"apps"}
        or not isinstance(data["apps"], dict)
        or not data["apps"]
    ):
        raise ClientError("MCPの設定ファイルにはappsを指定してください")
    directory = config_path.resolve().parent
    targets = {}
    use_env = False
    for kind, options in data["apps"].items():
        if (
            kind not in APP_PORTS
            or not isinstance(options, dict)
            or set(options)
            - {
                "url",
                "admin_username",
                "admin_password_file",
                "confirmation_file",
                "use_admin_env",
            }
        ):
            raise ClientError("登録するアプリ種別または設定項目を確認してください")
        for key in ("admin_username", "admin_password_file", "confirmation_file"):
            if key in options and (
                not isinstance(options[key], str) or not options[key]
            ):
                raise ClientError(
                    "MCPのユーザー名とファイルには空でない文字列を指定してください"
                )
        if not isinstance(options.get("use_admin_env", False), bool):
            raise ClientError("use_admin_envにはtrueまたはfalseを指定してください")
        username = options.get("admin_username")
        password_path = options.get("admin_password_file")
        if options.get("use_admin_env", False):
            if use_env or username or password_path:
                raise ClientError("管理認証の環境変数は1つの登録先だけに使用できます")
            use_env = True
            username, password_path = credentials_from_env()
            if not username:
                raise ClientError("管理認証の環境変数を設定してください")
        if password_path:
            password_path = directory / password_path
        confirmation_path = options.get("confirmation_file")
        targets[kind] = (
            FactoryClient(kind, options.get("url"), username, password_path),
            directory / confirmation_path if confirmation_path else None,
        )
    return targets


def status_summary(status):
    """運用者の接続情報、状態の本文、実行内容をツール結果から除く。"""
    if not isinstance(status, dict):
        raise ClientError("アプリが有効な状態情報を返しませんでした")
    if isinstance(status.get("runs"), list):
        return {
            "runs": [
                status_summary(run) for run in status["runs"] if isinstance(run, dict)
            ]
        }
    result = {
        key: value
        for key, value in status.items()
        if key in STATUS_KEYS
        and (value is None or isinstance(value, (bool, int, float, str)))
    }
    if isinstance(status.get("stats"), dict):
        result["stats"] = {
            key: value
            for key, value in status["stats"].items()
            if key in STATUS_KEYS | {"bytes", "files", "batches"} and type(value) is int
        }
    return result


class StdioServer:
    """MCPのstdio接続で固定のツール群を公開する。"""

    def __init__(self, targets):
        self.targets = targets
        self.initialized = False

    def list_tools(self):
        """利用可能なアプリ種別を各ツールの入力契約に含める。"""
        entries = []
        for name, (description, properties, required, read_only) in OPERATIONS.items():
            entries.append(
                {
                    "name": name,
                    "description": description,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "app": {
                                "type": "string",
                                "enum": sorted(self.targets),
                                "description": "登録済みアプリ種別",
                            },
                            **properties,
                        },
                        "required": ["app", *required],
                        "additionalProperties": False,
                    },
                    "annotations": {"readOnlyHint": read_only, "openWorldHint": True},
                }
            )
        return {"tools": entries}

    def call_tool(self, name, arguments):
        """固定経路へ振り分け、入力から任意のURLやファイルを選べないようにする。"""
        if (
            not isinstance(name, str)
            or name not in OPERATIONS
            or not isinstance(arguments, dict)
        ):
            raise RpcError(-32602, "ツール名または引数を確認してください")
        _, fields, required, _ = OPERATIONS[name]
        if set(arguments) - {"app", *fields} or {"app", *required} - arguments.keys():
            raise RpcError(-32602, "必須項目とツールの入力契約を確認してください")
        for key, value in arguments.items():
            kind = fields[key]["type"] if key != "app" else "string"
            if (
                kind == "boolean"
                and type(value) is not bool
                or kind == "object"
                and not isinstance(value, dict)
                or kind == "string"
                and not isinstance(value, str)
                or kind == "integer"
                and (type(value) is not int or value < 1)
            ):
                raise RpcError(-32602, f"{key} の型や値を確認してください")
        app = arguments["app"]
        if app not in self.targets:
            raise RpcError(-32602, "登録済みのアプリ種別を指定してください")
        client, confirmation_file = self.targets[app]
        try:
            if name == "list_presets":
                entries = client.request("/api/presets").get("presets", [])
                return {
                    "presets": [
                        {
                            "id": item["id"],
                            "name": item.get("spec", {}).get("name", item["id"]),
                        }
                        for item in entries
                    ]
                }
            if name == "get_preset":
                return client.get_preset(arguments["preset_id"])
            if name == "get_status":
                return status_summary(client.status(arguments.get("run_id")))
            if name == "stop":
                if arguments.get("execute") is not True:
                    raise ClientError("停止する場合は execute を true にしてください")
                path = client.mutation_path("stop", arguments.get("run_id"))
                client.check_kind()
                return status_summary(client.request(path, {}))
            spec = arguments["spec"]
            if name == "start" and arguments.get("execute") is True:
                if confirmation_file is None:
                    raise ClientError("実行には運用者が設定した確認ファイルが必要です")
                path = client.with_revision(
                    client.mutation_path("start"), arguments.get("profile_revision")
                )
                token, identity = read_approval(confirmation_file)
                client.check_kind()
                client.check_confirmation_available()
                status = status_summary(client.request(path, spec, token))
                if not discard_approval(confirmation_file, identity):
                    status["confirmation_file_warning"] = (
                        "開始を受け付けましたが確認ファイルを削除できませんでした。"
                        "権限を確認してから人が plan --replace で再発行してください"
                    )
                return status
            if arguments.get("profile_revision") is not None:
                raise RpcError(
                    -32602, "profile_revision はログの実開始にだけ指定してください"
                )
            result = client.request("/api/preview", spec)
            return {"valid": True} if name == "validate_template" else result
        except ClientError as exc:
            return self.tool_result(
                {"error": str(exc), "status": exc.status, "detail": exc.detail},
                is_error=True,
            )

    @staticmethod
    def tool_result(result, *, is_error=False):
        """対応する構造化結果と互換性のためのテキストを返す。"""
        value = result if isinstance(result, dict) else {"result": result}
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": value,
            "isError": is_error,
        }

    def request(self, message):
        """初期化とツール要求を処理し、通知には応答しない。"""
        if (
            not isinstance(message, dict)
            or message.get("jsonrpc") != "2.0"
            or not isinstance(message.get("method"), str)
        ):
            return self.error(None, RpcError(-32600, "不正なJSON-RPC要求です"))
        if "id" not in message:
            return None
        req_id = message["id"]
        if type(req_id) not in {int, str}:
            return self.error(None, RpcError(-32600, "JSON-RPCのIDを確認してください"))
        params = message.get("params", {})
        method = message["method"]
        try:
            if not isinstance(params, dict):
                raise RpcError(-32602, "paramsにはオブジェクトを指定してください")
            if method == "initialize":
                if not isinstance(params.get("protocolVersion"), str):
                    raise RpcError(-32602, "protocolVersionを指定してください")
                protocol = params["protocolVersion"]
                self.initialized = True
                result = {
                    "protocolVersion": protocol
                    if protocol in VERSIONS
                    else VERSIONS[0],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "factory-apps", "version": VERSION},
                }
            elif method == "ping":
                result = {}
            elif method not in {"tools/list", "tools/call"}:
                raise RpcError(-32601, "このメソッドには対応していません")
            elif not self.initialized:
                raise RpcError(-32002, "先にinitializeを実行してください")
            elif method == "tools/list":
                result = self.list_tools()
            else:
                output = self.call_tool(params.get("name"), params.get("arguments", {}))
                result = (
                    output
                    if isinstance(output, dict) and output.get("isError") is True
                    else self.tool_result(output)
                )
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except RpcError as exc:
            return self.error(req_id, exc)
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return self.error(
                req_id,
                RpcError(-32603, "アプリ応答または入力JSONを処理できませんでした"),
            )

    @staticmethod
    def error(req_id, exc):
        """JSON-RPC 2.0のエラー応答を構成する。"""
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": exc.code, "message": str(exc)},
        }

    def serve(self, source, output):
        """標準出力には1行ごとのプロトコルメッセージだけを書き出す。"""
        while line := source.readline(MAX_INPUT + 1):
            if len(line) > MAX_INPUT:
                while not line.endswith(b"\n") and (
                    line := source.readline(MAX_INPUT + 1)
                ):
                    pass
                response = self.error(
                    None, RpcError(-32600, "メッセージが2MiBを超えています")
                )
            else:
                try:
                    response = self.request(json.loads(line))
                except (ValueError, UnicodeError, RecursionError):
                    response = self.error(
                        None, RpcError(-32700, "JSONを解析できません")
                    )
            if response is not None:
                output.write(
                    (
                        json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n"
                    ).encode()
                )
                output.flush()


def main():
    """設定を確定してからMCPのstdio接続を開始する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", required=True, type=Path, help="許可するアプリのURLを記録したJSON"
    )
    args = parser.parse_args()
    try:
        server = StdioServer(load_targets(args.config))
    except (ClientError, OSError, ValueError, RecursionError) as exc:
        message = (
            str(exc)
            if isinstance(exc, ClientError)
            else "MCPの設定ファイルを読めません"
        )
        print(message, file=sys.stderr)
        return 2
    server.serve(sys.stdin.buffer, sys.stdout.buffer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
