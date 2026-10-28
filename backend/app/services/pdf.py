import asyncio
from html import escape
from zoneinfo import ZoneInfo

from weasyprint import CSS, HTML
from weasyprint.text.fonts import FontConfiguration

from app.core.config import get_settings
from app.models import Course, Lecture
from app.services.durations import format_duration
from app.services.summary_markdown import katex_css, render_summary

MOSCOW = ZoneInfo("Europe/Moscow")

FONT_CONFIG = FontConfiguration()
KATEX_STYLE = CSS(string=katex_css(), font_config=FONT_CONFIG)

STYLE = CSS(
    string="""
@page {
  size: A4;
  margin: 22mm 20mm 24mm;
  @bottom-left {
    content: string(lecture-title);
    font: 8.5pt Inter, "DejaVu Sans", sans-serif;
    color: #5b6270;
  }
  @bottom-right {
    content: counter(page) " из " counter(pages);
    font: 8.5pt Inter, "DejaVu Sans", sans-serif;
    color: #5b6270;
    font-variant-numeric: tabular-nums;
  }
}
html {
  font-family: Inter, "DejaVu Sans", sans-serif;
  font-size: 10.5pt;
  line-height: 1.5;
  color: #0f1115;
}
body { margin: 0; }
a { color: #1d5fbf; text-decoration: none; }
body > h1 {
  string-set: lecture-title content();
  font-size: 26pt;
  line-height: 1.08;
  letter-spacing: -0.02em;
  font-weight: 700;
  margin: 0 0 4mm;
}
.meta { color: #5b6270; margin: 0 0 12mm; }
h2 {
  font-size: 15pt;
  line-height: 1.25;
  letter-spacing: -0.01em;
  font-weight: 700;
  margin: 10mm 0 4mm;
  break-after: avoid;
}
h3, h4, h5, h6 {
  font-size: 10.5pt;
  font-weight: 700;
  margin: 6mm 0 2mm;
  break-after: avoid;
}
.summary h1, .summary h2 {
  font-size: 12.5pt;
  letter-spacing: 0;
  margin: 7mm 0 2.5mm;
}
p { margin: 0 0 3mm; }
.chapters {
  list-style: none;
  margin: 0;
  padding: 6mm 7mm;
  background: #f4f5f7;
}
.chapters li {
  position: relative;
  padding-left: 19mm;
  margin: 0 0 5mm;
  break-inside: avoid;
}
.chapters li:last-child { margin-bottom: 0; }
.chapters .time {
  position: absolute;
  left: 0;
  top: 0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.chapters .title { font-weight: 600; margin: 0; }
.chapters .title a { color: #0f1115; }
.chapters .about { color: #5b6270; margin: 1mm 0 0; }
.summary ul, .summary ol { margin: 0 0 3mm; padding-left: 6mm; }
.summary li { margin: 0 0 1.5mm; }
.summary li > ul, .summary li > ol { margin: 1.5mm 0 0; }
.summary blockquote {
  margin: 0 0 3mm;
  padding: 3mm 5mm;
  background: #f4f5f7;
}
.summary code {
  font-family: "DejaVu Sans Mono", monospace;
  font-size: 9pt;
  background: #eceef2;
  padding: 0 1mm;
}
.summary pre {
  break-inside: avoid;
  background: #eceef2;
  padding: 3mm 4mm;
  white-space: pre-wrap;
  margin: 0 0 3mm;
}
.summary pre code { background: none; padding: 0; }
.summary table { border-collapse: collapse; margin: 0 0 3mm; width: 100%; }
.summary th, .summary td {
  border: 0.5pt solid #c6cbd4;
  padding: 1.5mm 2.5mm;
  text-align: left;
  vertical-align: top;
}
.summary img { display: none; }
.summary-callout {
  margin: 0 0 4mm;
  padding: 3mm 5mm;
  border-left: 3pt solid #3880a0;
  background: #e5f0f4;
  break-inside: avoid;
}
.summary-callout--theorem { border-color: #5b69a2; background: #ebedf5; }
.summary-callout--formula { border-color: #a37826; background: #f4eee4; }
.summary-callout--example { border-color: #43875c; background: #e8f1eb; }
.summary-callout--important { border-color: #ad5b52; background: #f5eae9; }
.summary-callout__title { font-weight: 700; margin: 0 0 2mm; }
.summary-callout > :last-child { margin-bottom: 0; }
.tickets { margin: 0; padding-left: 7mm; }
.tickets li { margin: 0 0 2mm; padding-left: 1mm; break-inside: avoid; }
.tickets li::marker { font-weight: 600; font-variant-numeric: tabular-nums; }
.terms { margin: 0; }
.terms div {
  padding: 2.5mm 0;
  border-top: 0.5pt solid #c6cbd4;
  break-inside: avoid;
}
.terms div:last-child { border-bottom: 0.5pt solid #c6cbd4; }
.terms dt { font-weight: 700; margin: 0 0 1mm; }
.terms dd { margin: 0; color: #2b303a; }
.empty { color: #5b6270; }
"""
)


