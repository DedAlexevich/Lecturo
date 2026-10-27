import type { components } from "../../api/schema";
import { formatTimecode } from "../../lib/timecode";
import { findActiveSegment } from "./time";

type Chapter = components["schemas"]["ChapterOut"];

type ChaptersProps = {
  chapters: Chapter[];
  currentTime: number | null;
  onSelect?: (seconds: number) => void;
};

export function Chapters({ chapters, currentTime, onSelect }: ChaptersProps) {
  const active = currentTime === null ? -1 : findActiveSegment(chapters, currentTime);

  return (
    <ol className="chapters">
      {chapters.map((chapter, index) => {
        const current = index === active;
        const range = `${formatTimecode(chapter.start)} – ${formatTimecode(chapter.end)}`;
        return (
          <li key={`${chapter.start}-${index}`} className={current ? "chapter chapter--current" : "chapter"}>
            <span className="chapter__time">{range}</span>
            <h3 className="chapter__title">
              {onSelect ? (
                <button
                  type="button"
                  className="chapter__jump"
                  aria-current={current || undefined}
                  onClick={() => onSelect(chapter.start)}
                >
                  {chapter.title}
                </button>
              ) : (
                chapter.title
              )}
            </h3>
            {chapter.summary && <p className="chapter__summary">{chapter.summary}</p>}
          </li>
        );
      })}
    </ol>
  );
}
