import base64
import json
import re
from html import escape
from pathlib import Path
from typing import Any

import quickjs
from markdown_it import MarkdownIt
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin

KATEX_DIR = Path(__file__).parent / "katex"
KATEX_SCRIPT = (KATEX_DIR / "katex.min.js").read_text(encoding="utf-8")
LABELS = {
    "definition": "Определение",
    "theorem": "Теорема",
    "formula": "Формула",
    "example": "Пример",
    "important": "Важно",
}


def katex_css() -> str:
    css = (KATEX_DIR / "katex.min.css").read_text(encoding="utf-8")

    def embed(match: re.Match[str]) -> str:
        path = KATEX_DIR / "fonts" / match.group(1)
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"url(data:application/octet-stream;base64,{encoded})"

    return re.sub(r"url\(fonts/([^/)]+)\)", embed, css)


def render_summary(source: str) -> str:
    context = quickjs.Context()
    context.set_memory_limit(64 * 1024 * 1024)
    context.set_time_limit(1)
    context.eval(KATEX_SCRIPT)

    def render_math(content: str, options: dict[str, Any]) -> str:
        settings = {
            "displayMode": options["display_mode"],
            "throwOnError": False,
            "trust": False,
            "output": "html",
        }
        try:
            script = f"katex.renderToString({json.dumps(content)}, {json.dumps(settings)})"
            return context.eval(script)
        except (quickjs.JSException, MemoryError):
            return escape(content)

    def make_container(kind: str, label: str):
        def render(_renderer: Any, tokens: Any, index: int, _options: Any, _env: Any) -> str:
            if tokens[index].nesting == 1:
                return (
                    f'<section class="summary-callout summary-callout--{kind}">'
                    f'<p class="summary-callout__title">{label}</p>'
                )
            return "</section>\n"

        return render

    markdown = MarkdownIt("commonmark", {"html": False}).enable("table")
    markdown.disable("image")
    markdown.use(dollarmath_plugin, renderer=render_math, allow_labels=False)
    for kind, label in LABELS.items():
        markdown.use(container_plugin, kind, render=make_container(kind, label))
    return markdown.render(source)
