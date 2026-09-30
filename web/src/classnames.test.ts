// A class name the guide dialog owns, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (f: string) => readFileSync(new URL(f, import.meta.url), "utf8");

test("the report never borrows the guide dialog's .story class", () => {
  // Amgen, 29 Sep 2026: "What the AI searched" wrote its one-sentence story as <p class="callout story">,
  // and the guide's `.story` rule (a 640px flex-column dialog with a big shadow) styled it too: it
  // floated like a dialog, and every search in the sentence stacked on its own line after a stray comma.
  assert.match(read("./index.css"), /^\.story \{[^}]*flex-direction: column/m);
  const classes = [...read("./components.tsx").matchAll(/className="([^"]*)"/g)].map((m) => m[1].split(/\s+/));
  assert.deepEqual(classes.filter((c) => c.includes("story")), []);
});
