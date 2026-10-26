import { useEffect, useRef } from "react";
import type { components } from "../../api/schema";
import { findActiveSegment, formatTimecode } from "./time";

export type TranscriptSegment = components["schemas"]["SegmentOut"];

type TranscriptProps = {
  segments: TranscriptSegment[];
  currentTime: number | null;
  onSelect?: (seconds: number) => void;
};

const MANUAL_SCROLL_PAUSE_MS = 4000;

export function Transcript({ segments, currentTime, onSelect }: TranscriptProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const manualScrollAt = useRef(0);
  const active = currentTime === null ? -1 : findActiveSegment(segments, currentTime);

  useEffect(() => {
    const list = listRef.current;
    if (!list || active < 0) return;
    if (Date.now() - manualScrollAt.current < MANUAL_SCROLL_PAUSE_MS) return;
    const item = list.children[active] as HTMLElement | undefined;
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
      {segments.map((segment, index) => {
        const current = index === active;
        const content = (
          <>
            <span className="transcript__time">{formatTimecode(segment.start)}</span>
            <span className="transcript__text">{segment.text}</span>
          </>
        );
        return (
          <li key={`${segment.start}-${index}`} className={current ? "transcript__item transcript__item--current" : "transcript__item"}>
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
