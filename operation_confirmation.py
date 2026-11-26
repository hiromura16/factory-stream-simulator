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


class OperationGate:
    """Resolve immutable destination revisions and issue bounded, single-use tokens."""

    def __init__(self, kind, store):
        self.kind = kind
        self.store = store
        self.pending = OrderedDict()
        self.lock = Lock()

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
        if output:
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
            while self.pending:
                first = next(iter(self.pending))
                if self.pending[first][0] > now and len(self.pending) < MAX_PENDING:
                    break
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
            if stored and stored[0] > time.monotonic() and stored[1] == operation.fingerprint:
                self.pending.pop(token)
                return
        raise HTTPException(
            428, "操作の確認が必要です。計画で接続先と操作を確認してから実行してください。"
        )


def install_operation_gate(app: FastAPI, kind, store, spec_model, retry_model=None, *, validate=None):
    """Register the side-effect-free plan API and return the gate used by writes."""
    gate = OperationGate(kind, store)

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
