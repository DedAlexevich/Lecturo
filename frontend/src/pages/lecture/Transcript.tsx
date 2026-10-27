import { useEffect, useMemo, useRef } from "react";
import type { components } from "../../api/schema";
import { formatTimecode } from "../../lib/timecode";
import { findActiveSegment, groupTranscript } from "./time";

export type TranscriptSegment = components["schemas"]["SegmentOut"];
type TranscriptChapter = components["schemas"]["ChapterOut"];

type TranscriptProps = {
  segments: TranscriptSegment[];
  chapters?: TranscriptChapter[];
  currentTime: number | null;
  onSelect?: (seconds: number) => void;
};

const MANUAL_SCROLL_PAUSE_MS = 4000;
const NO_CHAPTERS: TranscriptChapter[] = [];

export function Transcript({ segments, chapters = NO_CHAPTERS, currentTime, onSelect }: TranscriptProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const manualScrollAt = useRef(0);
  const active = currentTime === null ? -1 : findActiveSegment(segments, currentTime);
  const activeChapter = currentTime === null ? -1 : findActiveSegment(chapters, currentTime);
  const rows = useMemo(() => groupTranscript(segments, chapters), [segments, chapters]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || active < 0) return;
    if (Date.now() - manualScrollAt.current < MANUAL_SCROLL_PAUSE_MS) return;
    const item = list.querySelector<HTMLElement>(`[data-segment="${active}"]`);
    if (!item) return;
    const top = item.offsetTop;
    const bottom = top + item.offsetHeight;
    if (top >= list.scrollTop && bottom <= list.scrollTop + list.clientHeight) return;
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    list.scrollTo({ top: top - list.clientHeight / 3, behavior: smooth ? "smooth" : "auto" });
  }, [active]);

  const markManualScroll = () => {
    manualScrollAt.current = Date.now();
  };

  return (
    <ol
      ref={listRef}
      className="transcript"
      onWheel={markManualScroll}
      onTouchMove={markManualScroll}
    >
      {rows.map((row) => {
        if (row.kind === "chapter") {
          const { chapter, chapterIndex } = row;
          const current = chapterIndex === activeChapter;
          return (
            <li
              key={`chapter-${chapter.start}-${chapterIndex}`}
              className={current ? "transcript__chapter transcript__chapter--current" : "transcript__chapter"}
            >
              {onSelect ? (
                <button
                  type="button"
                  className="transcript__chapter-time"
                  aria-label={`Перейти к главе «${chapter.title}», ${formatTimecode(chapter.start)}`}
                  onClick={() => {
                    manualScrollAt.current = 0;
                    onSelect(chapter.start);
                  }}
                >
                  {formatTimecode(chapter.start)}
                </button>
              ) : (
                <span className="transcript__chapter-time">{formatTimecode(chapter.start)}</span>
              )}
              <h3 className="transcript__chapter-title">{chapter.title}</h3>
            </li>
          );
        }
        const { segment, segmentIndex: index } = row;
        const current = index === active;
        const content = (
          <>
            <span className="transcript__time">{formatTimecode(segment.start)}</span>
            <span className="transcript__text">{segment.text}</span>
          </>
        );
        return (
          <li
            key={`${segment.start}-${index}`}
            data-segment={index}
            className={current ? "transcript__item transcript__item--current" : "transcript__item"}
          >
            {onSelect ? (
              <button
                type="button"
                className="transcript__phrase"
                aria-current={current || undefined}
                onClick={() => {
                  manualScrollAt.current = 0;
                  onSelect(segment.start);
                }}
              >
                {content}
              </button>
            ) : (
              <p className="transcript__phrase">{content}</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
