import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";

const allowed = [/^\/\/\s*eslint-disable/, /^\/\*\s*eslint-disable/, /^\/\/\s*@ts-expect-error/];
const skipped = new Set(["src/api/schema.d.ts"]);

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(ts|tsx|js|jsx|mjs)$/.test(name) && !skipped.has(path) ? [path] : [];
  });
}

function findComments(path) {
  const text = readFileSync(path, "utf8");
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true);
  const found = new Map();
  const collect = (ranges) => {
    for (const range of ranges ?? []) {
      const comment = text.slice(range.pos, range.end);
      if (!allowed.some((re) => re.test(comment))) found.set(range.pos, comment);
    }
  };
  const visit = (node) => {
    if (node.kind !== ts.SyntaxKind.JsxText) {
      collect(ts.getLeadingCommentRanges(text, node.pos));
      collect(ts.getTrailingCommentRanges(text, node.end));
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  collect(ts.getLeadingCommentRanges(text, source.endOfFileToken.pos));
  return [...found].map(([pos, comment]) => {
    const line = source.getLineAndCharacterOfPosition(pos).line + 1;
    return `${path}:${line}: ${comment.split("\n")[0]}`;
  });
}

const problems = process.argv.slice(2).flatMap(walk).flatMap(findComments);
if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`Комментарии в коде запрещены: ${problems.length}`);
  process.exit(1);
}
