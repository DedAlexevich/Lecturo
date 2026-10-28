import assert from "node:assert/strict";
import { test } from "node:test";
import { renderSummary } from "../src/pages/lecture/summaryMarkdown.ts";

test("формулы и блоки отображаются в конспекте", () => {
  const html = renderSummary(":::definition\nВектор $x^2$\n:::\n\n$$\\frac{a}{b}$$");
  assert.match(html, /summary-callout--definition/);
  assert.match(html, /Определение/);
  assert.match(html, /katex-display/);
  assert.match(html, /katex-mathml/);
});

test("некорректная формула и старый конспект остаются читаемыми", () => {
  const html = renderSummary("## Глава\n\n- **Термин**: определение\n\n$\\unknowncommand$");
  assert.match(html, /<h2>Глава<\/h2>/);
  assert.match(html, /<strong>Термин<\/strong>/);
  assert.match(html, /unknowncommand/);
});

test("конспект не выполняет произвольный HTML и небезопасные ссылки", () => {
  const html = renderSummary("<script>alert(1)</script>\n\n[ссылка](javascript:alert(1))");
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /href=\"javascript:/);
});

test("обычные суммы не превращаются в формулы", () => {
  const html = renderSummary("Цена $5 и $10.\n\n$$x^2$$");
  assert.match(html, /Цена \$5 и \$10/);
  assert.match(html, /katex-display/);
});

test("двойные доллары внутри абзаца остаются текстом", () => {
  const html = renderSummary("Текст $$x^2$$ рядом с текстом");
  assert.match(html, /\$\$x\^2\$\$/);
  assert.doesNotMatch(html, /class=\"katex/);
});

test("внешние ссылки открываются в новой вкладке", () => {
  const html = renderSummary("[учебник](https://example.org/book) и [архив](//archive.org/x)");
  assert.match(html, /<a href="https:\/\/example\.org\/book" target="_blank" rel="noopener noreferrer">/);
  assert.match(html, /<a href="\/\/archive\.org\/x" target="_blank" rel="noopener noreferrer">/);
});

test("внутренние ссылки и таймкоды остаются в окне", () => {
  const html = renderSummary("[глава](#glava), [момент](?t=90) и [лекция](/lectures/abc)");
  assert.equal((html.match(/<a /g) ?? []).length, 3);
  assert.doesNotMatch(html, /target=/);
  assert.doesNotMatch(html, /rel=/);
});

test("шпаргалка памятки показывает формулы и блоки вместо разметки", () => {
  const html = renderSummary("## Механика\n\n:::formula\n$E = mc^2$ и $a * b * c$\n:::\n\n- Сила: $F = m \\cdot a$");
  assert.match(html, /summary-callout--formula/);
  assert.match(html, /class="katex"/);
  assert.doesNotMatch(html, /:::/);
  assert.doesNotMatch(html, /\$E = mc\^2\$/);
  assert.doesNotMatch(html, /<em>/);
});
