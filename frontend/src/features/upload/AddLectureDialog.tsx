import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { useMe } from "../../app/useMe";
import { afterStartNote } from "../telegram-notice/TelegramNotice";
import { rememberPickedFile } from "../../local/pickedFiles";
import { Dialog } from "../../ui/Dialog";
import { Tabs } from "../../ui/Tabs";
import { useToast } from "../../ui/Toast";
import { useAiTransferConsent } from "../consent/useAiTransferConsent";
import { fetchWaiting, waitingQueryKey } from "../quota-dialog/queries";
import { useQuotaDialogParam } from "../quota-dialog/useQuotaDialogParam";
import { CourseField } from "./CourseField";
import { FilePanel } from "./FilePanel";
import { LinkPanel } from "./LinkPanel";
import { useAddLink, useCourseOptions } from "./queries";
import { useTusUpload } from "./useTusUpload";
import "./upload.css";

export function AddLectureDialog() {
  const [searchParams, setSearchParams] = useSearchParams();
  const open = searchParams.get("add") === "lecture";
  const [wasOpen, setWasOpen] = useState(false);
  const [tab, setTab] = useState("file");
  const [courseId, setCourseId] = useState("");
  const [linkKey, setLinkKey] = useState(0);
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const uploadedOriginal = useRef<File | null>(null);
  const { data: me } = useMe();
  const telegramState = me?.telegram_notifications;
  const courses = useCourseOptions(open);
  const upload = useTusUpload(me?.id);
  const addLink = useAddLink();
  const { requireConsent, waiting: consentWaiting, dialog: consentDialog } = useAiTransferConsent();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const { setOpen: setQuotaDialogOpen } = useQuotaDialogParam();

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open && !upload.active) setCourseId(searchParams.get("course") ?? "");
  }

  const selectedCourse = courses.data?.some((course) => course.id === courseId) ? courseId : "";

  const { reset: resetLink } = addLink;
  const { active: uploading, reset: resetUpload } = upload;

  const close = useCallback(() => {
    resetLink();
    if (!uploading) {
      setPickedFile(null);
      resetUpload();
    }
    setSearchParams(
      (params) => {
        params.delete("add");
        return params;
      },
      { replace: true },
    );
  }, [resetLink, uploading, resetUpload, setSearchParams]);

  const refreshLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["lectures"] });
    void queryClient.invalidateQueries({ queryKey: ["courses"] });
    void queryClient.invalidateQueries({ queryKey: ["billing"] });
  }, [queryClient]);

  const waitsForQuota = useCallback(
    async (lectureId: string | null) => {
      if (lectureId === null) return false;
      const waiting = await queryClient
        .fetchQuery({ queryKey: waitingQueryKey, queryFn: fetchWaiting, staleTime: 0 })
        .catch(() => null);
      return waiting?.lectures.some((lecture) => lecture.id === lectureId) ?? false;
    },
    [queryClient],
  );

  const { phase, file, lectureId } = upload.state;
  const { reset } = upload;

  useEffect(() => {
    if (phase !== "done") return;
    const name = file?.name ?? "";
    const original = uploadedOriginal.current ?? file;
    uploadedOriginal.current = null;
    refreshLists();
    reset();
    void waitsForQuota(lectureId).then((waiting) => {
      if (waiting) {
        if (lectureId !== null && original !== null) rememberPickedFile(lectureId, original);
        toast.show(`Запись «${name}» загружена, но лимита на неё не хватает`);
        if (open && tab === "file") {
          resetLink();
          setQuotaDialogOpen(true);
        }
        return;
      }
      toast.show(`Запись «${name}» загружена, начинаем обработку.${afterStartNote(telegramState)}`, "success");
      if (open && tab === "file") close();
    });
  }, [phase, file, lectureId, open, tab, close, refreshLists, reset, resetLink, setQuotaDialogOpen, toast, waitsForQuota, telegramState]);

  const startUpload = (picked: File, audioOnly: boolean) => {
    const course = selectedCourse || null;
    requireConsent(() => {
      uploadedOriginal.current = picked;
      void upload.start(picked, course, audioOnly);
      setPickedFile(null);
    });
  };

  const submitLink = (url: string) => {
    requireConsent(() =>
      addLink.mutate(
        { url, course_id: selectedCourse || null },
        {
          onSuccess: (lecture) => {
            refreshLists();
            setLinkKey((key) => key + 1);
            if (lecture.existing) {
              resetLink();
              navigate(`/lectures/${lecture.id}`);
              toast.show(`Лекция «${lecture.title}» уже добавлена, открыли её`);
              return;
            }
            if (lecture.status === "waiting_quota") {
              toast.show(`Лекция «${lecture.title}» добавлена, но лимита на неё не хватает`);
              resetLink();
              setQuotaDialogOpen(true);
              return;
            }
            toast.show(`Лекция «${lecture.title}» добавлена, начинаем обработку.${afterStartNote(telegramState)}`, "success");
            close();
          },
        },
      ),
    );
  };

  const courseField = (locked: boolean) => (
    <CourseField
      courses={courses.data}
      failed={courses.isError}
      value={selectedCourse}
      disabled={locked}
      onChange={setCourseId}
      onRetry={() => courses.refetch()}
    />
  );

  return (
    <>
      <Dialog open={open} onClose={close} title="Добавить лекцию">
        <div className="add-lecture">
          <Tabs
            label="Откуда взять лекцию"
            value={tab}
            onChange={setTab}
            items={[
              {
                id: "file",
                label: "Файл",
                panel: (
                  <FilePanel
                    state={upload.state}
                    file={pickedFile}
                    onPick={setPickedFile}
                    ready={me !== undefined}
                    courseField={courseField(false)}
                    onStart={startUpload}
                    onPause={upload.pause}
                    onResume={upload.resume}
                    onCancel={upload.cancel}
                    onClose={close}
                  />
                ),
              },
              {
                id: "link",
                label: "Ссылка",
                panel: (
                  <LinkPanel
                    key={linkKey}
                    courseField={courseField(addLink.isPending)}
                    pending={addLink.isPending || consentWaiting}
                    error={addLink.error}
                    onSubmit={submitLink}
                    onClose={close}
                  />
                ),
              },
            ]}
          />
        </div>
      </Dialog>
      {consentDialog}
    </>
  );
}
