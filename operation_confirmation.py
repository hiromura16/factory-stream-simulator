"""Require confirmation of the exact write and the selected destination revision."""

import hashlib
import json
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, ValidationError

CONFIRMATION_HEADER = "X-Operation-Confirmation"
PLAN_PATH = "/api/operations/plan"
POLICY = {
    "files": ("/api/runs",),
    "sql": ("/api/runs", "/api/table/prepare"),
    "stream": ("/api/runs", "/api/outbox/retry"),
    "equipment": ("/api/start",),
    "api": ("/api/start",),
    "historian": ("/api/start",),
    "logs": ("/api/start",),
    "identification": ("/api/start",),
}
JOB_KINDS = {"files", "sql", "stream"}
TTL_SECONDS = 120
MAX_PENDING = 256
CONFIRMATION_ERRORS = {
    "confirmation_required": "操作の確認が必要です。計画で接続先と操作を確認してください。",
    "confirmation_invalid": "確認を利用できません。未発行・使用済みなどの場合は、確認計画を作り直してください。",
    "confirmation_expired": "確認の有効期限が切れました。確認計画を作り直してください。",
    "confirmation_mismatch": "操作・設定・接続先の版のいずれかが確認計画と異なります。現在の内容で確認し直してください。",
}
SOURCE_PATHS = ("/source/rest/", "/source/odata/", "/source/history/")
HTTP_METHODS = ("GET", "POST", "PATCH", "DELETE")


class OperationPlan(BaseModel):
    path: str = Field(description="確認する操作のパス。クエリ文字列は含めません。")
    payload: dict = Field(description="実行時に送る設定JSON。")
    force_confirmation: bool = Field(default=False, description="確認が任意の操作でもトークンを発行します。")
    profile_revision: int | None = Field(
        default=None, ge=1, description="ログの開始時に指定する出力先の版。"
    )


@dataclass(frozen=True)
class Operation:
    required: bool
    revision: int
    fingerprint: str
    summary: dict


def equipment_listeners(spec, profile):
    """Describe the protocols that the equipment driver will listen on."""
    listeners = []
    if profile.opc_enabled:
        listeners.append({
            "protocol": "OPC UA",
            "address": f"opc.tcp://0.0.0.0:{profile.opc_port}/factory/",
            "auth_mode": profile.opc_auth,
            "security": profile.opc_security,
            "writable": spec.equipment.writable,
        })
    if profile.modbus_enabled:
        listeners.append({
            "protocol": "Modbus TCP",
            "address": f"0.0.0.0:{profile.modbus_port}",
            "auth_mode": "none",
            "writable": spec.equipment.writable,
        })
    return listeners


