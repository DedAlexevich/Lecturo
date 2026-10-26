import { useNavigate } from "react-router";
import { CourseFormDialog } from "./CourseFormDialog";
import { useCreateCourse } from "./queries";
import "./course.css";

export function CreateCourseDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const create = useCreateCourse();

  return (
    <CourseFormDialog
      title="Новый курс"
      submitLabel="Создать"
      pending={create.isPending}
      failed={create.isError}
      onClose={onClose}
      onSubmit={(fields) =>
        create.mutate(fields, {
          onSuccess: (course) => {
            onClose();
            navigate(`/courses/${course.id}`);
          },
        })
      }
    />
  );
}
