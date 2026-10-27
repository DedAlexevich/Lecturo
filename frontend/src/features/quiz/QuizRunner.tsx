import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router";
import { formatTimecode } from "../../lib/timecode";
import { Button } from "../../ui/Button";
import { fromQuizState, momentLink } from "./moment";
import { clearProgress, emptyProgress, loadProgress, saveProgress, type QuizAnswer, type QuizProgress } from "./progress";
import type { QuizQuestion } from "./queries";

type QuizRunnerProps = {
  lectureId: string;
  questions: QuizQuestion[];
  duration: number | null;
  onRegenerate: () => void;
  regenerating: boolean;
  onMoment?: (seconds: number) => void;
};

type Answer = QuizAnswer;

type MomentProps = {
  lectureId: string;
  seconds: number;
  onMoment?: (seconds: number) => void;
  className: string;
  children?: ReactNode;
  label?: string;
  title?: string;
  style?: CSSProperties;
};

function Moment({ lectureId, seconds, onMoment, className, children, label, title, style }: MomentProps) {
  if (onMoment) {
    return (
      <button
        type="button"
        className={className}
        style={style}
        aria-label={label}
        title={title}
        onClick={() => onMoment(seconds)}
      >
        {children}
      </button>
    );
  }
  return (
    <Link
      to={momentLink(lectureId, seconds)}
      state={fromQuizState}
      className={className}
      style={style}
      aria-label={label}
      title={title}
    >
      {children}
    </Link>
  );
}

function answersWord(count: number) {
  const tens = count % 100;
  const ones = count % 10;
  if (tens >= 11 && tens <= 14) return "ответов";
  if (ones === 1) return "ответ";
  if (ones >= 2 && ones <= 4) return "ответа";
  return "ответов";
}

export function QuizRunner({ lectureId, questions, duration, onRegenerate, regenerating, onMoment }: QuizRunnerProps) {
  const [progress, setProgress] = useState<QuizProgress>(
    () => loadProgress(lectureId, questions) ?? emptyProgress(questions),
  );
  const { answers, index } = progress;

  useEffect(() => {
    saveProgress(lectureId, questions, progress);
  }, [lectureId, questions, progress]);

  const restart = () => {
    clearProgress(lectureId);
    setProgress(emptyProgress(questions));
  };

  if (index >= questions.length) {
    return (
      <QuizResult
        lectureId={lectureId}
        questions={questions}
        answers={answers}
        duration={duration}
        onRestart={restart}
        onRegenerate={onRegenerate}
        regenerating={regenerating}
        onMoment={onMoment}
      />
    );
  }

  return (
    <QuestionStep
      key={index}
      lectureId={lectureId}
      questions={questions}
      index={index}
      answers={answers}
      onAnswer={(choice) =>
        setProgress((current) => ({
          ...current,
          answers: current.answers.map((value, at) => (at === current.index ? choice : value)),
        }))
      }
      onNext={() => setProgress((current) => ({ ...current, index: current.index + 1 }))}
      onMoment={onMoment}
    />
  );
}

function segmentState(question: QuizQuestion, answer: Answer, current: boolean) {
  if (answer !== null) return answer === question.correct_index ? "correct" : "wrong";
  return current ? "current" : "upcoming";
}

type QuestionStepProps = {
  lectureId: string;
  questions: QuizQuestion[];
  index: number;
  answers: Answer[];
  onAnswer: (choice: number) => void;
  onNext: () => void;
  onMoment?: (seconds: number) => void;
};

