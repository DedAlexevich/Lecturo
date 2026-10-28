import MarkdownIt from "markdown-it";
import container from "markdown-it-container";
import { katex } from "@mdit/plugin-katex";

const labels: Record<string, string> = {
  definition: "Определение",
  theorem: "Теорема",
  formula: "Формула",
  example: "Пример",
  important: "Важно",
};

const markdown = new MarkdownIt({ html: false, linkify: false });
markdown.disable("image");
markdown.use(katex, { throwOnError: false, trust: false });
for (const [kind, label] of Object.entries(labels)) {
  markdown.use(container, kind, {
    validate: (info: string) => info.trim() === kind,
    render: (tokens: { nesting: number }[], index: number) => tokens[index].nesting === 1
      ? `<section class="summary-callout summary-callout--${kind}"><p class="summary-callout__title">${label}</p>`
      : "</section>\n",
  });
}

const externalLink = /^(?:https?:)?\/\//i;

markdown.renderer.rules.link_open = (tokens, index, options, _env, self) => {
  const token = tokens[index];
  if (externalLink.test(String(token.attrGet("href") ?? ""))) {
    token.attrSet("target", "_blank");
    token.attrSet("rel", "noopener noreferrer");
  }
  return self.renderToken(tokens, index, options);
};

export function renderSummary(source: string) {
  return markdown.render(source);
}
