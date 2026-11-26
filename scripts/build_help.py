"""リポジトリの Markdown と公開設定スキーマから組み込みヘルプを生成する。"""

import argparse
import json
import re
import sys
from html import escape
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PAGES = {
    "index": ("初めて使う", "user-manual.md"),
    "presets": ("ひな型を選ぶ・作る", "preset-guide.md"),
    "templates": ("JSONの書き方", "template-guide.md"),
    "settings": ("設定リファレンス", "settings-reference.md"),
    "api": ("APIの使い方", "api-guide.md"),
    "glossary": ("用語集", "glossary.md"),
    "ai": ("AIにひな型を頼む", "AI_TEMPLATE_HARNESS.md"),
    "install": ("VMへの導入", "vm-compose.md"),
    "catalog": ("付属のひな型一覧", "../presets/README.md"),
}
LINKS = {filename: f"/help/{page}.html" for page, (_, filename) in PAGES.items()}
LINKS.update(
    {
        "../README.md": "/",
        "README.md": "/",
        "../docs/preset-guide.md": "/help/presets.html",
    }
)
BACK_LINK = "アプリに戻る"
FAMILIES = {"files", "sql", "stream"}
SECTIONS = {
    "FieldRule": "項目と値の生成方法",
    "Condition": "値を上書きする条件",
    "AnomalyRule": "異常データの条件",
    "Predicate": "異常を適用する条件",
    "FaultOptions": "実行処理の障害",
    "FileOptions": "ファイルの形式と完了通知",
    "ImageOptions": "画像の生成",
    "SqlOptions": "SQLの書き込み",
    "StreamOptions": "本文と配送",
    "RunSpec": "データの生成条件",
    "Equipment": "設備と通信異常",
    "Register": "Modbusレジスター",
    "Business": "業務APIと模擬障害",
    "Resource": "コレクション",
    "History": "履歴と品質",
    "Logs": "ログ形式とローテーション",
    "Identification": "タグと読取経路",
}
KIND_GROUP = {
    "equipment": "equipment",
    "api": "business",
    "historian": "history",
    "logs": "logs",
    "identification": "identification",
}
DEFS = "#/$defs/"
STUDIO_UNUSED = {
    "FileOptions",
    "ImageOptions",
    "SqlOptions",
    "StreamOptions",
    "FaultOptions",
}


def display(value):
    """JSON値を契約で使う表記のまま表示する。"""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def shape(prop):
    """型の選択肢、配列の要素型、参照先を表示する。"""
    if "$ref" in prop:
        target = prop["$ref"].removeprefix(DEFS)
        return f"{SECTIONS.get(target, target)}（{target}）"
    if "anyOf" in prop:
        return " / ".join(shape(item) for item in prop["anyOf"])
    if prop.get("type") == "array":
        return "配列［" + shape(prop.get("items", {})) + "］"
    return {
        "object": "オブジェクト",
        "string": "文字列",
        "integer": "整数",
        "number": "数値",
        "boolean": "真偽値",
        "null": "null",
    }.get(prop.get("type"), "JSON値")


def rules(prop, required):
    """選択肢と入力制約を省略せずに表示する。"""
    constraints = [
        ("選択肢", "enum"),
        ("固定値", "const"),
        ("最小", "minimum"),
        ("最大", "maximum"),
        ("より大きい", "exclusiveMinimum"),
        ("より小さい", "exclusiveMaximum"),
        ("最小件数", "minItems"),
        ("最大件数", "maxItems"),
        ("最短", "minLength"),
        ("最長", "maxLength"),
        ("書式", "pattern"),
    ]
    lines = ["必須" if required else "省略可"]
    if "default" in prop and prop.get("format") != "password":
        lines.append(f"既定 {display(prop['default'])}")
    for part in [prop, *prop.get("anyOf", []), prop.get("items", {})]:
        for label, key in constraints:
            if key in part:
                value = part[key]
                encoded = (
                    " / ".join(display(option) for option in value)
                    if key == "enum"
                    else display(value)
                )
                lines.append(f"{label} {encoded}")
    return "。".join(dict.fromkeys(lines))


