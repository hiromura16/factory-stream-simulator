"""Factoryアプリの操作と、ネットワークを使わないひな型検証のCLI。"""

import argparse
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from base64 import b64encode
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

try:
    import fcntl
except ImportError:  # Windows does not provide directory locks.
    fcntl = None


APP_PORTS = {
    "sql": 3560,
    "files": 3561,
    "stream": 3562,
    "equipment": 3640,
    "api": 3641,
    "historian": 3642,
    "logs": 3643,
    "identification": 3644,
}
JOB_APPS = frozenset({"sql", "files", "stream"})
MAX_INPUT = 2 * 1024 * 1024
MAX_RESPONSE = 16 * 1024 * 1024
CONFIRMATION_HEADER = "X-Operation-Confirmation"
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,4096}\Z")


class ClientError(Exception):
    """端末やMCPツールに返せるAPIクライアントのエラー。"""

    def __init__(self, message, status=None, detail=None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class RejectRedirect(HTTPRedirectHandler):
    """資格情報付きの要求を、起動時に設定した接続先だけに制限する。"""

    def redirect_request(self, *_args, **_kwargs):
        return None


def app_kind():
    """作業フォルダーに依存せず、このリポジトリに対応するアプリ種別を返す。"""
    info = Path(__file__).resolve().parent / "docs" / "help-site.json"
    return json.loads(info.read_text(encoding="utf-8"))["kind"]


def default_url(kind):
    """環境変数APP_PORT、リポジトリの.env、アプリの既定値の順に使う。"""
    configured = os.environ.get("APP_PORT")
    if configured is None:
        dotenv = Path(__file__).resolve().with_name(".env")
        if dotenv.is_file():
            for line in dotenv.read_text(encoding="utf-8").splitlines():
                match = re.fullmatch(
                    r"""[ \t]*(?:export[ \t]+)?APP_PORT[ \t]*=[ \t]*(['"]?)([0-9]+)\1(?:[ \t]+#.*|[ \t]*)""",
                    line,
                )
                if match:
                    configured = match[2]
                    break
    if configured is None:
        configured = str(APP_PORTS[kind])
    if not re.fullmatch(r"[0-9]{1,5}", configured) or not 1 <= int(configured) <= 65535:
        raise ClientError("APP_PORTには1〜65535の整数を指定してください")
    return f"http://127.0.0.1:{int(configured)}"


def read_json(path, limit=MAX_INPUT):
    """UTF-8 JSONを上限付きで読み込む。"""
    if path == "-":
        raw = sys.stdin.buffer.read(limit + 1)
    else:
        with Path(path).open("rb") as src:
            raw = src.read(limit + 1)
    if len(raw) > limit:
        raise ClientError("JSONがサイズ上限を超えています")
    return json.loads(raw.decode("utf-8-sig"))


def secret_file(path, maximum=4096, *, require_private=False):
    """設定済みファイルの1行だけを読み、値をエラーに含めない。"""
    try:
        with Path(path).open("rb") as source:
            if (
                require_private
                and os.name == "posix"
                and os.fstat(source.fileno()).st_mode & 0o077
            ):
                raise ClientError("確認トークンファイルの権限を0600にしてください")
            raw = source.read(maximum + 3)
        raw = raw.rstrip(b"\r\n")
        if not raw or len(raw) > maximum or b"\r" in raw or b"\n" in raw:
            raise ValueError
        return raw.decode("utf-8")
    except (OSError, UnicodeError, ValueError):
        raise ClientError("資格情報または確認トークンのファイルを読めません") from None


def credentials_from_env():
    """管理認証を優先し、従来のAPP_PASSWORD_FILEにも対応する。"""
    username = os.environ.get("ADMIN_USERNAME", "")
    password_file = os.environ.get("ADMIN_PASSWORD_FILE", "")
    if username or password_file:
        if not username or not password_file:
            raise ClientError(
                "管理認証を使う場合は ADMIN_USERNAME と ADMIN_PASSWORD_FILE を指定してください"
            )
        return username, password_file
    legacy = os.environ.get("APP_PASSWORD_FILE", "")
    return ("operator", legacy) if legacy else (None, None)


def identifier(value):
    """設定名や実行IDをURLの1要素に制限する。"""
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ClientError("IDは1〜64文字の英数字・ハイフン・下線を指定してください")
    return value


def safe_detail(raw):
    """検証エラーから構造化された内容を取り出す。送信した入力値は返さない。"""
    detail = raw.get("detail") if isinstance(raw, dict) else None
    if isinstance(detail, str):
        return detail[:1000]
    if isinstance(detail, list):
        return [
            {
                key: item[key]
                for key in ("loc", "location", "type", "code", "msg")
                if key in item
            }
            for item in detail[:20]
            if isinstance(item, dict)
        ]
    return None


class FactoryClient:
    """指定された1つのFactoryアプリだけに接続する。"""

    def __init__(self, kind, base_url, username=None, password_file=None):
        if kind not in APP_PORTS:
            raise ClientError("有効なアプリ種別を指定してください")
        if (
            not isinstance(base_url, str)
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in base_url)
            or "\\" in base_url
        ):
            raise ClientError("接続先URLを確認してください")
        try:
            url = urlsplit(base_url)
            port = url.port
        except ValueError:
            raise ClientError("接続先URLを確認してください") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or port == 0
            or not re.fullmatch(r"(?:/[A-Za-z0-9_.~-]+)*/?", url.path)
            or any(part in {".", ".."} for part in url.path.split("/"))
        ):
            raise ClientError(
                "接続先URLは資格情報・クエリ・フラグメントのないHTTP(S) URLを指定してください"
            )
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = url.hostname.lower() == "localhost"
        self.secure_transport = url.scheme == "https" or loopback
        if bool(username) != bool(password_file):
            raise ClientError(
                "管理認証にはユーザー名とパスワードファイルを両方設定してください"
            )
        if username and (
            not isinstance(username, str)
            or ":" in username
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in username)
        ):
            raise ClientError("管理ユーザー名を確認してください")
        if username and not self.secure_transport:
            raise ClientError(
                "管理認証を送る接続先にはHTTPSまたはループバックURLを使用してください"
            )
        self.kind = kind
        self.base_url = f"{url.scheme}://{url.netloc}{url.path.rstrip('/')}"
        self.username = username
        self.password_file = password_file
        self.opener = build_opener(ProxyHandler({}), RejectRedirect())

    def request(self, path, payload=None, confirmation=None):
        """認められたAPIパスへJSONを送り、リダイレクトを拒否する。"""
        if path != "/openapi.json" and not path.startswith("/api/"):
            raise ClientError("このAPIパスは指定できません")
        data = (
            None
            if payload is None
            else json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        )
        if data is not None and len(data) > MAX_INPUT:
            raise ClientError("リクエストのJSONは2MiB以下にしてください")
        req = Request(
            self.base_url + path, data=data, headers={"Accept": "application/json"}
        )
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if self.username:
            password = secret_file(self.password_file)
            basic = b64encode(f"{self.username}:{password}".encode()).decode("ascii")
            req.add_unredirected_header("Authorization", f"Basic {basic}")
        if confirmation is not None:
            if not self.secure_transport or not TOKEN.fullmatch(confirmation):
                raise ClientError(
                    "HTTPSまたはループバックの接続先と、有効な確認トークンが必要です"
                )
            req.add_unredirected_header(CONFIRMATION_HEADER, confirmation)
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            with exc:
                if 300 <= exc.code < 400:
                    raise ClientError(
                        "リダイレクトを拒否しました。最終URLを設定してください",
                        exc.code,
                    ) from None
                try:
                    detail = safe_detail(json.loads(exc.read(65537)))
                except (UnicodeError, ValueError, RecursionError):
                    detail = None
                raise ClientError(
                    f"APIがHTTP {exc.code}を返しました", exc.code, detail
                ) from None
        except (URLError, OSError):
            raise ClientError(
                "アプリに接続できません。起動状態、URL、TLS証明書を確認してください"
            ) from None
        if len(raw) > MAX_RESPONSE:
            raise ClientError("API応答が16MiBを超えています")
        try:
            return json.loads(raw)
        except (UnicodeError, ValueError, RecursionError):
            raise ClientError("アプリから有効なJSONが返りませんでした") from None

    def check_kind(self):
        """登録したアプリと実際の接続先を実行前に照合する。"""
        info = self.request("/api/info")
        if not isinstance(info, dict) or info.get("kind") != self.kind:
            raise ClientError("登録したアプリ種別と接続先のアプリ種別が一致しません")

    def check_confirmation_available(self):
        """確認APIのない旧サーバーへのMCP実開始を防ぐ。"""
        spec = self.request("/openapi.json")
        paths = spec.get("paths") if isinstance(spec, dict) else None
        plan = paths.get("/api/operations/plan") if isinstance(paths, dict) else None
        if not isinstance(plan, dict) or not isinstance(plan.get("post"), dict):
            raise ClientError("確認APIを備えたアプリに接続してください")

    def get_preset(self, preset_id):
        """両形式のアプリから指定したひな型のJSONを取得する。"""
        preset_id = identifier(preset_id)
        if self.kind in JOB_APPS:
            return self.request(f"/api/presets/{preset_id}/export")
        for item in self.request("/api/presets").get("presets", []):
            if item.get("id") == preset_id:
                return item["spec"]
        raise ClientError("指定したひな型が見つかりません")

    def mutation_path(self, action, run_id=None):
        """アプリと操作に対応する書き込み経路を返す。"""
        if action == "start":
            return "/api/runs" if self.kind in JOB_APPS else "/api/start"
        if action == "stop":
            if self.kind in JOB_APPS:
                return f"/api/runs/{identifier(run_id)}/stop"
            return "/api/stop"
        if action == "retry" and self.kind == "stream":
            return "/api/outbox/retry"
        if action == "prepare" and self.kind == "sql":
            return "/api/table/prepare"
        raise ClientError("選択したアプリはこの操作に対応していません")

    def status(self, run_id=None):
        """ジョブの実行履歴またはライブシミュレーターの状態を読む。"""
        if self.kind in JOB_APPS:
            path = (
                f"/api/runs/{identifier(run_id)}" if run_id is not None else "/api/runs"
            )
        else:
            if run_id is not None:
                raise ClientError("このアプリの状態取得には実行IDを指定しません")
            path = "/api/state"
        return self.request(path)

    def with_revision(self, path, revision):
        """ログの開始に、計画時と同じプロファイルの版を付ける。"""
        if revision is None:
            return path
        if (
            self.kind != "logs"
            or path != "/api/start"
            or not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 1
        ):
            raise ClientError(
                "プロファイルの版はログの開始に1以上の整数で指定してください"
            )
        return f"{path}?profile_revision={revision}"


