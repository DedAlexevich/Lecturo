import assert from "node:assert/strict";
import { test } from "node:test";
import { isTelegramLaunch } from "../src/telegram/loadSdk.ts";

test("launch data in the hash means the page is opened inside Telegram", () => {
  assert.equal(isTelegramLaunch("#tgWebAppData=query_id%3D1&tgWebAppVersion=8.0", null, false), true);
});

test("saved launch data keeps the Mini App working after a reload", () => {
  assert.equal(isTelegramLaunch("", '{"tgWebAppData":"query_id=1"}', false), true);
});

test("the Telegram webview proxy marks a Mini App without launch data", () => {
  assert.equal(isTelegramLaunch("", null, true), true);
});

test("an ordinary browser page does not load the Telegram script", () => {
  assert.equal(isTelegramLaunch("", null, false), false);
  assert.equal(isTelegramLaunch("#summary", null, false), false);
  assert.equal(isTelegramLaunch("", '{"tgWebAppVersion":"8.0"}', false), false);
});
