import { useEffect, useRef } from "react";
import { Button } from "../../ui/Button";
import { formatMinutes, lectureSeconds, lecturesWord } from "./format";
import { useWaiting } from "./queries";
import { useQuotaDialogParam } from "./useQuotaDialogParam";
import "./quota-dialog.css";

export function WaitingNotice() {
  const { data } = useWaiting();
  const { open, setOpen, adding } = useQuotaDialogParam();
  const known = useRef<Set<string> | null>(null);

  useEffect(() => {
    if (!data) return;
    const ids = new Set(data.lectures.map((lecture) => lecture.id));
    const seen = known.current;
    if (seen !== null && !open && adding) return;
    known.current = ids;
    if (seen !== null && !open && [...ids].some((id) => !seen.has(id))) setOpen(true);
  }, [data, open, adding, setOpen]);

  if (!data || data.lectures.length === 0) return null;

  const count = data.lectures.length;
  const needed = data.lectures.reduce((sum, lecture) => sum + lectureSeconds(lecture.duration_sec), 0);

  return (
    <div className="waiting-notice" role="status">
      <p>
        <strong>
          Ждут лимита: {count} {lecturesWord(count)}.
        </strong>{" "}
        Нужно {formatMinutes(needed)}, осталось {formatMinutes(data.available_sec)}.
      </p>
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        Выбрать, что обработать
      </Button>
    </div>
  );
}