@contextmanager
def approval_directory_lock(path):
    """POSIX上で、確認ファイルを扱うCLIとMCPの短い操作を直列化する。"""
    if fcntl is None:
        yield
        return
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def approval_identity(path):
    """パスをたどらず、書き換えと差し替えを識別する情報を返す。"""
    return approval_signature(path.lstat())


def approval_signature(info):
    """読み取り時に変わるアクセス時刻を照合から外す。"""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_approval(path):
    """確認ファイルそのものを読み、使用後の照合情報を取得する。"""
    try:
        with approval_directory_lock(path):
            initial = path.lstat()
            if not stat.S_ISREG(initial.st_mode):
                raise ClientError("確認ファイルには通常のファイルを指定してください")
            if os.name == "posix" and initial.st_mode & 0o077:
                raise ClientError("確認トークンファイルの権限を0600にしてください")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
            with os.fdopen(descriptor, "rb") as file:
                identity = approval_signature(initial)
                if approval_signature(os.fstat(file.fileno())) != identity:
                    raise ClientError("確認ファイルが変更されました。もう一度確認してください")
                raw = file.read(4099)
                if len(raw) > 4098:
                    raise ClientError("確認ファイルに有効なトークンがありません")
                token = raw.removesuffix(b"\n").removesuffix(b"\r").decode("ascii")
                if approval_identity(path) != identity:
                    raise ClientError("確認ファイルが変更されました。もう一度確認してください")
            if not TOKEN.fullmatch(token):
                raise ClientError("確認ファイルに有効なトークンがありません")
            return token, identity
    except FileNotFoundError:
        raise ClientError("実行には人が発行した確認ファイルが必要です") from None
    except (OSError, UnicodeError):
        raise ClientError("確認ファイルを読めません。パスと権限を確認してください") from None


