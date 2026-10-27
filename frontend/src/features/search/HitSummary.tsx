import { highlight } from "./highlight";
import type { SearchHit } from "./queries";

type HitSummaryProps = {
  hit: SearchHit;
  matcher: RegExp | null;
};

export function HitSummary({ hit, matcher }: HitSummaryProps) {
  if (hit.description) {
    return (
      <>
        <span className="search__description">{hit.description}</span>
        <span className="search__quote">{highlight(hit.text, matcher)}</span>
      </>
    );
  }
  return (
    <>
      {hit.chapter_title && <span className="search__chapter">{hit.chapter_title}</span>}
      <span className="search__text">{highlight(hit.text, matcher)}</span>
    </>
  );
}
