import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Checkbox } from "../../ui/Checkbox";
import { formatMinutes } from "./format";
import type { WaitingLecture } from "./queries";

const scrollEdge = 40;
const scrollStep = 8;

type PlanListProps = {
  lectures: WaitingLecture[];
  selected: string[];
  disabled: boolean;
  onToggle: (id: string) => void;
  onMove: (id: string, index: number) => void;
};

export function PlanList({ lectures, selected, disabled, onToggle, onMove }: PlanListProps) {
  const listRef = useRef<HTMLOListElement>(null);
  const [dragging, setDragging] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const pointerY = useRef<number | null>(null);
  const reorderRef = useRef<(clientY: number) => void>(() => undefined);

  const indexAt = (clientY: number, id: string) => {
    const rows = Array.from(listRef.current?.children ?? []).filter(
      (row) => row instanceof HTMLElement && row.dataset.id !== id,
    );
    return rows.filter((row) => {
      const rect = row.getBoundingClientRect();
      return rect.top + rect.height / 2 < clientY;
    }).length;
  };

  const startDrag = (event: PointerEvent<HTMLButtonElement>, id: string) => {
    if (disabled || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerY.current = event.clientY;
    setDragging(id);
  };

  const reorder = (clientY: number) => {
    if (dragging === null) return;
    const target = indexAt(clientY, dragging);
    if (target !== lectures.findIndex((lecture) => lecture.id === dragging)) onMove(dragging, target);
  };

  useEffect(() => {
    reorderRef.current = reorder;
  });

  useEffect(() => {
    if (dragging === null) return;
    let frame = 0;
    const tick = () => {
      const list = listRef.current;
      const y = pointerY.current;
      if (list && y !== null) {
        const rect = list.getBoundingClientRect();
        const step = y < rect.top + scrollEdge ? -scrollStep : y > rect.bottom - scrollEdge ? scrollStep : 0;
        if (step !== 0) {
          list.scrollTop += step;
          reorderRef.current(y);
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [dragging]);

  const drag = (event: PointerEvent<HTMLButtonElement>, id: string) => {
    if (dragging !== id) return;
    pointerY.current = event.clientY;
    reorder(event.clientY);
  };

  const stopDrag = () => {
    pointerY.current = null;
    setDragging(null);
  };

  const moveByKey = (event: KeyboardEvent<HTMLButtonElement>, lecture: WaitingLecture, index: number) => {
    const step = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const target = index + step;
    if (target < 0 || target >= lectures.length) return;
    onMove(lecture.id, target);
    setAnnouncement(`«${lecture.title}» — ${target + 1} из ${lectures.length}`);
  };

  return (
    <>
      <ol ref={listRef} className="quota-plan__list" aria-label="Лекции, которые ждут лимита">
        {lectures.map((lecture, index) => {
          const isSelected = selected.includes(lecture.id);
          const classes = ["quota-plan__row"];
          if (isSelected) classes.push("quota-plan__row--selected");
          if (dragging === lecture.id) classes.push("quota-plan__row--dragging");
          return (
            <li key={lecture.id} data-id={lecture.id} className={classes.join(" ")}>
              <button
                type="button"
                className="quota-plan__handle"
                aria-label={`Переместить «${lecture.title}», стрелки вверх и вниз`}
                disabled={disabled}
                onPointerDown={(event) => startDrag(event, lecture.id)}
                onPointerMove={(event) => drag(event, lecture.id)}
                onPointerUp={stopDrag}
                onPointerCancel={stopDrag}
                onKeyDown={(event) => moveByKey(event, lecture, index)}
              >
                <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                  <circle cx="5.5" cy="4" r="1.25" />
                  <circle cx="10.5" cy="4" r="1.25" />
                  <circle cx="5.5" cy="8" r="1.25" />
                  <circle cx="10.5" cy="8" r="1.25" />
                  <circle cx="5.5" cy="12" r="1.25" />
                  <circle cx="10.5" cy="12" r="1.25" />
                </svg>
              </button>
              <Checkbox
                className="quota-plan__check"
                checked={isSelected}
                disabled={disabled}
                onChange={() => onToggle(lecture.id)}
                label={
                  <span className="quota-plan__text">
                    <span className="quota-plan__title">{lecture.title}</span>
                    <span className="quota-plan__state">{isSelected ? "Обработаем сейчас" : "Ожидает"}</span>
                  </span>
                }
              />
              <span className="quota-plan__duration">
                {lecture.duration_sec === null ? "длительность неизвестна" : formatMinutes(lecture.duration_sec)}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="quota-plan__sr" aria-live="polite">
        {announcement}
      </p>
    </>
  );
}