def discard_approval(path, identity):
    """成功した要求で読んだファイルだけを取り除き、片付けの成否を返す。"""
    try:
        with approval_directory_lock(path):
            if approval_identity(path) == identity:
                path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def save_token(path, token, *, original=None):
    """通常は新規作成し、明示した再発行では照合後に原子的に置き換える。"""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ClientError("APIが有効な確認トークンを返しませんでした")
    try:
        with approval_directory_lock(path):
            if original is None:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write(token + "\n")
                return
            if approval_identity(path) != original:
                raise ClientError("確認ファイルが変更されました。現在のファイルを確認してください")
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=".confirmation-", delete=False
            ) as file:
                staged = Path(file.name)
                try:
                    file.write(token + "\n")
                    file.close()
                    staged.replace(path)
                finally:
                    staged.unlink(missing_ok=True)
    except FileExistsError:
        raise ClientError(
            "確認ファイルには存在しない名前を指定してください。再発行には plan --replace を使えます"
        ) from None
    except OSError:
        raise ClientError("確認ファイルを保存できません。パスと権限を確認してください") from None


def main(argv=None):
    """コマンドを解析し、検証または登録済み経路の要求を実行する。"""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=[
            "info",
            "preview",
            "validate",
            "presets",
            "export",
            "start",
            "plan",
            "status",
            "runs",
            "stop",
            "source",
            "retry",
            "prepare",
        ],
    )
    p.add_argument("file", nargs="?", help="validateで読むJSONのパス。- は標準入力")
    p.add_argument(
        "--url", help="アプリURL。既定はAPP_PORTまたはアプリ既定のループバックURL"
    )
    p.add_argument("--spec", help="APIリクエストに使うJSONのパス。- は標準入力")
    p.add_argument("--preset-id", help="exportで取得するひな型ID")
    p.add_argument("--run-id", help="statusまたはstopの実行ID（ジョブ形式）")
    p.add_argument(
        "--operation",
        choices=["start", "retry", "prepare"],
        default="start",
        help="planの対象",
    )
    p.add_argument(
        "--confirmation-file",
        type=Path,
        help="planで作る、または実行時に読む確認ファイル",
    )
    p.add_argument(
        "--replace", action="store_true", help="planで既存の確認ファイルを再発行"
    )
    p.add_argument(
        "--profile-revision", type=int, help="ログのplan/startに使うプロファイル版"
    )
    p.add_argument(
        "--compact", action="store_true", help="validate結果を既定値省略JSONで出力"
    )
    a = p.parse_intermixed_args(argv)
    if a.replace and a.action != "plan":
        p.error("--replace は plan でだけ使えます")
    try:
        if a.action == "validate":
            if not (a.file or a.spec) or (a.file and a.spec):
                p.error("validateではJSONファイルを1つ指定してください")
            validator = (
                Path(__file__).resolve().parent / "scripts" / "validate_template.py"
            )
            args = [sys.executable, str(validator), a.file or a.spec]
            if a.compact:
                args.append("--compact")
            return subprocess.run(args, check=False).returncode
        if a.file is not None:
            p.error("JSONファイルは --spec で指定してください")
        kind = app_kind()
        username, password_file = credentials_from_env()
        client = FactoryClient(
            kind, a.url or default_url(kind), username, password_file
        )
        if a.action == "info":
            result = client.request("/api/info")
        elif a.action == "presets":
            result = client.request("/api/presets")
        elif a.action == "export":
            result = client.get_preset(a.preset_id)
        elif a.action in {"status", "runs"}:
            result = client.status(a.run_id)
        elif a.action == "source":
            if kind not in JOB_APPS:
                raise ClientError("このアプリでは status を使ってください")
            result = client.request("/api/source")
        else:
            body = read_json(a.spec) if a.spec else {}
            if not isinstance(body, dict):
                raise ClientError("設定JSONはオブジェクトを指定してください")
            if a.action == "preview":
                result = client.request("/api/preview", body)
            else:
                action = a.operation if a.action == "plan" else a.action
                path = client.mutation_path(action, a.run_id)
                request_path = client.with_revision(path, a.profile_revision)
                if a.action == "plan":
                    if a.confirmation_file is None:
                        p.error("planでは --confirmation-file を指定してください")
                    if not client.secure_transport:
                        raise ClientError(
                            "確認の計画にはHTTPSまたはループバックURLを指定してください"
                        )
                    original = None
                    if os.path.lexists(a.confirmation_file):
                        if not a.replace:
                            raise ClientError(
                                "確認ファイルには存在しない名前を指定してください。再発行には plan --replace を使えます"
                            )
                        _, original = read_approval(a.confirmation_file)
                    client.check_kind()
                    plan = {"path": path, "payload": body, "force_confirmation": True}
                    if a.profile_revision is not None:
                        plan["profile_revision"] = a.profile_revision
                    result = client.request("/api/operations/plan", plan)
                    if not isinstance(result, dict):
                        raise ClientError(
                            "確認計画がJSONオブジェクトで返りませんでした"
                        )
                    token = result.pop("confirmation_token", None)
                    if token is not None:
                        save_token(a.confirmation_file, token, original=original)
                        result["confirmation_saved"] = True
                else:
                    token = (
                        secret_file(a.confirmation_file, require_private=True)
                        if a.confirmation_file
                        else None
                    )
                    client.check_kind()
                    result = client.request(request_path, body, token)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        if exc.detail is not None:
            print(json.dumps(exc.detail, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2 if exc.status is None else 1
    except (OSError, ValueError, RecursionError):
        print(
            "ファイルのパス、権限とUTF-8 JSONの内容を確認してください", file=sys.stderr
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
