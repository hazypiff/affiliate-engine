import fs from "node:fs";
import path from "node:path";

const CONTENT_DIR = path.join(process.cwd(), "content");

export function listPages() {
  const manifest = path.join(CONTENT_DIR, "manifest.json");
  if (!fs.existsSync(manifest)) return [];
  return JSON.parse(fs.readFileSync(manifest, "utf8"));
}

export function getPage(vertical, slug) {
  const file = path.join(CONTENT_DIR, vertical, `${slug}.json`);
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

// The tracker owns offer selection (Thompson sampling) and geo-gating at redirect time.
export const TRACKER_BASE = process.env.NEXT_PUBLIC_TRACKER_BASE || "http://127.0.0.1:8000";
