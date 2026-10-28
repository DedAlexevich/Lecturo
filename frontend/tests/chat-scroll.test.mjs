import assert from "node:assert/strict";
import { test } from "node:test";
import { answerScrollTop, hasContentBelow, keyboardOverlap, scrollIntent } from "../src/pages/lecture/chatScroll.ts";

test("restored history opens at the bottom", () => {
  assert.equal(scrollIntent(null, ["user", "assistant"]), "bottom");
  assert.equal(scrollIntent(null, []), null);
});

test("new question scrolls to the bottom, new answer to its start", () => {
  assert.equal(scrollIntent(1, ["user", "assistant", "user"]), "bottom");
  assert.equal(scrollIntent(2, ["user", "assistant", "user"]), "bottom");
  assert.equal(scrollIntent(1, ["user", "assistant"]), "answer");
});

test("unchanged history keeps the position", () => {
  assert.equal(scrollIntent(2, ["user", "assistant"]), null);
});

test("answer start is aligned to the top of the list", () => {
  assert.equal(answerScrollTop({ scrollTop: 100, containerTop: 200, messageTop: 500, inset: 16 }), 384);
  assert.equal(answerScrollTop({ scrollTop: 0, containerTop: 200, messageTop: 205, inset: 16 }), 0);
});

test("scroll down button appears only when content is hidden below", () => {
  assert.equal(hasContentBelow({ scrollTop: 0, clientHeight: 400, scrollHeight: 400 }), false);
  assert.equal(hasContentBelow({ scrollTop: 560, clientHeight: 400, scrollHeight: 1000 }), false);
  assert.equal(hasContentBelow({ scrollTop: 300, clientHeight: 400, scrollHeight: 1000 }), true);
});

test("keyboard overlap is measured against the visual viewport", () => {
  assert.equal(keyboardOverlap({ elementBottom: 600, viewportTop: 0, viewportHeight: 700 }), 0);
  assert.equal(keyboardOverlap({ elementBottom: 600, viewportTop: 0, viewportHeight: 420 }), 180);
  assert.equal(keyboardOverlap({ elementBottom: 600, viewportTop: 100, viewportHeight: 420 }), 80);
});
