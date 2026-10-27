import assert from "node:assert/strict";
import { test } from "node:test";
import { isTelegramMode, parseTelegramUser, telegramAuthUrl } from "../src/pages/auth/telegramParams.ts";

const query = (text) => new URLSearchParams(text);

test("разбирает полный набор параметров", () => {
  const user = parseTelegramUser(
    query("id=42&first_name=Иван&last_name=Петров&username=ivan&photo_url=https%3A%2F%2Ft.me%2Fa.jpg&auth_date=1730000000&hash=abc"),
  );
  assert.deepEqual(user, {
    id: 42,
    first_name: "Иван",
    last_name: "Петров",
    username: "ivan",
    photo_url: "https://t.me/a.jpg",
    auth_date: 1730000000,
    hash: "abc",
  });
});

test("необязательные поля не попадают в результат", () => {
  const user = parseTelegramUser(query("id=42&first_name=Иван&auth_date=1730000000&hash=abc"));
  assert.deepEqual(user, { id: 42, first_name: "Иван", auth_date: 1730000000, hash: "abc" });
});

test("без обязательных полей возвращает null", () => {
  assert.equal(parseTelegramUser(query("")), null);
  assert.equal(parseTelegramUser(query("id=42&first_name=Иван&auth_date=1")), null);
  assert.equal(parseTelegramUser(query("first_name=Иван&auth_date=1&hash=abc")), null);
  assert.equal(parseTelegramUser(query("id=42&auth_date=1&hash=abc")), null);
});

test("нечисловые id и auth_date отклоняются", () => {
  assert.equal(parseTelegramUser(query("id=x&first_name=a&auth_date=1&hash=h")), null);
  assert.equal(parseTelegramUser(query("id=1&first_name=a&auth_date=-5&hash=h")), null);
  assert.equal(parseTelegramUser(query("id=1.5&first_name=a&auth_date=1&hash=h")), null);
});

test("режимы и адрес возврата", () => {
  assert.equal(isTelegramMode("link"), true);
  assert.equal(isTelegramMode("other"), false);
  assert.equal(isTelegramMode(undefined), false);
  assert.equal(telegramAuthUrl("https://lecturo.example", "login"), "https://lecturo.example/auth/telegram/login");
});
