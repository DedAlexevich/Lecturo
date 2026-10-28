import { SummaryMarkdown } from "../../pages/lecture/SummaryMarkdown";
import type { Definition } from "./queries";

export function TicketList({ tickets }: { tickets: string[] }) {
  if (tickets.length === 0) return <p className="exam-sheet__none">Билетов в памятке нет.</p>;
  return (
    <ol className="exam-tickets">
      {tickets.map((ticket, index) => (
        <li key={index}>{ticket}</li>
      ))}
    </ol>
  );
}

export function DefinitionList({ definitions }: { definitions: Definition[] }) {
  if (definitions.length === 0) return <p className="exam-sheet__none">Определений в памятке нет.</p>;
  return (
    <dl className="exam-terms">
      {definitions.map(({ term, definition }) => (
        <div key={term} className="exam-terms__row">
          <dt>{term}</dt>
          <dd>{definition}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Cheatsheet({ source }: { source: string }) {
  if (!source.trim()) return <p className="exam-sheet__none">Шпаргалки в памятке нет.</p>;
  return (
    <div className="exam-cheatsheet">
      <SummaryMarkdown source={source} />
    </div>
  );
}
