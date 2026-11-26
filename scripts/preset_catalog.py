"""配布プリセットのJSONから、READMEとアプリのヘルプで使う一覧を作る。"""

import json
import re
from collections import Counter
from pathlib import Path


CONTENT_HEADINGS = (
    "発生するデータ・タイミング",
    "このプリセットの内容",
    "生成内容・条件",
    "生成内容",
)


def read_sections(description: str) -> dict[str, str]:
    """説明の見出しと本文を、記載された順序で取り出す。"""
    return {
        label: content.strip()
        for label, content in re.findall(
            r"^【([^\n】]+)】\s*\n(.*?)(?=^【|\Z)", description, re.M | re.S
        )
    } or {"内容": description.strip()}


def overview(sections: dict[str, str]) -> str:
    """一覧の概要には、導入文よりも生成データの条件を優先する。"""
    return next(
        (sections[label] for label in CONTENT_HEADINGS if sections.get(label)),
        next(iter(sections.values())),
    )


def write_catalog(directory: Path) -> None:
    """保存済み設定から各ひな型の違いを示す概要と詳細を出力する。"""
    presets = []
    for path in sorted(directory.glob("*.json")):
        preset = json.loads(path.read_text(encoding="utf-8"))
        sections = read_sections(preset["description"])
        presets.append((path, preset, sections, overview(sections)))

    continuous = bool(presets and "max_ticks" in presets[0][1])
    count_heading = "最大tick数" if continuous else "元の件数"
    rows = [
        "# 付属のひな型一覧",
        "",
        "迷ったときは[ひな型を選ぶ・作る](../docs/preset-guide.md)を参照してください。",
        "アプリで保存したひな型はアプリの一覧から開きます。",
        "",
        f"| ID | 表示名 | {count_heading} | 生成する内容 |",
        "| --- | --- | --- | --- |",
    ]
    details = ["", "## ひな型ごとの内容"]
    line_frequency = Counter(
        line.strip() for _, _, _, content in presets for line in content.splitlines()
    )
    for path, preset, sections, content in presets:
        identity, name = path.stem, preset["name"]
        if continuous:
            unique_lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and line_frequency[line.strip()] == 1
            ]
            # 条件の差が別の設定項目にしかない場合は、ひな型に記載された目的を示す。
            scenario = sections.get("想定", name).split("。", 1)[-1]
            summary = " ".join(unique_lines[:2]) or scenario
            count = preset["max_ticks"] or "手動停止まで"
        else:
            # 件数は専用列に表示し、生成条件の後ろにある定型文は概要から外す。
            overview_text = " ".join(content.split()).split(" 件数", 1)[0]
            if overview_text.startswith("同じ汎用項目を使用し、件数・速度・バッチを段階的に変更する負荷試験。"):
                rate = preset["target_rate"]
                speed = f"目標速度 {rate:,}件/秒" if rate else "速度の上限なし"
                summary = f"{speed}、1バッチ {preset['batch_size']:,}件で試す"
            else:
                summary = overview_text
            count = preset["rows"]

        summary = " ".join(summary.split()).rstrip("。")
        if len(summary) > 120:
            summary = summary[:120].rstrip() + "…"
        table_name = name.replace("|", r"\|")
        table_summary = summary.replace("|", r"\|")
        rows.append(f"| [{identity}](#{identity}) | {table_name} | {count} | {table_summary} |")
        details.extend(
            [
                "",
                f"### {identity}",
                "",
                f"**{name}** · [JSONをダウンロード]({path.name})",
                "",
            ]
        )
        details.extend(
            f"- **{label}**　{' '.join(text.split())}"
            for label, text in sections.items()
            if text
        )
    (directory / "README.md").write_text("\n".join(rows + details) + "\n", encoding="utf-8")
