export function notesPrompts(language: string): { system: string; user: string } {
  if (language === "en") {
    return {
      system: "You create lecture notes. Respond only in English, based only on the transcript. Do not add facts.",
      user: "Give this excerpt a short one-line title. Then write detailed notes as a list of key points. Do not add an introduction.",
    };
  }
  return {
    system: "Ты составляешь конспект лекции. Отвечай только на русском языке, опирайся только на текст. Не добавляй факты от себя.",
    user: "Назови тему фрагмента одной короткой строкой. Затем с новой строки напиши подробный конспект фрагмента в виде списка ключевых мыслей. Не добавляй вводных слов.",
  };
}
