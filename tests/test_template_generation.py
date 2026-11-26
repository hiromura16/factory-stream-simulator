"""生成エンジンとテンプレート入力契約の回帰テスト。"""

import pytest
from pydantic import ValidationError

from config import RunSpec
from generation import GenerationError, generate_record, validate_generation


@pytest.mark.parametrize("operation", ["add", "multiply", "ramp"])
def test_numeric_anomalies_skip_missing_or_non_numeric_values(operation):
    spec = RunSpec.model_validate({
        "rows": 4,
        "fields": [
            {"name": "missing", "data_type": "number", "value": 1, "null_probability": 1},
            {"name": "state", "value": "stopped"},
            {"name": "valid", "data_type": "number", "value": 7},
        ],
        "anomalies": [
            {"name": key, "field": key, "operation": operation, "value": 2}
            for key in ("missing", "state", "valid")
        ],
    })
    trace = []
    validate_generation(spec)
    row = generate_record(spec, 1, trace=trace)
    expected = 14 if operation == "multiply" else 9
    assert row == {"missing": None, "state": "stopped", "valid": expected}
    assert trace == ["valid"]


def test_numeric_anomaly_has_a_path_for_an_invalid_operand():
    spec = RunSpec.model_validate({
        "fields": [{"name": "maybe", "data_type": "number", "value": None}],
        "anomalies": [{"field": "maybe", "operation": "add", "value": "not a number"}],
    })
    with pytest.raises(GenerationError, match="数値") as hit:
        validate_generation(spec)
    assert hit.value.path == ("anomalies", 0, "value")
    assert "not a number" not in str(hit.value)


def test_nullable_comparisons_and_explicit_membership():
    spec = RunSpec.model_validate({
        "fields": [
            {"name": "maybe", "value": None},
            {
                "name": "simple", "value": "unchanged",
                "condition": {"field": "maybe", "operator": "gt", "value": 0, "then_value": "changed"},
            },
            {
                "name": "matched", "value": "initial",
                "condition": {"field": "maybe", "operator": "in", "value": [None], "then_value": "empty"},
            },
        ],
        "anomalies": [
            {
                "field": "simple", "operation": "set", "value": "changed",
                "when": {"field": "maybe", "operator": "le", "value": 42},
            },
        ],
    })
    assert generate_record(validate_generation(spec), 0) == {
        "maybe": None, "simple": "unchanged", "matched": "empty"
    }


def test_membership_rejects_a_scalar_with_a_path():
    rule = {"field": "first", "operator": "in", "value": "prefix"}
    definition = {
        "fields": [
            {"name": "first", "value": "pre"},
            {"name": "second", "value": "item", "condition": {**rule, "then_value": "matched"}},
        ],
    }
    with pytest.raises(GenerationError, match="配列") as hit:
        validate_generation(RunSpec.model_validate(definition))
    assert hit.value.path == ("fields", 1, "condition", "value")

    definition["fields"][1].pop("condition")
    definition["anomalies"] = [{"field": "second", "value": "matched", "when": rule}]
    with pytest.raises(GenerationError, match="配列") as hit:
        validate_generation(RunSpec.model_validate(definition))
    assert hit.value.path == ("anomalies", 0, "when", "value")


def test_string_sequences_omit_integral_dot_zero():
    spec = RunSpec.model_validate({
        "fields": [
            {"name": "code", "generator": "sequence", "start": "4.0", "step": 2},
            {"name": "fraction", "generator": "sequence", "step": 0.5},
        ],
    })
    assert generate_record(spec, 0) == {"code": "4", "fraction": "0"}
    assert generate_record(spec, 1) == {"code": "6", "fraction": "0.5"}


def test_editor_annotations_are_accepted_and_do_not_change_output():
    definition = {
        "fields": [{"name": "serial", "generator": "sequence", "step": 2}],
        "anomalies": [{"field": "serial", "operation": "set", "value": "0"}],
    }
    with_metadata = {
        "$schema": "../contracts/preset.schema.json",
        "_comment": "トップレベルのメモ",
        "fields": [{**definition["fields"][0], "_comment": "項目について"}],
        "anomalies": [{**definition["anomalies"][0], "_comment": "試験条件について"}],
    }
    original = RunSpec.model_validate(definition)
    annotated = RunSpec.model_validate(with_metadata)
    assert annotated.model_dump() == original.model_dump()
    assert generate_record(annotated, 0) == generate_record(original, 0)
    schema = RunSpec.model_json_schema()
    assert schema["properties"]["$schema"]["x-editor-only"]
    assert schema["$defs"]["FieldRule"]["properties"]["_comment"]["x-editor-only"]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        RunSpec.model_validate({**definition, "_coment": "キー名の誤記"})


def test_template_format_error_reports_the_affected_field():
    spec = RunSpec.model_validate({
        "fields": [
            {"name": "source", "generator": "sequence"},
            {"name": "text", "generator": "template", "template": "sample-{source:03d}"},
        ],
    })
    with pytest.raises(GenerationError) as hit:
        validate_generation(spec)
    assert hit.value.path == ("fields", 1, "template")


def test_other_output_options_can_be_loaded_and_used_by_their_own_tool():
    definition = {
        "rows": 2,
        "fields": [{"name": "serial", "generator": "sequence"}],
        "files": {
            "formats": ["json", "xlsx", "xml", "parquet", "avro", "pdf"],
            "completion_mode": "manifest-v2",
            "xlsx_sheet": "Imported sheet",
            "json_template": {"serial": "$row.serial"},
        },
        "stream": {
            "duplicate_rate": 1,
            "message_size_bytes": 512,
            "payload_template": {"body": "$row.serial"},
        },
    }
    spec = RunSpec.model_validate(definition)
    for kind in ("files", "sql", "stream"):
        validate_generation(spec, kind=kind)
    assert spec.model_dump()["files"]["xlsx_sheet"] == "Imported sheet"
    assert spec.model_dump()["stream"]["message_size_bytes"] == 512


