import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import type { components } from "../../api/schema";
import { ApiError } from "../../app/queryClient";
import { useLecture } from "../../pages/lecture/useLecture";
import { Button } from "../../ui/Button";
import { EmptyState } from "../../ui/EmptyState";
import { Progress } from "../../ui/Progress";
import { useAiTransferConsent } from "../consent/useAiTransferConsent";
import {
  isBuilding,
  needsSubscription,
  quizErrorOf,
  useCreateQuiz,
  useQuiz,
  useQuizStep,
  useRefreshQuiz,
} from "./queries";
import { hasMomentPlayer, MomentDialog } from "./MomentDialog";
import { QuizRunner } from "./QuizRunner";
import "./quiz.css";

type Step = components["schemas"]["StepOut"];

function QuizSkeleton() {
  return (
    <div className="quiz-skeleton" aria-busy="true" aria-label="Квиз загружается">
      <span className="quiz-skeleton__bar quiz-skeleton__bar--track" />
      <span className="quiz-skeleton__bar quiz-skeleton__bar--question" />
      {Array.from({ length: 4 }, (_, index) => (
        <span key={index} className="quiz-skeleton__bar quiz-skeleton__bar--option" />
      ))}
    </div>
  );
}

function SubscriptionOffer() {
  return (
    <section className="quiz-offer" aria-labelledby="quiz-offer-title">
      <h2 id="quiz-offer-title" className="quiz-offer__title">
        Квизы доступны с подпиской
      </h2>
      <p className="quiz-offer__text">
        Вопросы составляются по расшифровке этой лекции. После каждого ответа видно объяснение и момент видео, где об этом
        говорят.
      </p>
      <Link to="/account#purchase" className="button button--primary">
        Оформить подписку
      </Link>
    </section>
  );
}

type StartProps = {
  step: Step | null;
  empty: boolean;
  onStart: () => void;
  starting: boolean;
  error: string | null;
};

function QuizStart({ step, empty, onStart, starting, error }: StartProps) {
  const failed = step?.status === "failed";
  let heading = "Проверьте, что запомнили";
  let text = "Соберём вопросы по лекции. После каждого ответа покажем объяснение и ссылку на момент видео.";
  if (failed) {
    heading = "Квиз не получилось составить";
    text = step?.error ?? "Попробуйте запустить его ещё раз.";
  } else if (empty) {
    heading = "Вопросов не набралось";
    text = "В расшифровке слишком мало материала. Можно попробовать составить квиз заново.";
  }
  return (
    <section className="quiz-start" aria-labelledby="quiz-start-title">
      <h2 id="quiz-start-title" className="quiz-start__title">
        {heading}
      </h2>
      <p className="quiz-start__text">{text}</p>
      {error && (
        <p className="quiz-start__error" role="alert">
          {error}
        </p>
      )}
      <Button onClick={onStart} loading={starting}>
        {failed || empty ? "Попробовать ещё раз" : "Сделать квиз"}
      </Button>
    </section>
  );
}

function QuizBuilding({ step }: { step: Step }) {
  return (
    <section className="quiz-start" aria-labelledby="quiz-building-title">
      <h2 id="quiz-building-title" className="quiz-start__title" aria-live="polite">
        Составляем вопросы
      </h2>
      <p className="quiz-start__text">Обычно это занимает меньше минуты. Страница обновится сама.</p>
      <Progress
        label={step.status === "pending" ? "В очереди" : "Читаем расшифровку"}
        value={step.status === "running" ? step.progress * 100 : undefined}
      />
    </section>
  );
}

function QuizFailure({ onRetry, retrying }: { onRetry: () => void; retrying: boolean }) {
  return (
    <div className="quiz-error" role="alert">
      <p>Не удалось загрузить квиз. Проверьте соединение и попробуйте ещё раз.</p>
      <Button variant="secondary" size="sm" onClick={onRetry} loading={retrying}>
        Повторить
      </Button>
    </div>
  );
}

