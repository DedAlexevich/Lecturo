from app.services.summary_markdown import katex_css, render_summary


def test_render_formula_and_callout():
    html = render_summary(":::definition\nВектор $x^2$\n:::\n\n$$\\frac{a}{b}$$")

    assert 'class="summary-callout summary-callout--definition"' in html
    assert "Определение" in html
    assert 'class="katex-display"' in html
    assert 'class="mfrac"' in html


def test_invalid_formula_and_legacy_markdown():
    html = render_summary("## Глава\n\n- **Термин**: определение\n\n$\\unknowncommand$")

    assert "<h2>Глава</h2>" in html
    assert "<strong>Термин</strong>" in html
    assert "unknowncommand" in html


def test_untrusted_markup_is_not_executed():
    html = render_summary("<script>alert(1)</script>\n\n[ссылка](javascript:alert(1))")

    assert "<script>" not in html
    assert 'href="javascript:' not in html


def test_fonts_are_embedded():
    css = katex_css()

    assert "data:application/octet-stream;base64," in css
    assert "url(fonts/" not in css
