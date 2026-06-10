// Sync docs/public/** → site/src/content/docs/
//
// Why this exists: VideoCraft's published docs are authored in
// <repo>/docs/public/, but Starlight reads from site/src/content/docs/.
// This script mirrors the public tree into the Starlight content
// directory before each build.
//
// Behavior:
//   - Wipes site/src/content/docs/ entirely (it is build output, gitignored)
//   - Recursively copies docs/public/ over
//   - Hardcoded skip: filenames starting with "_" (drafts/WIP) and "."
//
// Anything *not* under docs/public/ is never published, by construction.

import { readdir, mkdir, copyFile, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(here, '..', '..');
const SRC = resolve(REPO_ROOT, 'docs', 'public');
const DEST = resolve(here, '..', 'src', 'content', 'docs');

async function copyTree(src, dest) {
  const entries = await readdir(src, { withFileTypes: true });
  await mkdir(dest, { recursive: true });
  for (const entry of entries) {
    if (entry.name.startsWith('_') || entry.name.startsWith('.')) continue;
    const s = join(src, entry.name);
    const d = join(dest, entry.name);
    if (entry.isDirectory()) {
      await copyTree(s, d);
    } else if (entry.isFile()) {
      await copyFile(s, d);
    }
  }
}

async function main() {
  if (!existsSync(SRC)) {
    console.error(`[sync-docs] Source directory missing: ${SRC}`);
    process.exit(1);
  }
  if (existsSync(DEST)) {
    await rm(DEST, { recursive: true, force: true });
  }
  await copyTree(SRC, DEST);
  console.log(`[sync-docs] ${SRC} → ${DEST}`);
}

main().catch((err) => {
  console.error('[sync-docs] failed:', err);
  process.exit(1);
});
