import type { MouseEvent } from "react";
import "katex/dist/katex.min.css";
import { getWebApp, openExternalLink } from "../../telegram/sdk";
import { renderSummary } from "./summaryMarkdown";
import "./summary-markdown.css";

function openInTelegram(event: MouseEvent<HTMLDivElement>) {
  if (!getWebApp() || !(event.target instanceof Element)) return;
  const link = event.target.closest<HTMLAnchorElement>("a[target=\"_blank\"]");
  if (!link) return;
  event.preventDefault();
  openExternalLink(link.href);
}

export function SummaryMarkdown({ source }: { source: string }) {
  return (
    <div
      className="summary__content"
      onClick={openInTelegram}
      dangerouslySetInnerHTML={{ __html: renderSummary(source) }}
    />
  );
}
