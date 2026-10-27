import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import type { components } from "../../api/schema";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { formatTimecode } from "../../lib/timecode";
import "./chat.css";

type ChatResponse = components["schemas"]["LectureChatOut"];
type ChatHistory = components["schemas"]["ChatMessage"][];
type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; content: string; response: ChatResponse };

type ChatPanelProps = {
  lectureId: string;
  onSelectTime?: (seconds: number) => void;
};

function storageKey(lectureId: string) {
  return `lecturo.chat.${lectureId}`;
}

function isChatResponse(value: unknown): value is ChatResponse {
  if (typeof value !== "object" || value === null) return false;
  const response = value as Partial<ChatResponse>;
  return (
    (response.status === "answered" || response.status === "not_found" || response.status === "off_topic") &&
    typeof response.answer === "string" &&
    (typeof response.extra === "string" || response.extra === null) &&
    Array.isArray(response.sources) &&
    response.sources.every(
      (source) =>
        typeof source === "object" &&
        source !== null &&
        (source.kind === "transcript" || source.kind === "chapter") &&
        Number.isFinite(source.start) &&
        Number.isFinite(source.end) &&
        typeof source.text === "string",
    )
  );
}

function isMessage(value: unknown): value is Message {
  if (typeof value !== "object" || value === null) return false;
  const message = value as Partial<Message>;
  if (typeof message.content !== "string") return false;
  if (message.role === "user") return true;
  return message.role === "assistant" && isChatResponse(message.response);
}

function restoreMessages(lectureId: string): Message[] {
  try {
    const stored = sessionStorage.getItem(storageKey(lectureId));
    if (!stored) return [];
    const messages: unknown = JSON.parse(stored);
    return Array.isArray(messages) ? messages.filter(isMessage) : [];
  } catch {
    return [];
  }
}

function historyContent(message: Message) {
  if (message.role === "user") return message.content;
  return [message.response.answer, message.response.extra].filter(Boolean).join("\n");
}

function errorMessage(error: Error) {
  if (!(error instanceof ApiError)) return "Не удалось отправить вопрос. Проверьте соединение и попробуйте ещё раз.";
  if (error.status === 403) {
    const body = error.body as { detail?: { code?: string } | string } | undefined;
    if (typeof body?.detail === "object" && body.detail?.code === "subscription_required") {
      return "Чат доступен только с подпиской.";
    }
    return "Для чата нужно действующее согласие на передачу данных провайдерам ИИ.";
  }
  if (error.status === 409) return "Лекция ещё обрабатывается. Попробуйте позже.";
  if (error.status === 429) return "Слишком много вопросов подряд. Попробуйте через минуту.";
  if (error.status === 503) return "Чат временно недоступен. Попробуйте позже.";
  return "Не удалось получить ответ. Попробуйте ещё раз.";
}

export function ChatPanel({ lectureId, onSelectTime }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>(() => restoreMessages(lectureId));
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const chat = useMutation({
    mutationFn: async ({ question, history }: { question: string; history: ChatHistory }) => {
      const { data, error, response } = await api.POST("/api/v1/lectures/{lecture_id}/chat", {
        params: { path: { lecture_id: lectureId } },
        body: { question, history },
      });
      if (data === undefined) throw new ApiError(response.status, error);
      return data;
    },
    onSuccess: (response) => {
      const message = { role: "assistant" as const, content: "", response };
      message.content = historyContent(message);
      setMessages((current) => [...current, message]);
      setError(null);
    },
    onError: (cause: Error) => setError(errorMessage(cause)),
  });

  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey(lectureId), JSON.stringify(messages));
    } catch {
      setError("Не удалось сохранить историю чата в этой вкладке.");
    }
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lectureId, messages]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || chat.isPending) return;
    const history: ChatHistory = messages
      .map((message) => ({ role: message.role, content: historyContent(message) }))
      .filter((message) => message.content)
      .slice(-10);
    setMessages((current) => [...current, { role: "user", content: trimmed }]);
    setQuestion("");
    setError(null);
    chat.mutate({ question: trimmed, history });
  };

  return (
    <div className="lecture-chat">
      <div className="lecture-chat__messages" aria-live="polite" aria-label="История чата">
        {messages.length === 0 && (
          <p className="lecture-chat__empty">Задайте вопрос по лекции. Ответ будет опираться на расшифровку и главы.</p>
        )}
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`lecture-chat__message lecture-chat__message--${message.role}`}>
            <p className="lecture-chat__speaker">{message.role === "user" ? "Вы" : "Ответ по лекции"}</p>
            {message.role === "user" ? (
              <p className="lecture-chat__text">{message.content}</p>
            ) : (
              <>
                {message.response.status === "off_topic" ? (
                  <p className="lecture-chat__text">{message.response.answer}</p>
                ) : message.response.status === "not_found" ? (
                  <p className="lecture-chat__text">{message.response.answer}</p>
                ) : (
                  <p className="lecture-chat__text">{message.response.answer}</p>
                )}
                {message.response.extra && <p className="lecture-chat__extra">Дополнительно: {message.response.extra}</p>}
                {message.response.sources.length > 0 && (
                  <ul className="lecture-chat__sources" aria-label="Источники в лекции">
                    {message.response.sources.map((source, sourceIndex) => (
                      <li key={`${source.kind}-${source.start}-${sourceIndex}`}>
                        {onSelectTime ? (
                          <button type="button" onClick={() => onSelectTime(source.start)}>
                            {formatTimecode(source.start)}
                          </button>
                        ) : (
                          <span>{formatTimecode(source.start)}</span>
                        )}
                        <span>{source.text}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </article>
        ))}
        {chat.isPending && <p className="lecture-chat__pending" role="status">Ищем ответ в материалах лекции…</p>}
        {error && <p className="lecture-chat__error" role="alert">{error}</p>}
        <div ref={endRef} />
      </div>
      <form className="lecture-chat__form" onSubmit={submit}>
        <label className="lecture-chat__label" htmlFor={`lecture-chat-question-${lectureId}`}>Ваш вопрос</label>
        <textarea
          id={`lecture-chat-question-${lectureId}`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={1000}
          rows={3}
          placeholder="Например: как лектор определяет предел?"
          disabled={chat.isPending}
          required
        />
        <Button type="submit" size="sm" loading={chat.isPending} disabled={!question.trim()}>
          Отправить
        </Button>
      </form>
    </div>
  );
}
