import { Field } from "../../ui/Field";
import type { Course } from "./queries";

type CourseFieldProps = {
  courses: Course[] | undefined;
  failed: boolean;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  onRetry: () => void;
};

export function CourseField({ courses, failed, value, disabled, onChange, onRetry }: CourseFieldProps) {
  const loading = courses === undefined && !failed;

  return (
    <div className="add-lecture__course">
      <Field label="Курс" hint={courses?.length === 0 ? "Курсов пока нет, лекция попадёт в общий список" : undefined}>
        {(control) => (
          <select
            {...control}
            className="input add-lecture__select"
            value={value}
            disabled={disabled || loading}
            onChange={(event) => onChange(event.target.value)}
          >
            <option value="">{loading ? "Загружаем курсы" : "Без курса"}</option>
            {courses?.map((course) => (
              <option key={course.id} value={course.id}>
                {course.title}
              </option>
            ))}
          </select>
        )}
      </Field>
      {failed && (
        <p className="add-lecture__note">
          Курсы не загрузились.{" "}
          <button type="button" className="add-lecture__text-button" onClick={onRetry}>
            Повторить
          </button>
        </p>
      )}
    </div>
  );
}