def table_cell(text):
    """複数行の説明を Markdown の表に収める。"""
    return str(text).replace("|", "\\|").replace("\n\n", "。").replace("\n", " ")


def group_rows(schema, prefix, family, applicable=True):
    """スキーマの各項目を、画面での利用範囲を含む参照表へ変換する。"""
    lines = ["| JSONキー | 画面名と用途 | 型・入力条件 |", "| --- | --- | --- |"]
    for key, prop in schema.get("properties", {}).items():
        name = prop.get("title", key)
        description = prop.get("description", "")
        if not description:
            raise ValueError(f"{prefix}.{key} に説明がありません")
        path = f"{prefix}.{key}" if prefix else key
        usage = ""
        if not applicable:
            usage = " **このアプリでは適用外。**"
        elif prop.get("ui_hidden"):
            usage = " **画面に表示されません。**"
        elif prop.get("writeOnly") or any(
            part.get("writeOnly") for part in prop.get("anyOf", [])
        ):
            usage = " **秘密値。**"
        if (
            family in FAMILIES
            and not prefix
            and key in FAMILIES | {"files"}
            and key != family
        ):
            usage = " **このアプリでは適用外。**"
        cells = (
            f"\x60{path}\x60",
            f"**{name}**　{description}{usage}",
            f"{shape(prop)}。{rules(prop, key in schema.get('required', []))}",
        )
        lines.append("| " + " | ".join(table_cell(cell) for cell in cells) + " |")
    return lines


def reference(kind):
    """公開スキーマを使用し、すべての設定プロパティの参照表を作る。"""
    if kind in FAMILIES:
        from helptext import annotated_schemas

        schemas = annotated_schemas(kind)
        areas = {"run": "実行ひな型", "connection": "接続先"}
        inactive = {
            "files": {"SqlOptions", "StreamOptions"},
            "sql": {"FileOptions", "ImageOptions", "StreamOptions"},
            "stream": {"FileOptions", "ImageOptions", "SqlOptions"},
        }[kind]
    else:
        from studio import schemas as studio_schemas

        schemas = studio_schemas(kind)
        areas = {"spec": "公開・生成ひな型", "profile": "公開・出力設定"}
        active = KIND_GROUP[kind]
        inactive = STUDIO_UNUSED | {
            name
            for key, names in {
                "equipment": ("Equipment", "Register"),
                "business": ("Business", "Resource"),
                "history": ("History",),
                "logs": ("Logs",),
                "identification": ("Identification",),
            }.items()
            if key != active
            for name in names
        }

    lines = [
        "# 設定リファレンス",
        "",
        "画面の表示名、JSONキー、意味、制約、既定値を確認できます。",
        "接続方式や選択した形式によって表示される設定が変わります。",
        "共通形式の別アプリ用の項目も掲載しています。該当する出力方式で使う設定を選んでください。",
        "",
        "[JSONの書き方](template-guide.md) · [ひな型の選び方](preset-guide.md)",
        "",
    ]
    for name, schema in schemas.items():
        lines += [f"## {areas[name]}", "", *group_rows(schema, "", kind), ""]
        for key, definition in schema.get("$defs", {}).items():
            lines += [
                f"### {SECTIONS.get(key, key)}（{key}）",
                "",
                *group_rows(definition, key, kind, applicable=key not in inactive),
                "",
            ]
    return "\n".join(lines)


def rewrite_links(tokens):
    """GitHub向け相対パスをアプリ内の同じページまたは画像に変換する。"""
    for token in tokens:
        if token.children:
            rewrite_links(token.children)
        attr = {"link_open": "href", "image": "src"}.get(token.type)
        if not attr:
            continue
        address = token.attrGet(attr)
        parsed = urlsplit(address)
        path = unquote(parsed.path)
        if parsed.hostname in {"127.0.0.1", "localhost"} and path in {
            "/docs",
            "/redoc",
            "/openapi.json",
        }:
            token.attrSet(attr, path)
            continue
        if parsed.scheme or parsed.netloc or path.startswith("/") or not path:
            continue
        if path.startswith("images/"):
            target = "/help/" + path
        elif path.startswith("examples/"):
            target = "/help/" + path
        elif re.fullmatch(r"[0-9][A-Za-z0-9_-]+\.json", path):
            target = "/help/preset-files/" + path
        elif path in LINKS:
            target = LINKS[path]
        else:
            continue
        token.attrSet(attr, target + ("#" + parsed.fragment if parsed.fragment else ""))
        if token.type == "image":
            token.attrSet("loading", "lazy")


