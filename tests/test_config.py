import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from config import ConnectionProfile, FieldRule, RunSpec
from factorylib import Runtime, create_app
from generation import (
    GenerationError,
    batch_limit,
    encode_json,
    generate_record,
    map_json,
    render,
    validate_generation,
)
from helptext import annotated_schemas
from storage import ConfigStore


def test_reproducible_and_split_sequences():
    spec = RunSpec()
    a = [generate_record(spec, i) for i in range(30)]
    assert a == [generate_record(spec, i) for i in range(15)] + [
        generate_record(spec, i) for i in range(15, 30)
    ]
    assert len({r["id"] for r in a}) == 30
    assert generate_record(spec.model_copy(update={"seed": 44}), 0) != a[0]


def test_custom_conditions_derived_values_and_nested_json():
    spec = RunSpec(
        parameters={"states": ["OK", "NG"], "quantity": 12},
        fields=[
            FieldRule(
                name="status", generator="choice", choices="$states", weights=[0, 1]
            ),
            FieldRule(
                name="a", data_type="integer", generator="constant", value="$quantity"
            ),
            FieldRule(
                name="b",
                data_type="integer",
                generator="sequence",
                start=2,
                group_size=2,
                modulo=3,
            ),
            FieldRule(
                name="total",
                data_type="number",
                generator="product",
                sources=["a", "b"],
            ),
            FieldRule(
                name="result",
                generator="constant",
                value="pass",
                condition={"field": "status", "value": "NG", "then_value": "reject"},
            ),
        ],
    )
    row = generate_record(spec, 7)
    assert row == {"status": "NG", "a": 12, "b": 2, "total": 24.0, "result": "reject"}
    assert map_json(
        {"value": "$row.total", "inner": ["$parameters.quantity", "$meta.record_key"]},
        row,
        spec.parameters,
        {"record_key": "abc"},
    ) == {"value": 24.0, "inner": [12, "abc"]}


@pytest.mark.parametrize(
    "template", ["{x.__class__}", "{x[0]}", "{x!r}", "{x:999999d}"]
)
def test_templates_cannot_execute_or_allocate_arbitrary_formats(template):
    with pytest.raises(GenerationError):
        render(template, {"x": "abc"})


def test_nullable_decimal_and_timezone():
    spec = RunSpec(
        fields=[
            FieldRule(name="n", generator="constant", value="v", null_probability=1),
            FieldRule(
                name="money",
                data_type="decimal",
                generator="constant",
                value="123456789012345678901234567890.1234",
                precision=38,
                scale=4,
            ),
            FieldRule(
                name="at",
                data_type="datetime",
                generator="timestamp",
                start="2026-11-13T09:00:00+09:00",
                step=2,
            ),
        ]
    )
    row = generate_record(spec, 2)
    assert (
        row["n"] is None
        and row["money"].endswith(".1234")
        and row["at"] == "2026-11-13T00:00:04+00:00"
    )


def test_bad_references_and_invalid_primary_keys():
    with pytest.raises(ValidationError):
        RunSpec(fields=[FieldRule(name="same"), FieldRule(name="SAME")])
    with pytest.raises(ValidationError):
        FieldRule(name="id", primary_key=True, null_probability=0.1)
    with pytest.raises(GenerationError):
        validate_generation(
            RunSpec(
                fields=[FieldRule(name="a", generator="reference", sources=["missing"])]
            )
        )
    with pytest.raises(GenerationError):
        generate_record(RunSpec(fields=[FieldRule(name="a", generator="choice")]), 0)
    with pytest.raises(GenerationError):
        encode_json({"large": "x" * 1048577})
    with pytest.raises(GenerationError):
        map_json("$row.missing", {}, {}, {})
    assert batch_limit(RunSpec(rows=100000000), 1000) <= 1000


def test_profiles_encrypted_revisioned_and_never_export_secrets(tmp_path):
    store = ConfigStore(tmp_path / "vault")
    profile = ConnectionProfile(
        id="api",
        name="API",
        kind="http",
        url="https://example.test/events",
        bearer_token="private-credential-value",
        auth_mode="bearer",
        headers={"X-Tenant": "private-header-value"},
    )
    public = store.save_profile(profile)
    assert "private-" not in json.dumps(public)
    assert b"private-" not in store.db.read_bytes()
    changed = profile.model_copy(
        update={"bearer_token": None, "headers": {"X-Tenant": None}}
    )
    store.save_profile(changed)
    assert (
        store.get_profile("api")[0].bearer_token.get_secret_value()
        == "private-credential-value"
    )
    assert (
        store.get_profile("api", 1)[0].headers["X-Tenant"].get_secret_value()
        == "private-header-value"
    )
    changed.url = "https://another.test/events"
    store.save_profile(changed)
    assert (
        store.get_profile("api")[0].bearer_token is None
        and not store.get_profile("api")[0].headers
    )
    assert ConfigStore(tmp_path / "vault").get_profile("api")[1] == 3
    assert (tmp_path / "vault/connection-v2.key").stat().st_mode & 0o777 == 0o600
    store.save_profile(profile.model_copy(update={"clear_secrets": ["bearer_token"]}))
    assert store.get_profile("api")[0].bearer_token is None


def test_complete_inline_help():
    for schema in annotated_schemas().values():
        for model in [schema, *schema.get("$defs", {}).values()]:
            for prop in model.get("properties", {}).values():
                assert prop["title"] and len(prop["description"]) > 8


