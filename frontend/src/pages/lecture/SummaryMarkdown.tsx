import "katex/dist/katex.min.css";
import { renderSummary } from "./summaryMarkdown";

export function SummaryMarkdown({ source }: { source: string }) {
  return <div className="summary__content" dangerouslySetInnerHTML={{ __html: renderSummary(source) }} />;
}
