import { CreateMLCEngine } from "@mlc-ai/web-llm";
import { splitTranscript } from "./chunks";
import { notesPrompts } from "./prompt";
import type { LocalChapter, LocalSegment } from "../storage";

const MODEL = "Qwen2.5-1.5B-Instruct-q4f32_1-MLC";

self.onmessage = async (event: MessageEvent<{ segments: LocalSegment[]; language: string }>) => {
  try {
    const chunks = splitTranscript(event.data.segments);
    if (!chunks.length) throw new Error("В расшифровке нет текста");
    const engine = await CreateMLCEngine(MODEL, {
      initProgressCallback: (progress) => self.postMessage({ type: "loading", value: progress.progress }),
    });
    const prompts = notesPrompts(event.data.language);
    const chapters: LocalChapter[] = [];
    const notes: string[] = [];
    for (const [index, chunk] of chunks.entries()) {
      self.postMessage({ type: "generating", value: index / chunks.length });
      const response = await engine.chat.completions.create({
        messages: [
          { role: "system", content: prompts.system },
          { role: "user", content: `${prompts.user}\n\n${chunk.text}` },
        ],
        temperature: 0.2,
        max_tokens: 512,
      });
      if (response.choices[0]?.finish_reason === "length") throw new Error("Ответ модели не поместился целиком. Попробуйте создать конспект ещё раз.");
      const content = response.choices[0]?.message.content?.trim();
      if (!content) throw new Error("Модель вернула пустой ответ");
      const [first, ...rest] = content.split("\n");
      const title = first.replace(/^#+\s*|^\*\*|\*\*$/g, "").trim();
      const summary = rest.join("\n").trim();
      if (!title || !summary) throw new Error("Не удалось разобрать ответ модели");
      chapters.push({ start: chunk.start, end: chunk.end, title, summary });
      notes.push(`### ${title}\n\n${summary}`);
    }
    await engine.unload();
    self.postMessage({ type: "done", chapters, summaryMd: notes.join("\n\n") });
  } catch (error) {
    self.postMessage({ type: "error", message: error instanceof Error ? error.message : String(error) });
  }
};