def test_api_without_login_csrf_profile_preset_roundtrip_and_no_secret_echo(tmp_path):
    adapter = SimpleNamespace(
        handle=lambda *a: None, test_connection=lambda p: {"status": "ok"}
    )
    app = create_app("stream", "Test", adapter)
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/api/info").status_code == 200
        for path in ["/", "/static/app.js", "/metrics"]:
            response = c.get(path)
            assert response.status_code == 200
            assert "www-authenticate" not in response.headers
        assert (
            c.post(
                "/api/preview", json={}, headers={"Origin": "https://attacker.test"}
            ).status_code
            == 403
        )
        response = c.post(
            "/api/connections",
            json={
                "id": "test",
                "name": "test",
                "kind": "http",
                "url": "invalid",
                "bearer_token": "secret-echo-test",
            },
        )
        assert response.status_code == 422 and "secret-echo-test" not in response.text
        spec = RunSpec(
            name="Custom",
            rows=3,
            parameters={"custom": "設定"},
            fields=[FieldRule(name="arbitrary", generator="constant", value="$custom")],
        ).model_dump(mode="json")
        preview = c.post("/api/preview", json=spec).json()
        assert (
            preview["writes"] is False and preview["records"][0]["arbitrary"] == "設定"
        )
        assert c.post("/api/presets/mine", json=spec).status_code == 200
        assert c.get("/api/presets/mine/export").json() == spec
        assert "接続" in c.get("/api/schemas").text
        r = c.post("/api/runs", json=spec)
        assert r.status_code == 202
        identity = r.json()["id"]
        for _ in range(100):
            job = c.get("/api/runs/" + identity).json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        assert job["status"] == "completed" and job["spec"]["connection_revision"] == 1
    assert app.state.config_store.get_preset("mine")["spec"] == spec


def test_restart_recovers_history_and_marks_active_interrupted():
    runtime = Runtime("test", lambda *a: None, 100000000)
    with runtime.connect() as conn:
        conn.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
            ("old", "running", "{}", "{}", "[]", None, "t", "t"),
        )
    recovered = Runtime("test", lambda *a: None, 100000000)
    assert recovered.get("old")["status"] == "interrupted"


def test_shipped_preset_library_validates_and_preserves_user_edits(tmp_path):
    from scripts.build_presets import library
    from pathlib import Path

    import tomllib

    name = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["project"]["name"]
    values = library(
        {
            "factory-mes-erp-simulator": "sql",
            "factory-file-generator": "files",
            "factory-stream-simulator": "stream",
        }[name]
    )
    assert len(values) == 48
    for spec in values.values():
        validate_generation(spec)
    store = ConfigStore(tmp_path / "library")
    preset_dir = Path(__file__).resolve().parents[1] / "presets"
    store.seed_presets(preset_dir)
    saved = store.get_preset(
        "05-" + next(p.stem.split("-", 1)[1] for p in preset_dir.glob("05-*.json"))
    )
    spec = RunSpec.model_validate(saved["spec"])
    spec.description = "user edit"
    store.save_preset(saved["id"], spec)
    store.seed_presets(preset_dir)
    assert store.get_preset(saved["id"])["spec"]["description"] == "user edit"


def test_decimal_arithmetic_keeps_large_exact_values():
    spec = RunSpec(
        fields=[
            FieldRule(
                name="price",
                data_type="decimal",
                generator="constant",
                value="12345678901234567890.12",
                precision=24,
                scale=2,
            ),
            FieldRule(
                name="quantity", data_type="integer", generator="constant", value=3
            ),
            FieldRule(
                name="amount",
                data_type="decimal",
                generator="product",
                sources=["price", "quantity"],
                precision=26,
                scale=2,
            ),
        ]
    )
    assert generate_record(spec, 0)["amount"] == "37037036703703703670.36"


def test_anomalies_are_deterministic_scheduled_and_can_omit_values():
    from config import AnomalyRule

    spec = RunSpec(
        rows=50,
        anomalies=[
            AnomalyRule(
                name="spike",
                field="value",
                operation="set",
                value=250,
                from_row=20,
                to_row=29,
            )
        ],
    )
    assert generate_record(spec, 19)["value"] != 250
    trace = []
    assert generate_record(spec, 20, trace=trace)["value"] == 250 and trace == ["spike"]
    assert generate_record(spec, 30)["value"] != 250
    spec.anomalies = [
        AnomalyRule(field="value", operation="freeze", from_row=10, to_row=20)
    ]
    assert generate_record(spec, 10)["value"] == generate_record(spec, 20)["value"]
    spec.anomalies = [AnomalyRule(field="value", operation="omit", from_row=0)]
    assert "value" not in generate_record(spec, 0)
    spec.anomalies = [AnomalyRule(field="value", value="N/A", bypass_validation=True)]
    assert generate_record(spec, 0)["value"] == "N/A"


def test_published_json_contract_includes_current_anomaly_and_fault_settings():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "contracts/preset.schema.json").read_text())
    assert (
        schema["properties"]["anomalies"]
        == annotated_schemas()["run"]["properties"]["anomalies"]
    )
    assert (
        schema["$defs"]["FaultOptions"]
        == annotated_schemas()["run"]["$defs"]["FaultOptions"]
    )