class OperationGate:
    """Resolve immutable destination revisions and issue bounded, single-use tokens."""

    def __init__(self, kind, store, app):
        self.kind = kind
        self.store = store
        self.app = app
        self.pending = OrderedDict()
        self.lock = Lock()

    def source_api(self, spec, profile):
        """Summarize registered data routes and the selected profile's access rules."""
        methods_by_path = {}
        for route in self.app.routes:
            if isinstance(route, APIRoute) and route.path.startswith(SOURCE_PATHS):
                methods_by_path.setdefault(route.path, set()).update(route.methods)
        methods = HTTP_METHODS if profile.allow_writes else ("GET",)
        return {
            "auth_mode": profile.auth_mode,
            "resources": [resource.name for resource in spec.business.resources],
            "paths": [
                {"path": path, "methods": [method for method in methods if method in registered]}
                for path, registered in methods_by_path.items()
                if any(method in registered for method in methods)
            ],
        }

    def assess(self, path, spec, requested_revision=None):
        """Read a destination snapshot and derive its confirmation requirements."""
        if path not in POLICY[self.kind]:
            raise HTTPException(422, "この操作は確認プランの対象外です。")
        if self.kind in JOB_KINDS:
            identity = spec.connection_id
            revision = requested_revision if requested_revision is not None else getattr(spec, "connection_revision", None)
            load = self.store.get_profile
        else:
            identity = spec.profile_id
            revision = requested_revision
            load = self.store.profile
        try:
            profile, actual_revision = load(identity, revision)
        except KeyError:
            raise HTTPException(404, "指定された接続先または出力先の版が見つかりません。") from None

        label = {"api": "業務APIを公開", "equipment": "設備を公開",
                 "historian": "履歴を生成・公開", "logs": "ログを出力",
                 "identification": "読取イベントを生成",
                 "files": "ファイルを出力", "stream": "イベントを送信",
                 "sql": "データベースに書き込み"}[self.kind]
        output = getattr(profile, "kind", None) if self.kind in JOB_KINDS else getattr(profile, "output", None)
        summary = {
            "operation": label, "destination_id": identity,
            "destination_name": profile.name, "revision": actual_revision,
        }
        if self.kind == "equipment":
            summary["listeners"] = equipment_listeners(spec, profile)
        elif self.kind in {"api", "historian"}:
            summary["source_api"] = self.source_api(spec, profile)
        elif output:
            summary["destination_kind"] = output
        if self.kind in JOB_KINDS:
            summary["rows"] = spec.limit if path == "/api/outbox/retry" else spec.rows
        elif hasattr(spec, "max_ticks"):
            summary["max_ticks"] = spec.max_ticks
            if self.kind == "historian":
                summary["initial_samples"] = spec.history.initial_samples
        if self.kind == "sql":
            action = "create_table" if path == "/api/table/prepare" else spec.sql.operation
            summary.update(
                operation=action,
                table=f"{spec.sql.schema_name}.{spec.sql.table}" if spec.sql.schema_name else spec.sql.table,
            )
            required = action != "insert" or output != "sqlite"
        elif self.kind == "files":
            required = output != "local"
        elif self.kind == "stream":
            required = output != "capture"
            if path == "/api/outbox/retry":
                summary["operation"] = "イベントを再送"
        elif self.kind in {"logs", "identification"}:
            required = output != "capture"
        else:
            required = True

        binding = json.dumps(
            [self.kind, path, actual_revision, spec.model_dump(mode="json")],
            sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        )
        signature = hashlib.sha256(binding.encode()).hexdigest()
        return Operation(required, actual_revision, signature, summary)

    def issue(self, operation):
        """Create a short-lived authorization bound to the submitted data."""
        with self.lock:
            now = time.monotonic()
            # Retain expired entries within the bound so an old token can
            # still be distinguished from a different or consumed one.
            if len(self.pending) >= MAX_PENDING:
                self.pending.popitem(last=False)
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now + TTL_SECONDS, operation.fingerprint)
            return token

    def require(self, operation, token):
        """Consume only a token that authorizes the exact operation."""
        if not operation.required and token is None:
            return
        with self.lock:
            stored = self.pending.get(token) if token else None
            if token is None:
                code = "confirmation_required"
            elif stored is None:
                code = "confirmation_invalid"
            elif stored[0] <= time.monotonic():
                code = "confirmation_expired"
            elif stored[1] != operation.fingerprint:
                code = "confirmation_mismatch"
            else:
                self.pending.pop(token)
                return
        raise HTTPException(428, [{
            "loc": ["header", CONFIRMATION_HEADER],
            "location": "実行前の確認",
            "type": "operation_confirmation",
            "code": code,
            "msg": CONFIRMATION_ERRORS[code],
        }])


def install_operation_gate(app: FastAPI, kind, store, spec_model, retry_model=None, *, validate=None):
    """Register the side-effect-free plan API and return the gate used by writes."""
    gate = OperationGate(kind, store, app)

    @app.post(
        PLAN_PATH,
        summary="実行前に操作と接続先を確認する",
        tags=["実行・出力"],
        responses={404: {"description": "指定した接続先または版が見つかりません。"}},
    )
    def plan(request: OperationPlan):
        """変更は行いません。操作と接続先の版を返し、必要時は確認トークンを発行します。"""
        if request.path not in POLICY[kind] or (
            request.profile_revision is not None and kind != "logs"
        ):
            raise HTTPException(422, "操作のパスまたは出力先の版を確認してください。")
        model = retry_model if request.path == "/api/outbox/retry" else spec_model
        try:
            spec = model.model_validate(request.payload)
        except ValidationError as exc:
            details = [dict(error, loc=("body", "payload", *error["loc"])) for error in exc.errors()]
            raise RequestValidationError(details, body=request.model_dump()) from None
        operation = gate.assess(request.path, spec, request.profile_revision)
        if validate is not None:
            validate(spec, operation.revision)
        issue_token = operation.required or request.force_confirmation
        return {
            "confirmation_required": operation.required,
            "confirmation_token": gate.issue(operation) if issue_token else None,
            "expires_in": TTL_SECONDS if issue_token else None,
            "summary": operation.summary,
        }

    return gate
