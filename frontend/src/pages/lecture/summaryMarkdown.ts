import MarkdownIt from "markdown-it";
import container from "markdown-it-container";
import texmath from "markdown-it-texmath";
import katex from "katex";

const labels: Record<string, string> = {
  definition: "Определение",
  theorem: "Теорема",
  formula: "Формула",
  example: "Пример",
  important: "Важно",
};

const markdown = new MarkdownIt({ html: false, linkify: false });
markdown.disable("image");
markdown.use(texmath, { engine: katex, delimiters: "dollars", katexOptions: { throwOnError: false, trust: false } });
for (const [kind, label] of Object.entries(labels)) {
  markdown.use(container, kind, {
    validate: (info: string) => info.trim() === kind,
    render: (tokens: { nesting: number }[], index: number) => tokens[index].nesting === 1
      ? `<section class="summary-callout summary-callout--${kind}"><p class="summary-callout__title">${label}</p>`
      : "</section>\n",
  });
}

export function renderSummary(source: string) {
  return markdown.render(source);
}
