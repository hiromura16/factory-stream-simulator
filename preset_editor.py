"""Manage user preset drafts without invoking execution or accessing connections."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, HTTPException, Path as ApiPath, Request
from fastapi.routing import APIRoute
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, create_model

IDENTITY = r"^[A-Za-z0-9_-]{1,64}$"
MAX_PRESET_BYTES = 2 * 1024 * 1024
SECRET_NAMES = {
    "accesstoken", "apikey", "authorization", "bearertoken", "clientsecret",
    "connectionstring", "keytab", "passphrase", "password", "privatekey",
    "accesskey", "secretkey", "sessiontoken", "dbaccesstoken", "walletpassword", "tlskeypassword",
    "sshprivatekey", "sshkeypassword", "natstoken", "opcpassword", "outputpassword", "outputtoken",
    "refreshtoken", "saslpassword", "secret", "secretaccesskey", "smbpassword",
    "sslkeypassword", "token", "webhooksecret", "awssecretaccesskey",
}
PRESET_TAG = ["設定・ひな型"]
PresetId = Annotated[str, ApiPath(pattern=IDENTITY, description="同梱または保存済みのプリセットID。")]
Revision = Annotated[str | None, Header(alias="If-Match", description="取得時の revision を引用符で囲んだ値。")]
Tag = Annotated[str, Field(min_length=1, max_length=40)]


class PresetDraft(BaseModel):
    """Define a reusable preset independently of its execution settings."""

    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(description="各アプリのバージョン付きプリセットJSON。接続はIDで参照します。")
    tags: list[Tag] = Field(default_factory=list, max_length=16, description="プリセット一覧で絞り込むラベル。")


class NewPreset(PresetDraft):
    """Create a new preset under an unused identifier."""

    id: str = Field(pattern=IDENTITY, description="既存と重複しない英数字、下線、ハイフンのID。")


def clean_secrets(value, depth=0):
    """Remove authentication keys from any legacy preset being read."""
    if depth > 80:
        return None
    if isinstance(value, dict):
        return {
            key: clean_secrets(item, depth + 1)
            for key, item in value.items()
            if re.sub(r"[^a-z0-9]", "", key.casefold()) not in SECRET_NAMES
        }
    if isinstance(value, list):
        return [clean_secrets(item, depth + 1) for item in value]
    return value


def require_safe_preset(raw):
    """Reject credential-bearing or oversized editor input before model validation."""
    if clean_secrets(raw) != raw:
        raise HTTPException(422, "認証情報は接続プロファイルへ入力してください。JSONの入れ子は80段までです。")
    try:
        size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode())
    except (ValueError, UnicodeError, RecursionError):
        raise HTTPException(422, "JSONに保存できない値が含まれています。") from None
    if size > MAX_PRESET_BYTES:
        raise HTTPException(413, "プリセットは2MiB以下にしてください。")
    return raw


class PresetSummary(BaseModel):
    """Identify a preset and the revision used for conditional writes."""

    id: str = Field(description="ライブラリで一意のプリセットID。")
    name: str
    description: str
    source: Literal["bundled", "user"] = Field(description="bundled は同梱・読み取り専用。user は保存済み。")
    revision: str = Field(description="上書き・削除の If-Match に使う版。値を二重引用符で囲みます。")
    updated_at: str | None = Field(description="保存日時。旧データなど日時がない場合は null。")
    tags: list[str]


class PresetDetail(PresetSummary):
    """Return the editable JSON document and legacy credential cleanup status."""

    spec: dict[str, Any] = Field(description="アプリ固有のJSON。/api/preset-editor/validate の入力定義を参照。")
    secrets_removed: bool = Field(description="旧データから認証項目を除いて返した場合は true。")


class PresetCatalog(BaseModel):
    """Return the metadata needed to search and list stored presets."""

    presets: list[PresetSummary]


class DeletedPreset(BaseModel):
    """Confirm removal of the requested user preset."""

    id: str
    deleted: Literal[True]


class PresetLibrary:
    """Read and conditionally mutate the same SQLite presets consumed by the app."""

    def __init__(self, connection, directory, spec_column):
        self.connection = connection
        self.bundled = frozenset(path.stem for path in Path(directory).glob("*.json"))
        if spec_column == "spec":
            self.document = "p.spec"
            self.updated_at = "p.updated_at"
            self.upsert = (
                "INSERT INTO presets(id,spec,updated_at) VALUES(?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET spec=excluded.spec,updated_at=excluded.updated_at"
            )
        elif spec_column == "data":
            self.document = "p.data"
            self.updated_at = "m.updated_at"
            self.upsert = (
                "INSERT INTO presets(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data"
            )
        else:
            raise ValueError("Unsupported preset column")
        self.timed = spec_column == "spec"
        with self.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS preset_editor_metadata ("
                "id TEXT PRIMARY KEY,tags TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )

    def require_writable(self, identity):
        """Reject attempts to edit or remove a bundled preset."""
        if identity in self.bundled:
            raise HTTPException(403, "同梱プリセットは別名で保存してください。")

    def _rows(self, conn, identity=None):
        sql = (
            f"SELECT p.id,{self.document} AS document,{self.updated_at} AS updated_at,m.tags "
            "FROM presets p LEFT JOIN preset_editor_metadata m ON p.id=m.id"
        )
        return (
            conn.execute(sql + " ORDER BY p.id")
            if identity is None
            else conn.execute(sql + " WHERE p.id=?", (identity,)).fetchone()
        )

    def _record(self, row, *, include_spec):
        raw = json.loads(row["document"])
        tags = json.loads(row["tags"]) if row["tags"] else []
        revision = sha256(
            json.dumps([row["document"], row["updated_at"], tags], ensure_ascii=False).encode()
        ).hexdigest()
        result = {
            "id": row["id"],
            "name": raw.get("name") or row["id"],
            "description": raw.get("description") or "",
            "source": "bundled" if row["id"] in self.bundled else "user",
            "revision": revision,
            "updated_at": row["updated_at"],
            "tags": tags,
        }
        if include_spec:
            result["spec"] = clean_secrets(raw)
            result["secrets_removed"] = result["spec"] != raw
        return result

    def list(self):
        """Return searchable metadata for the preset browser."""
        with self.connection() as conn:
            return [self._record(row, include_spec=False) for row in self._rows(conn)]

    def get(self, identity):
        """Load one preset with its current revision."""
        with self.connection() as conn:
            row = self._rows(conn, identity)
            if row is None:
                raise HTTPException(404, "プリセットが見つかりません。")
            return self._record(row, include_spec=True)

    def _match(self, row, expected):
        if expected is None:
            raise HTTPException(428, "保存前の版を指定してください。")
        if row is None:
            raise HTTPException(404, "このプリセットは削除されています。")
        if expected != '"' + self._record(row, include_spec=False)["revision"] + '"':
            raise HTTPException(412, "別の操作でプリセットが更新されました。変更を残したまま比較できます。")

    def save(self, identity, spec, tags, *, create, expected=None):
        """Atomically create or replace a user preset and its display metadata."""
        self.require_writable(identity)
        encoded = spec.model_dump_json()
        updated = datetime.now(timezone.utc).isoformat()
        tags = json.dumps(list(dict.fromkeys(tag.strip() for tag in tags if tag.strip())), ensure_ascii=False)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = self._rows(conn, identity)
            if create:
                if row is not None:
                    raise HTTPException(409, "同じIDがあります。別のIDで保存してください。")
            else:
                self._match(row, expected)
            conn.execute(self.upsert, (identity, encoded, updated) if self.timed else (identity, encoded))
            conn.execute(
                "INSERT INTO preset_editor_metadata VALUES(?,?,?) ON CONFLICT(id) "
                "DO UPDATE SET tags=excluded.tags,updated_at=excluded.updated_at",
                (identity, tags, updated),
            )
            return self._record(self._rows(conn, identity), include_spec=True)

    def delete(self, identity, expected):
        """Remove only the reviewed preset revision."""
        self.require_writable(identity)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._match(self._rows(conn, identity), expected)
            conn.execute("DELETE FROM presets WHERE id=?", (identity,))
            conn.execute("DELETE FROM preset_editor_metadata WHERE id=?", (identity,))


class BoundedPresetRoute(APIRoute):
    """Apply the editor's size limit to actual bytes, including chunked requests."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def limited_handler(request: Request):
            if request.method not in {"POST", "PUT"}:
                return await original(request)
            size = 0

            async def receive():
                nonlocal size
                message = await request.receive()
                size += len(message.get("body", b""))
                if size > MAX_PRESET_BYTES:
                    raise HTTPException(413, "プリセットは2MiB以下にしてください。")
                return message

            limited = Request(request.scope, receive)
            try:
                await limited.json()
            except json.JSONDecodeError:
                # The standard FastAPI handler will attach the syntax error's location.
                pass
            except RecursionError:
                raise HTTPException(422, "JSONの入れ子は80段までです。") from None
            except UnicodeError:
                raise HTTPException(422, "JSONはUTF-8で送信してください。") from None
            return await original(limited)

        return limited_handler


