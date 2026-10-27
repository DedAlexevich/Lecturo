import assert from "node:assert/strict";
import { test } from "node:test";
import { chooseLocalDelivery, chooseShareMode } from "../src/local/export/delivery.ts";
import { nextLinkStep } from "../src/pages/lecture/exportLink.ts";

const file = new File(["# Лекция"], "lecture.md", { type: "text/markdown" });

test("local export opens a dialog in the Mini App and downloads in a browser", () => {
  assert.equal(chooseLocalDelivery(true), "dialog");
  assert.equal(chooseLocalDelivery(false), "download");
});

test("share mode is none without the Web Share API", () => {
  assert.equal(chooseShareMode({}, file), "none");
  assert.equal(chooseShareMode({ share: "yes" }, file), "none");
});

test("share mode prefers a file when the browser can share files", () => {
  const calls = [];
  const support = { share: () => {}, canShare: (data) => { calls.push(data); return true; } };
  assert.equal(chooseShareMode(support, file), "file");
  assert.deepEqual(calls, [{ files: [file] }]);
});

test("share mode falls back to text when files cannot be shared", () => {
  assert.equal(chooseShareMode({ share: () => {}, canShare: () => false }, file), "text");
  assert.equal(chooseShareMode({ share: () => {} }, file), "text");
  assert.equal(chooseShareMode({ share: () => {}, canShare: () => true }, null), "text");
  assert.equal(chooseShareMode({ share: () => {}, canShare: () => { throw new TypeError("bad"); } }, file), "text");
});

test("a working link is opened", () => {
  assert.equal(nextLinkStep(200, false), "open");
  assert.equal(nextLinkStep(204, true), "open");
});

test("an expired link is requested again only once", () => {
  assert.equal(nextLinkStep(401, false), "refresh");
  assert.equal(nextLinkStep(401, true), "fail");
});

test("other failures show an error instead of opening the link", () => {
  for (const status of [0, 403, 404, 409, 500, 503]) assert.equal(nextLinkStep(status, false), "fail");
  assert.equal(nextLinkStep(302, false), "fail");
});
