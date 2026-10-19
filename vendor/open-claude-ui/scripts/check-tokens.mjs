#!/usr/bin/env node
/**
 * 断言 AGENTS.md 里引用的每个 `--cds-*` 都在 cds-theme.css 里有定义。
 * 退出码 0 = 通过，1 = 有未定义引用（可用作 CI 门禁）。
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(process.argv[2] ?? '.');
const DOC = 'AGENTS.md';
const CSS = 'code-examples/cds-theme.css';

const css = fs.readFileSync(path.join(ROOT, CSS), 'utf8');
const doc = fs.readFileSync(path.join(ROOT, DOC), 'utf8');

const defined = new Map();
for (const m of css.matchAll(/(--cds-[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
  if (!defined.has(m[1])) defined.set(m[1], m[2].trim());
}

const referenced = [...new Set([...doc.matchAll(/`(--cds-[a-z0-9-]+)`/g)].map((m) => m[1]))];
const missing = referenced.filter((t) => !defined.has(t));

console.log(`定义: ${defined.size} 个 token（${CSS}）`);
console.log(`引用: ${referenced.length} 个 token（${DOC}）`);

if (!missing.length) {
  console.log('\n✓ 全部引用都有定义');
  process.exit(0);
}

console.log(`\n✗ ${missing.length} 个引用没有定义：\n`);
for (const t of missing) {
  const i = doc.indexOf('`' + t + '`');
  const line = doc.slice(0, i).split('\n').length;
  const stem = t.replace(/^--cds-/, '').split('-')[0];
  const near = [...defined.keys()].filter((d) => d.startsWith(`--cds-${stem}`));
  console.log(`  ${t}   (AGENTS.md:${line})`);
  if (near.length) console.log(`      同词根候选: ${near.join(', ')}`);
}
process.exit(1);