def rendered(source):
    """リポジトリの Markdown を素のHTMLやスクリプトを許可せずに変換する。"""
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(source)
    rewrite_links(tokens)
    toc = []
    headings = {}
    for i, token in enumerate(tokens):
        if token.type != "heading_open" or token.tag not in {"h2", "h3"}:
            continue
        label = tokens[i + 1].content
        base = (
            re.sub(r"[^a-z0-9ぁ-ゖァ-ヺ一-龯]+", "-", label.lower()).strip("-")
            or "section"
        )
        headings[base] = headings.get(base, 0) + 1
        anchor = base if headings[base] == 1 else f"{base}-{headings[base]}"
        token.attrSet("id", anchor)
        if token.tag == "h2":
            toc.append((anchor, label))
    return md.renderer.render(tokens, md.options, {}), toc


def page_html(page, title, text):
    """共通のヘルプナビゲーションと、ページに応じた目次を付ける。"""
    content, sections = rendered(text)
    nav = []
    for key, (label, _) in PAGES.items():
        current = ' aria-current="page"' if key == page else ""
        nav.append(f'<a href="/help/{key}.html"{current}>{escape(label)}</a>')
    outline = "".join(
        f'<a href="#{escape(anchor)}">{escape(label)}</a>' for anchor, label in sections
    )
    outline = (
        f'<nav class="help-outline" aria-label="このページ">{outline}</nav>'
        if outline
        else ""
    )
    search = ""
    if page in {"settings", "catalog"}:
        search = (
            '<div class="help-search" hidden><label for="help-filter">表を検索</label>'
            '<input id="help-filter" type="search" placeholder="日本語、ID、JSONキー">'
            '<p id="help-results" role="status"></p></div>'
        )
    before_article = "".join(f"      {section}\n" for section in (outline, search) if section)
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(PAGES[page][0])} | {escape(title)}</title>
  <link rel="stylesheet" href="/static/style.css">
  <link rel="stylesheet" href="/static/help.css">
  <script src="/static/help.js" defer></script>
</head>
<body class="help-page">
  <a class="help-skip" href="#help-content">本文へ移動</a>
  <div class="help-top">
    <a class="help-home" href="/">{escape(title)}</a>
    <a href="/">{BACK_LINK}</a>
  </div>
  <div class="help-layout">
    <nav class="help-nav" aria-label="ヘルプ">{"".join(nav)}</nav>
    <main class="help-content" id="help-content">
{before_article}      <article>{content}</article>
    </main>
  </div>
</body>
</html>
"""


def build(check):
    """Markdown と組み込みヘルプに差分があれば書き出すか検証を失敗させる。"""
    config = json.loads((ROOT / "docs/help-site.json").read_text())
    directory = ROOT / "docs/help-site"
    directory.mkdir(exist_ok=True)
    settings = reference(config["kind"])
    files = {ROOT / "docs/settings-reference.md": settings}
    for page, (_, filename) in PAGES.items():
        source = (
            settings if page == "settings" else (ROOT / "docs" / filename).read_text()
        )
        files[directory / (page + ".html")] = page_html(page, config["title"], source)
    stale = []
    for path, expected in files.items():
        if not path.is_file() or path.read_text() != expected:
            if check:
                stale.append(str(path.relative_to(ROOT)))
            else:
                path.write_text(expected)
    if stale:
        raise SystemExit("再生成が必要: " + ", ".join(stale))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="生成済みファイルとの一致だけを確認"
    )
    build(parser.parse_args().check)
