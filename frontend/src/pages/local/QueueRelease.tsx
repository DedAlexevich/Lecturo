import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useDeleteLecture } from "../../features/lecture-actions/queries";
import { forgetPickedFile } from "../../local/pickedFiles";
import { Button } from "../../ui/Button";
import { Dialog } from "../../ui/Dialog";
import { useToast } from "../../ui/Toast";

type QueueReleaseProps = {
  lecture: { id: string; title: string };
  onReleased: () => void;
};

export function QueueRelease({ lecture, onReleased }: QueueReleaseProps) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();
  const toast = useToast();
  const remove = useDeleteLecture(lecture.id, () => {
    forgetPickedFile(lecture.id);
    setConfirming(false);
    onReleased();
    toast.show(`Лекция «${lecture.title}» убрана из очереди`, "success");
    void queryClient.invalidateQueries({ queryKey: ["billing"] });
  });

  const close = () => {
    if (remove.isPending) return;
    remove.reset();
    setConfirming(false);
  };

  return (
    <div className="local-release">
      <p>
        Лекция «{lecture.title}» всё ещё ждёт лимита на сервере. Если расшифровки на устройстве достаточно, уберите
        её из очереди, чтобы она не заняла часы, когда лимит обновится.
      </p>
      <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>
        Убрать из очереди
      </Button>
      {confirming && (
        <Dialog
          open
          dismissible={!remove.isPending}
          title="Убрать лекцию из очереди?"
          onClose={close}
          actions={
            <>
              <Button variant="secondary" autoFocus disabled={remove.isPending} onClick={close}>
                Отмена
              </Button>
              <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
                Убрать и удалить с сервера
              </Button>
            </>
          }
        >
          <p className="local-release__description">
            Лекция «{lecture.title}» и загруженная запись удалятся с сервера. Расшифровка на этой странице останется.
          </p>
          {remove.isError && (
            <p role="alert" className="local-error">
              Не удалось убрать лекцию. Попробуйте ещё раз.
            </p>
          )}
        </Dialog>
      )}
    </div>
  );
}
