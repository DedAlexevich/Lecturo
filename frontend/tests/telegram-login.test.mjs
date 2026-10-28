import assert from "node:assert/strict";
import { test } from "node:test";
import { parseBotId, requestTelegramAuth } from "../src/telegram/login.ts";

test("parseBotId accepts only a positive integer", () => {
  assert.equal(parseBotId("123456789"), 123456789);
  assert.equal(parseBotId(" 42 "), 42);
  assert.equal(parseBotId(undefined), undefined);
  assert.equal(parseBotId(""), undefined);
  assert.equal(parseBotId("0"), undefined);
  assert.equal(parseBotId("-5"), undefined);
  assert.equal(parseBotId("12ab"), undefined);
  assert.equal(parseBotId("123456789:AAH"), undefined);
  assert.equal(parseBotId("99999999999999999999"), undefined);
});

test("requestTelegramAuth asks for write access and returns the user", async () => {
  const user = { id: 1, first_name: "Анна", auth_date: 1700000000, hash: "abc" };
  const calls = [];
  const login = {
    auth: (options, callback) => {
      calls.push(options);
      callback(user);
    },
  };
  assert.deepEqual(await requestTelegramAuth(login, 77), user);
  assert.deepEqual(calls, [{ bot_id: 77, request_access: "write", lang: "ru" }]);
});

test("requestTelegramAuth returns null when the window is closed without login", async () => {
  const login = { auth: (_options, callback) => callback(false) };
  assert.equal(await requestTelegramAuth(login, 77), null);
});
