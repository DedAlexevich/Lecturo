import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import type { components } from "../../api/schema";
import { api } from "../../api/client";
import { ApiError } from "../../app/queryClient";
import { Button } from "../../ui/Button";
import { formatTimecode } from "../../lib/timecode";
import { answerScrollTop, hasContentBelow, keyboardOverlap, scrollIntent } from "./chatScroll";
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

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function ChatPanel({ lectureId, onSelectTime }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>(() => restoreMessages(lectureId));
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [contentBelow, setContentBelow] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const lastMessageRef = useRef<HTMLElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const fieldRef = useRef<HTMLTextAreaElement>(null);
  const shownCount = useRef<number | null>(null);
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
  }, [lectureId, messages]);

  const updateContentBelow = useCallback(() => {
    const list = listRef.current;
    if (list) setContentBelow(hasContentBelow(list));
  }, []);

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      const list = listRef.current;
      if (!list) return;
      list.scrollTo({ top: list.scrollHeight, behavior });
      updateContentBelow();
    },
    [updateContentBelow],
  );

  useLayoutEffect(() => {
    const list = listRef.current;
    const intent = scrollIntent(shownCount.current, messages.map((message) => message.role));
    shownCount.current = messages.length;
    if (!list) return;
    if (intent === "bottom") {
      scrollToBottom();
    } else if (intent === "answer" && lastMessageRef.current) {
      list.scrollTop = answerScrollTop({
        scrollTop: list.scrollTop,
        containerTop: list.getBoundingClientRect().top,
        messageTop: lastMessageRef.current.getBoundingClientRect().top,
        inset: parseFloat(getComputedStyle(list).paddingTop) || 0,
      });
    }
    updateContentBelow();
  }, [messages, scrollToBottom, updateContentBelow]);

  useLayoutEffect(() => {
    if (chat.isPending || error) scrollToBottom();
  }, [chat.isPending, error, scrollToBottom]);

  useLayoutEffect(() => {
    const field = fieldRef.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${field.scrollHeight + field.offsetHeight - field.clientHeight}px`;
  }, [question]);

  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const keepFormVisible = () => {
      const form = formRef.current;
      if (!form || !form.contains(document.activeElement)) return;
      const overlap = keyboardOverlap({
        elementBottom: form.getBoundingClientRect().bottom,
        viewportTop: viewport.offsetTop,
        viewportHeight: viewport.height,
      });
      if (overlap > 0) window.scrollBy({ top: overlap });
    };
    viewport.addEventListener("resize", keepFormVisible);
    return () => viewport.removeEventListener("resize", keepFormVisible);
  }, []);

  useEffect(() => {
    window.addEventListener("resize", updateContentBelow);
    return () => window.removeEventListener("resize", updateContentBelow);
  }, [updateContentBelow]);

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

  const submitOnEnter = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;
    event.preventDefault();
    formRef.current?.requestSubmit();
  };

  return (
    <div className="lecture-chat">
      <div className="lecture-chat__viewport">
        <div
          ref={listRef}
          className="lecture-chat__messages"
          aria-live="polite"
          aria-label="История чата"
          onScroll={updateContentBelow}
        >
          {messages.length === 0 && (
            <p className="lecture-chat__empty">Задайте вопрос по лекции. Ответ будет опираться на расшифровку и главы.</p>
          )}
          {messages.map((message, index) => (
            <article
              key={`${message.role}-${index}`}
              ref={index === messages.length - 1 ? lastMessageRef : undefined}
              className={`lecture-chat__message lecture-chat__message--${message.role}`}
            >
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
        </div>
        {contentBelow && (
          <button type="button" className="lecture-chat__to-bottom" onClick={() => scrollToBottom(reducedMotion() ? "auto" : "smooth")}>
            Прокрутить вниз
          </button>
        )}
      </div>
      <form ref={formRef} className="lecture-chat__form" onSubmit={submit}>
        <label className="lecture-chat__label" htmlFor={`lecture-chat-question-${lectureId}`}>Ваш вопрос</label>
        <textarea
          ref={fieldRef}
          id={`lecture-chat-question-${lectureId}`}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={submitOnEnter}
          maxLength={1000}
          rows={1}
          placeholder="Вопрос по лекции"
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
