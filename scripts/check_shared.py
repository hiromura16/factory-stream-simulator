"""同期している共通ファイルの意図しない差分を検出する。"""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    """ファイルのSHA-256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root, expected):
    """リポジトリに保存された共通ファイルを検証する。"""
    return [
        name
        for name, value in expected.items()
        if not (root / name).is_file() or digest(root / name) != value
    ]


def main():
    """このリポジトリと、手元にある任意の他アプリを照合する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("peers", nargs="*", type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "docs/shared-components.json").read_text())
    failures = []
    for repo in [ROOT, *args.peers]:
        failures.extend(f"{repo.name}/{name}" for name in check(repo, manifest))
    if failures:
        raise SystemExit("共通ファイルの差分: " + ", ".join(failures))


if __name__ == "__main__":
    main()
