"""プリセットの生成コマンドと配布ファイルのずれを検出する。"""

import tomllib
from pathlib import Path

from scripts.build_presets import write_library
from scripts.export_contracts import JOB_KINDS, export_contracts


def test_preset_generators_reproduce_the_shipped_library(tmp_path):
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    kind = JOB_KINDS[project["project"]["name"]]
    write_library(kind, tmp_path)
    if kind == "files":
        from scripts.build_document_presets import build

        build(tmp_path)

    shipped = root / "presets"
    assert sorted(p.name for p in tmp_path.glob("*.json")) == sorted(
        p.name for p in shipped.glob("*.json")
    )
    for path in sorted(tmp_path.iterdir()):
        assert path.read_bytes() == (shipped / path.name).read_bytes(), path.name


def test_shipped_contracts_match_the_management_schema():
    root = Path(__file__).resolve().parents[1]
    export_contracts(root / "contracts", check=True)
