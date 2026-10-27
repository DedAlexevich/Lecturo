type ProgressQuestion = {
  question: string;
  options: string[];
  correct_index: number;
  timestamp: number;
};

export type QuizAnswer = number | null;

export type QuizProgress = {
  answers: QuizAnswer[];
  index: number;
};

type StoredProgress = QuizProgress & {
  fingerprint: string;
  score: number;
};

type StorageSource = () => Pick<Storage, "getItem" | "setItem" | "removeItem">;

const browserStorage: StorageSource = () => window.sessionStorage;

export function progressKey(lectureId: string) {
  return `lecturo:quiz-progress:${lectureId}`;
}

export function quizFingerprint(questions: ProgressQuestion[]) {
  const source = JSON.stringify(
    questions.map(({ question, options, correct_index, timestamp }) => [question, options, correct_index, timestamp]),
  );
  let hash = 5381;
  for (let at = 0; at < source.length; at += 1) {
    hash = (Math.imul(hash, 33) ^ source.charCodeAt(at)) >>> 0;
  }
  return `${questions.length}:${hash.toString(36)}`;
}

export function scoreOf(questions: ProgressQuestion[], answers: QuizAnswer[]) {
  return questions.filter((question, at) => answers[at] === question.correct_index).length;
}

export function emptyProgress(questions: ProgressQuestion[]): QuizProgress {
  return { answers: questions.map(() => null), index: 0 };
}

export function serializeProgress(questions: ProgressQuestion[], progress: QuizProgress) {
  const stored: StoredProgress = {
    fingerprint: quizFingerprint(questions),
    answers: progress.answers,
    index: progress.index,
    score: scoreOf(questions, progress.answers),
  };
  return JSON.stringify(stored);
}

function validAnswer(value: unknown, question: ProgressQuestion) {
  return value === null || (Number.isInteger(value) && (value as number) >= 0 && (value as number) < question.options.length);
}

export function parseProgress(raw: string | null, questions: ProgressQuestion[]): QuizProgress | null {
  if (raw === null) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const { fingerprint, answers, index, score } = data as Partial<StoredProgress>;
  if (fingerprint !== quizFingerprint(questions)) return null;
  if (!Array.isArray(answers) || answers.length !== questions.length) return null;
  if (!answers.every((answer, at) => validAnswer(answer, questions[at]))) return null;
  if (!Number.isInteger(index) || index! < 0 || index! > questions.length) return null;
  if (answers.slice(0, index).some((answer) => answer === null)) return null;
  if (score !== scoreOf(questions, answers)) return null;
  return { answers, index: index! };
}

export function loadProgress(lectureId: string, questions: ProgressQuestion[], storage = browserStorage) {
  try {
    const store = storage();
    const key = progressKey(lectureId);
    const raw = store.getItem(key);
    const progress = parseProgress(raw, questions);
    if (raw !== null && progress === null) store.removeItem(key);
    return progress;
  } catch {
    return null;
  }
}

export function saveProgress(
  lectureId: string,
  questions: ProgressQuestion[],
  progress: QuizProgress,
  storage = browserStorage,
) {
  try {
    storage().setItem(progressKey(lectureId), serializeProgress(questions, progress));
  } catch {
    return;
  }
}

export function clearProgress(lectureId: string, storage = browserStorage) {
  try {
    storage().removeItem(progressKey(lectureId));
  } catch {
    return;
  }
}
