"""管理APIとヘルプが使う注釈付きスキーマを契約ファイルに書き出す。"""

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from helptext import annotated_schemas  # noqa: E402


JOB_KINDS = {
    "factory-sql-data-loader": "sql",
    "factory-file-generator": "files",
    "factory-stream-simulator": "stream",
}


def export_contracts(directory: Path, *, check: bool = False) -> None:
    """配布用JSONを生成する。検査時に差分があれば書き換えず終了する。"""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    schemas = annotated_schemas(JOB_KINDS[project["project"]["name"]])
    paths = {
        directory / "preset.schema.json": schemas["run"],
        directory / "connection.schema.json": schemas["connection"],
    }
    stale = []
    if not check:
        directory.mkdir(parents=True, exist_ok=True)
    for path, schema in paths.items():
        expected = json.dumps(schema, ensure_ascii=False, indent=2) + "\n"
        if check:
            if not path.is_file() or path.read_bytes() != expected.encode("utf-8"):
                stale.append(str(path))
        else:
            path.write_text(expected, encoding="utf-8")
    if stale:
        raise SystemExit("契約スキーマの再生成が必要: " + ", ".join(stale))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="配布契約との差分だけを確認")
    args = parser.parse_args()
    export_contracts(ROOT / "contracts", check=args.check)