def test_other_format_templates_do_not_affect_preview_validation():
    spec = RunSpec.model_validate({
        "fields": [{"name": "serial", "generator": "sequence"}],
        "files": {"formats": ["json"], "json_template": {"x": "$row.only_file"}},
        "stream": {"payload_template": {"y": "$row.only_stream"}},
    })
    validate_generation(spec, kind="sql")
    for kind, expected in (("files", "json_template"), ("stream", "payload_template")):
        with pytest.raises(GenerationError) as hit:
            validate_generation(spec, kind=kind)
        assert hit.value.path == (kind, expected)


def test_parameter_errors_identify_the_setting_that_references_them():
    sequence = RunSpec.model_validate({
        "fields": [{"name": "no", "generator": "sequence", "step": "$not_defined"}],
    })
    with pytest.raises(GenerationError) as error:
        validate_generation(sequence)
    assert error.value.path == ("fields", 0, "step")

    condition = RunSpec.model_validate({
        "fields": [
            {"name": "ready", "value": "ok"},
            {
                "name": "next_value",
                "condition": {
                    "field": "ready", "value": "ok", "then_value": "$not_defined",
                },
            },
        ],
    })
    with pytest.raises(GenerationError) as error:
        validate_generation(condition)
    assert error.value.path == ("fields", 1, "condition", "then_value")


def test_integer_sequence_does_not_round_large_values():
    spec = RunSpec.model_validate({
        "fields": [{"name": "serial", "generator": "sequence", "start": 2**53, "step": 1}],
    })
    assert generate_record(spec, 0)["serial"] == "9007199254740992"
    assert generate_record(spec, 1)["serial"] == "9007199254740993"


def test_numeric_boolean_and_timestamp_generators_accept_valid_conversion_inputs():
    spec = RunSpec.model_validate({
        "parameters": {"upper": 10.0, "step": 2.0},
        "fields": [
            {"name": "count", "generator": "integer", "data_type": "integer", "minimum": 9, "maximum": "$upper"},
            {"name": "reading", "generator": "uniform", "data_type": "number", "minimum": 4, "maximum": 4.5},
            {"name": "normal", "generator": "normal", "data_type": "number", "mean": 5, "stddev": 0},
            {"name": "healthy", "generator": "boolean", "data_type": "boolean", "probability": 1},
            {"name": "when", "generator": "timestamp", "data_type": "datetime", "start": "2026-01-01T00:00:00+00:00", "step": "$step"},
        ],
    })
    validate_generation(spec)
    record = generate_record(spec, 1)
    assert 9 <= record["count"] <= 10
    assert 4 <= record["reading"] <= 4.5
    assert record["normal"] == 5
    assert record["healthy"] is True
    assert record["when"] == "2026-01-01T00:00:02+00:00"


def test_offline_stream_validation_accepts_a_destination_supplied_topic():
    from scripts.validate_template import validate_template

    spec = validate_template({
        "rows": 3,
        "fields": [{"name": "serial", "generator": "sequence"}],
        "stream": {
            "payload_template": {"serial": "$row.serial"},
            "message_size_bytes": 512,
            "duplicate_rate": 1,
        },
    })
    assert spec.stream.topic_template == ""



def test_numeric_anomaly_warning_preserves_conversion_and_skips_disabled_rules():
    from generation import anomaly_warnings

    fields = [
        {"name": "text", "generator": "constant", "value": "label"},
        {"name": "numeric_text", "generator": "constant", "value": "2.5"},
        {
            "name": "number", "generator": "constant",
            "data_type": "integer", "value": 2,
        },
    ]
    anomalies = [
        {"name": "text", "field": "text", "operation": "ramp", "value": 1},
        {"name": "numeric_text", "field": "numeric_text", "operation": "add", "value": 1},
        {"name": "number", "field": "number", "operation": "multiply", "value": 2},
        {"name": "disabled", "field": "text", "operation": "multiply", "enabled": False},
        {"name": "never", "field": "text", "operation": "ramp", "probability": 0},
    ]
    spec = RunSpec.model_validate({"fields": fields, "anomalies": anomalies})
    warnings = anomaly_warnings(spec, prefix=("generator",))
    assert [warning["loc"] for warning in warnings] == [
        ["body", "generator", "anomalies", 0, "field"],
        ["body", "generator", "anomalies", 1, "field"],
    ]
    assert {warning["code"] for warning in warnings} == {"non_numeric_anomaly_field"}
    assert generate_record(spec, 1) == {"text": "label", "numeric_text": "3.5", "number": 4}


@pytest.mark.parametrize(
    "payload, path, code, message",
    [
        (
            {"fields": [{"name": "event_time", "generator": "timestamp",
                         "data_type": "datetime", "start": "not-a-date"}]},
            ("fields", 0, "start"), "invalid_datetime", "タイムゾーン付きISO 8601",
        ),
        (
            {"fields": [{"name": "v", "generator": "constant", "value": 17}],
             "anomalies": [{"name": "copied", "field": "v", "operation": "copy_from"}]},
            ("anomalies", 0, "value"), "copy_from_position_required", "0始まりの整数",
        ),
    ],
)
def test_generation_errors_offer_stable_code_and_specific_fix(payload, path, code, message):
    spec = RunSpec.model_validate(payload)
    with pytest.raises(GenerationError) as error:
        generate_record(spec, 0)
    assert error.value.path == path
    assert error.value.code == code
    assert message in str(error.value)
