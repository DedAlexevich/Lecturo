import { Link } from "react-router";
import type { components } from "../../api/schema";
import "../../ui/Button.css";
import { isBuilding, quizStepOf } from "./queries";
import "./quiz.css";

type Lecture = components["schemas"]["LectureDetail"];

export function QuizButton({ lecture }: { lecture: Lecture }) {
  if (lecture.status !== "ready") return null;
  const step = quizStepOf(lecture.steps);
  const label = step?.status === "done" ? "Квиз" : isBuilding(step) ? "Квиз готовится" : "Сделать квиз";
  return (
    <Link to={`/lectures/${lecture.id}/quiz`} className="button button--secondary button--sm quiz-entry">
      {label}
    </Link>
  );
}
