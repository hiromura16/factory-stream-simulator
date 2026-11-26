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
    repos = [ROOT, *args.peers]
    failures = []
    groups = {
        "shared-components.json": repos,
        "shared-studio-components.json": [repo for repo in repos if (repo / "studio.py").is_file()],
    }
    for filename, members in groups.items():
        canonical = None
        for repo in members:
            manifest_path = repo / "docs" / filename
            if not manifest_path.is_file():
                failures.append(f"{repo.name}/docs/{filename}")
                continue
            manifest = json.loads(manifest_path.read_text())
            if canonical is None:
                canonical = manifest
            elif manifest != canonical:
                failures.append(f"{repo.name}/docs/{filename}")
            failures.extend(f"{repo.name}/{name}" for name in check(repo, canonical))
    if failures:
        raise SystemExit("共通ファイルの差分: " + ", ".join(failures))


if __name__ == "__main__":
    main()
