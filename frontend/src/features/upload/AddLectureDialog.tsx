import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { useMe } from "../../app/useMe";
import { Dialog } from "../../ui/Dialog";
import { Tabs } from "../../ui/Tabs";
import { useToast } from "../../ui/Toast";
import { useAiTransferConsent } from "../consent/useAiTransferConsent";
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
  const [fileKey, setFileKey] = useState(0);
  const { data: me } = useMe();
  const courses = useCourseOptions(open);
  const upload = useTusUpload(me?.id);
  const addLink = useAddLink();
  const { requireConsent, dialog: consentDialog } = useAiTransferConsent();
  const queryClient = useQueryClient();
  const toast = useToast();

  if (open !== wasOpen) {
    setWasOpen(open);
    if (open && !upload.active) setCourseId(searchParams.get("course") ?? "");
  }

  const selectedCourse = courses.data?.some((course) => course.id === courseId) ? courseId : "";

  const close = useCallback(() => {
    setSearchParams(
      (params) => {
        params.delete("add");
        return params;
      },
      { replace: true },
    );
  }, [setSearchParams]);

  const refreshLists = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["lectures"] });
    void queryClient.invalidateQueries({ queryKey: ["courses"] });
  }, [queryClient]);

  const { phase, file } = upload.state;
  const { reset } = upload;

  useEffect(() => {
    if (phase !== "done") return;
    toast.show(`Запись «${file?.name ?? ""}» загружена, начинаем обработку`, "success");
    refreshLists();
    reset();
    setFileKey((key) => key + 1);
    if (open) close();
  }, [phase, file, open, close, refreshLists, reset, toast]);

  const startUpload = (picked: File) => {
    const course = selectedCourse || null;
    requireConsent(() => upload.start(picked, course));
  };

  const submitLink = (url: string) => {
    requireConsent(() =>
      addLink.mutate(
        { url, course_id: selectedCourse || null },
        {
          onSuccess: (lecture) => {
            toast.show(`Лекция «${lecture.title}» добавлена, начинаем обработку`, "success");
            refreshLists();
            addLink.reset();
            setLinkKey((key) => key + 1);
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
                    key={fileKey}
                    state={upload.state}
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
                    pending={addLink.isPending}
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
