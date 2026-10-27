import assert from "node:assert/strict";
import { test } from "node:test";
import { buildMatcher, splitHighlights } from "../src/features/search/matcher.ts";

function marked(text, query) {
  return splitHighlights(text, buildMatcher(query))
    .filter((part) => part.marked)
    .map((part) => part.text);
}

test("matcher has no lookbehind so old Safari can compile it", () => {
  assert.doesNotMatch(buildMatcher("производная функции").source, /\(\?<[!=]/);
});

test("short or empty queries give no matcher", () => {
  assert.equal(buildMatcher(""), null);
  assert.equal(buildMatcher("а , ."), null);
  assert.deepEqual(splitHighlights("текст", null), [{ text: "текст", marked: false }]);
});

test("word forms are found by stem from the start of a word", () => {
  assert.deepEqual(marked("Производные функций и функция", "функция"), ["функций", "функция"]);
});

test("a stem inside another word is not marked", () => {
  assert.deepEqual(marked("подфункция и функция", "функция"), ["функция"]);
  assert.deepEqual(marked("матрица2 и 2матрица", "матрица"), ["матрица2"]);
});

test("match at the very start and after punctuation", () => {
  assert.deepEqual(marked("Граф, (граф) и «графы»", "граф"), ["Граф", "граф", "графы"]);
});

test("neighbouring words separated by one space are both marked", () => {
  assert.deepEqual(marked("лемма лемма", "лемма"), ["лемма", "лемма"]);
});

test("parts join back into the original text", () => {
  const text = " Теорема Ферма: теоремы о простых числах ";
  const parts = splitHighlights(text, buildMatcher("теорема простые"));
  assert.equal(parts.map((part) => part.text).join(""), text);
  assert.deepEqual(
    parts.filter((part) => part.marked).map((part) => part.text),
    ["Теорема", "теоремы", "простых"],
  );
});

test("regex symbols in the query are escaped", () => {
  assert.deepEqual(marked("C++ и c# языки", "c++"), []);
  assert.deepEqual(marked("цена (руб.) указана", "(руб.)"), ["руб"]);
});