function QuestionStep({ lectureId, questions, index, answers, onAnswer, onNext, onMoment }: QuestionStepProps) {
  const question = questions[index];
  const answer = answers[index];
  const answered = answer !== null;
  const correct = answer === question.correct_index;
  const last = index === answers.length - 1;
  const verdictRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (answered) verdictRef.current?.focus();
  }, [answered]);

  return (
    <section className="quiz-step" aria-labelledby="quiz-question">
      <div className="quiz-step__progress">
        <p className="quiz-step__count">
          Вопрос {index + 1} из {answers.length}
        </p>
        <ol className="quiz-track" aria-hidden="true">
          {answers.map((value, at) => (
            <li key={at} className={`quiz-track__segment quiz-track__segment--${segmentState(questions[at], value, at === index)}`} />
          ))}
        </ol>
      </div>

      <h2 id="quiz-question" className="quiz-step__question">
        {question.question}
      </h2>

      <ul className="quiz-options">
        {question.options.map((option, at) => {
          const classes = ["quiz-option"];
          if (answered && at === question.correct_index) classes.push("quiz-option--correct");
          else if (answered && at === answer) classes.push("quiz-option--wrong");
          else if (answered) classes.push("quiz-option--muted");
          return (
            <li key={at}>
              <button
                type="button"
                className={classes.join(" ")}
                disabled={answered}
                aria-pressed={at === answer}
                onClick={() => onAnswer(at)}
              >
                <span className="quiz-option__text">{option}</span>
                {answered && at === question.correct_index && <span className="quiz-option__mark">Правильный ответ</span>}
                {answered && at === answer && !correct && <span className="quiz-option__mark">Ваш ответ</span>}
              </button>
            </li>
          );
        })}
      </ul>

      {answered && (
        <div className={correct ? "quiz-feedback quiz-feedback--correct" : "quiz-feedback quiz-feedback--wrong"}>
          <p ref={verdictRef} className="quiz-feedback__verdict" tabIndex={-1}>
            {correct ? "Верно" : "Неверно"}
          </p>
          {question.explanation && <p className="quiz-feedback__text">{question.explanation}</p>}
          <div className="quiz-feedback__actions">
            <Moment lectureId={lectureId} seconds={question.timestamp} onMoment={onMoment} className="quiz-moment">
              Смотреть в лекции с {formatTimecode(question.timestamp)}
            </Moment>
            <Button onClick={onNext}>{last ? "Показать итог" : "Следующий вопрос"}</Button>
          </div>
        </div>
      )}
    </section>
  );
}

type QuizResultProps = {
  lectureId: string;
  questions: QuizQuestion[];
  answers: Answer[];
  duration: number | null;
  onRestart: () => void;
  onRegenerate: () => void;
  regenerating: boolean;
  onMoment?: (seconds: number) => void;
};

function QuizResult({
  lectureId,
  questions,
  answers,
  duration,
  onRestart,
  onRegenerate,
  regenerating,
  onMoment,
}: QuizResultProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const results = questions.map((question, at) => ({
    question,
    answer: answers[at],
    correct: answers[at] === question.correct_index,
    position: at,
  }));
  const score = results.filter((result) => result.correct).length;
  const missed = results.filter((result) => !result.correct);
  const span = Math.max(duration ?? 0, ...questions.map((question) => question.timestamp), 1);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  return (
    <section className="quiz-result" aria-labelledby="quiz-result-title">
      <div className="quiz-result__head">
        <h2 id="quiz-result-title" ref={headingRef} tabIndex={-1} className="quiz-result__score">
          {score} из {questions.length}
        </h2>
        <p className="quiz-result__lead">
          {missed.length === 0
            ? "Все ответы верные. Лекцию вы усвоили."
            : `${missed.length} ${answersWord(missed.length)} с ошибкой. На шкале отмечено, где в лекции об этом говорят.`}
        </p>
      </div>

      <div className="quiz-timeline">
        <div className="quiz-timeline__track">
          {results.map((result, at) => (
            <Moment
              key={at}
              lectureId={lectureId}
              seconds={result.question.timestamp}
              onMoment={onMoment}
              className={result.correct ? "quiz-timeline__mark" : "quiz-timeline__mark quiz-timeline__mark--wrong"}
              style={{ left: `${(result.question.timestamp / span) * 100}%` }}
              label={`${formatTimecode(result.question.timestamp)}, ${result.correct ? "верно" : "ошибка"}: ${result.question.question}`}
              title={result.question.question}
            />
          ))}
        </div>
        <div className="quiz-timeline__scale" aria-hidden="true">
          <span>0:00</span>
          <span>{formatTimecode(span)}</span>
        </div>
      </div>

      {missed.length > 0 && (
        <section className="quiz-review" aria-labelledby="quiz-review-title">
          <h3 id="quiz-review-title" className="quiz-review__title">
            Что пересмотреть
          </h3>
          <ul className="quiz-review__list">
            {missed.map(({ question, answer, position }) => (
              <li key={position} className="quiz-review__item">
                <p className="quiz-review__question">{question.question}</p>
                <p className="quiz-review__answers">
                  {answer !== null && <span className="quiz-review__yours">Ваш ответ: {question.options[answer]}</span>}
                  <span>Правильно: {question.options[question.correct_index]}</span>
                </p>
                <Moment lectureId={lectureId} seconds={question.timestamp} onMoment={onMoment} className="quiz-moment">
                  Смотреть с {formatTimecode(question.timestamp)}
                </Moment>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="quiz-result__actions">
        <Button onClick={onRestart}>Пройти ещё раз</Button>
        <Button variant="secondary" onClick={onRegenerate} loading={regenerating}>
          Новые вопросы
        </Button>
      </div>
    </section>
  );
}