def install_preset_editor(app, library, spec_model, validate_spec):
    """Register the preset browser and optimistic-lock editing operations."""

    router = APIRouter(prefix="/api/preset-editor", route_class=BoundedPresetRoute)
    safe_spec = Annotated[spec_model, BeforeValidator(require_safe_preset)]
    edit_request = create_model(
        "PresetEditorDraft", __base__=PresetDraft,
        spec=(safe_spec, Field(description="バージョン付きのアプリ固有プリセット。接続はIDで参照します。")),
    )
    create_request = create_model(
        "PresetEditorCreate", __base__=NewPreset,
        spec=(safe_spec, Field(description="バージョン付きのアプリ固有プリセット。接続はIDで参照します。")),
    )
    validation_response = create_model(
        "PresetEditorValidation",
        spec=(dict[str, Any], Field(description="検証済みのプリセットJSON。入力の spec と同じ契約です。")),
        compact_spec=(dict[str, Any], Field(description="既定値を省略した設定。バージョンは保持します。")),
    )

    def validated(spec):
        validate_spec(spec)
        return spec

    @router.get("", summary="プリセット編集用一覧", tags=PRESET_TAG, response_model=PresetCatalog)
    def editor_list():
        """同梱・保存済みの区分、タグ、更新日時を一覧で返します。"""
        return {"presets": library.list()}

    @router.post("/validate", summary="編集中のプリセットを検証", tags=PRESET_TAG,
              response_model=validation_response)
    def editor_validate(draft: edit_request):
        """保存、接続、出力を行わず、検証済みのJSONを返します。"""
        spec = validated(draft.spec)
        return {"spec": spec.model_dump(mode="json"),
                "compact_spec": {"version": spec.version, **spec.model_dump(mode="json", exclude_defaults=True)}}

    @router.post("", status_code=201, summary="別名でプリセットを保存", tags=PRESET_TAG, response_model=PresetDetail,
              responses={403: {"description": "同梱プリセット"}, 409: {"description": "IDが登録済み"}})
    def editor_create(draft: create_request):
        """未使用のIDで保存します。同じIDの設定は上書きしません。"""
        return library.save(draft.id, validated(draft.spec), draft.tags, create=True)

    @router.get("/{identity}", summary="編集するプリセットを開く", tags=PRESET_TAG,
             response_model=PresetDetail, responses={404: {"description": "指定のIDが見つかりません"}})
    def editor_get(identity: PresetId):
        """編集用JSONと、更新・削除時の照合に使う revision を返します。"""
        return library.get(identity)

    @router.put("/{identity}", summary="プリセットを上書き保存", tags=PRESET_TAG, response_model=PresetDetail,
             responses={403: {"description": "同梱プリセット"}, 412: {"description": "版の競合"},
                        428: {"description": "If-Match が未指定"}})
    def editor_update(identity: PresetId, draft: edit_request, if_match: Revision = None):
        """保存済みプリセットの版が開いた時点と一致する場合に更新します。"""
        return library.save(identity, validated(draft.spec), draft.tags, create=False, expected=if_match)

    @router.delete("/{identity}", summary="保存済みプリセットを削除", tags=PRESET_TAG, response_model=DeletedPreset,
                responses={403: {"description": "同梱プリセット"}, 412: {"description": "版の競合"},
                           428: {"description": "If-Match が未指定"}})
    def editor_delete(identity: PresetId, if_match: Revision = None):
        """指定された保存済みプリセットだけを削除します。接続設定や実行履歴は保持します。"""
        library.delete(identity, if_match)
        return {"id": identity, "deleted": True}

    app.include_router(router)