def format_timecode(total_seconds: float) -> str:
    seconds = max(0, int(total_seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def lecture_html(lecture: Lecture, base_url: str, lecture_url: str | None = None) -> str:
    lecture_url = lecture_url or f"{base_url}/lectures/{lecture.id}"
    meta = [lecture.created_at.astimezone(MOSCOW).strftime("%d.%m.%Y")]
    if lecture.duration_sec:
        meta.append(format_duration(max(lecture.duration_sec, 60), round_up=False))
    meta.append(f'<a href="{escape(lecture_url)}">Открыть в Lecturo</a>')

    parts = [
        f"<h1>{escape(lecture.title)}</h1>",
        f'<p class="meta">{" · ".join(meta)}</p>',
    ]
    if lecture.chapters:
        parts.append('<h2>Главы</h2><ol class="chapters">')
        for chapter in lecture.chapters:
            href = escape(f"{lecture_url}?t={int(chapter.start)}")
            about = f'<p class="about">{escape(chapter.summary)}</p>' if chapter.summary else ""
            parts.append(
                f'<li><a class="time" href="{href}">{format_timecode(chapter.start)}</a>'
                f'<p class="title"><a href="{href}">{escape(chapter.title)}</a></p>{about}</li>'
            )
        parts.append("</ol>")
    if lecture.summary is not None and lecture.summary.content_md.strip():
        parts.append(
            f'<h2>Конспект</h2><div class="summary">'
            f"{render_summary(lecture.summary.content_md)}</div>"
        )

    return (
        f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{escape(lecture.title)}</title></head><body>{''.join(parts)}</body></html>"
    )


def exam_sheet_html(course: Course, content: dict, base_url: str) -> str:
    sheet_url = f"{base_url}/courses/{course.id}/exam-sheet"
    tickets = [ticket for ticket in content.get("tickets", []) if ticket]
    definitions = [
        item
        for item in content.get("definitions", [])
        if item.get("term") and item.get("definition")
    ]
    cheatsheet = content.get("cheatsheet_md", "")

    parts = [
        f"<h1>{escape(course.title)}</h1>",
        f'<p class="meta">Памятка к экзамену · '
        f'<a href="{escape(sheet_url)}">Открыть в Lecturo</a></p>',
        "<h2>Билеты</h2>",
    ]
    if tickets:
        parts.append('<ol class="tickets">')
        parts.extend(f"<li>{escape(ticket)}</li>" for ticket in tickets)
        parts.append("</ol>")
    else:
        parts.append('<p class="empty">Билетов в памятке нет.</p>')
    parts.append("<h2>Определения</h2>")
    if definitions:
        parts.append('<dl class="terms">')
        parts.extend(
            f"<div><dt>{escape(item['term'])}</dt><dd>{escape(item['definition'])}</dd></div>"
            for item in definitions
        )
        parts.append("</dl>")
    else:
        parts.append('<p class="empty">Определений в памятке нет.</p>')
    parts.append("<h2>Шпаргалка</h2>")
    if cheatsheet.strip():
        parts.append(f'<div class="summary">{render_summary(cheatsheet)}</div>')
    else:
        parts.append('<p class="empty">Шпаргалки в памятке нет.</p>')

    return (
        f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        f"<title>{escape(course.title)}</title></head><body>{''.join(parts)}</body></html>"
    )


def refuse_fetch(url: str, *args: object, **kwargs: object) -> dict:
    raise ValueError(f"Внешние ресурсы в PDF не загружаются: {url}")


def render_pdf(html: str) -> bytes:
    return HTML(string=html, url_fetcher=refuse_fetch).write_pdf(
        stylesheets=[KATEX_STYLE, STYLE], font_config=FONT_CONFIG
    )


pdf_renders = asyncio.Semaphore(get_settings().pdf_render_concurrency)


async def render_pdf_limited(html: str) -> bytes:
    async with pdf_renders:
        return await asyncio.to_thread(render_pdf, html)