export function QuizPage() {
  const { id = "" } = useParams();
  const lecture = useLecture(id);
  const ready = lecture.data?.status === "ready";
  const quiz = useQuiz(id, ready);
  const stepQuery = useQuizStep(id, ready);
  const create = useCreateQuiz(id);
  const refreshQuiz = useRefreshQuiz(id);
  const { requireConsent, dialog: consentDialog } = useAiTransferConsent();
  const [moment, setMoment] = useState<number | null>(null);

  const step = stepQuery.data ?? null;
  const building = isBuilding(step);
  const wasBuilding = useRef(false);

  useEffect(() => {
    if (wasBuilding.current && step?.status === "done") void refreshQuiz();
    wasBuilding.current = building;
  }, [building, step?.status, refreshQuiz]);

  const start = () => requireConsent(() => create.mutate());

  if (lecture.isError) {
    const missing = lecture.error instanceof ApiError && (lecture.error.status === 404 || lecture.error.status === 422);
    return (
      <div className="quiz-page">
        {missing ? (
          <EmptyState
            title="Лекция не найдена"
            description="Возможно, её удалили или ссылка открыта не из того аккаунта."
            action={<Link to="/">К списку лекций</Link>}
          />
        ) : (
          <QuizFailure onRetry={() => void lecture.refetch()} retrying={lecture.isFetching} />
        )}
      </div>
    );
  }

  const title = lecture.data?.title;
  const subscriptionNeeded = needsSubscription(quiz.error) || needsSubscription(create.error);
  const createError = create.error && !subscriptionNeeded ? quizErrorOf(create.error) : null;
  const rebuildError = step?.status === "failed" ? (step.error ?? "Новые вопросы не получилось составить.") : null;

  let body;
  if (lecture.isPending || (ready && (quiz.isPending || stepQuery.isPending))) {
    body = <QuizSkeleton />;
  } else if (!ready) {
    body = (
      <EmptyState
        title="Квиз появится после обработки"
        description="Вопросы составляются по готовой расшифровке. Вернитесь, когда лекция обработается."
        action={<Link to={`/lectures/${id}`}>К лекции</Link>}
      />
    );
  } else if (subscriptionNeeded) {
    body = <SubscriptionOffer />;
  } else if (quiz.isError) {
    body = <QuizFailure onRetry={() => void quiz.refetch()} retrying={quiz.isFetching} />;
  } else if (stepQuery.isError && !quiz.data) {
    body = <QuizFailure onRetry={() => void stepQuery.refetch()} retrying={stepQuery.isFetching} />;
  } else if (building && step) {
    body = <QuizBuilding step={step} />;
  } else if (quiz.data && quiz.data.questions.length > 0) {
    body = (
      <>
        {(createError ?? rebuildError) && (
          <div className="quiz-error" role="alert">
            <p>{createError ?? rebuildError}</p>
            <Button variant="secondary" size="sm" onClick={start} loading={create.isPending}>
              Попробовать ещё раз
            </Button>
          </div>
        )}
        <QuizRunner
          key={quiz.dataUpdatedAt}
          lectureId={id}
          questions={quiz.data.questions}
          duration={lecture.data?.duration_sec ?? null}
          onRegenerate={start}
          regenerating={create.isPending}
          onMoment={lecture.data && hasMomentPlayer(lecture.data) ? setMoment : undefined}
        />
        {lecture.data && <MomentDialog lecture={lecture.data} seconds={moment} onClose={() => setMoment(null)} />}
      </>
    );
  } else {
    body = (
      <QuizStart
        step={step}
        empty={quiz.data !== null && quiz.data !== undefined}
        onStart={start}
        starting={create.isPending}
        error={createError}
      />
    );
  }

  return (
    <div className="quiz-page">
      <header className="quiz-page__header">
        <Link to={`/lectures/${id}`} className="quiz-page__back">
          К лекции
        </Link>
        <h1 className="quiz-page__title">{title ? `Квиз: ${title}` : "Квиз"}</h1>
      </header>
      {body}
      {consentDialog}
    </div>
  );
}
