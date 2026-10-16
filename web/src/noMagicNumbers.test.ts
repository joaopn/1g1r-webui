/**
 * Project rule: no hardcoded magic numbers. Every tunable value comes from the server's
 * config (defaults.yaml, via /api/meta). Application code may only use 0 and 1. Tests and
 * the vendored shadcn primitives in components/ui are exempt.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import ts from "typescript";

const ROOT = path.resolve(__dirname);
const ALLOWED = new Set([0, 1]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "ui" || name === "test" ? [] : files(full);
    return /\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name) ? [full] : [];
  });
}

test("application code has no magic numbers", () => {
  const offenders: string[] = [];
  for (const file of files(ROOT)) {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
    );
    const visit = (node: ts.Node) => {
      if (ts.isNumericLiteral(node) && !ALLOWED.has(Number(node.text))) {
        const { line } = source.getLineAndCharacterOfPosition(node.getStart());
        offenders.push(`${path.relative(ROOT, file)}:${line + 1}: ${node.text}`);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }
  expect(offenders).toEqual([]);
});
