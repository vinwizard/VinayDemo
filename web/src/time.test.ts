// Stored times, run by `node --test` (CI: web unit tests).
import assert from "node:assert/strict";
import { test } from "node:test";
import { instant } from "./time.ts";

test("a stored time is UTC, with or without its offset written down", () => {
  // Runs saved before the offset was written carry none; read as local time they moved by the viewer's offset.
  assert.equal(instant("2026-09-28T06:57:01").toISOString(), "2026-09-28T06:57:01.000Z");
  assert.equal(instant("2026-09-28T06:57:01+00:00").toISOString(), "2026-09-28T06:57:01.000Z");
  assert.equal(instant("2026-09-28T02:57:01-04:00").toISOString(), "2026-09-28T06:57:01.000Z");
  assert.equal(instant("2026-09-28").toISOString(), "2026-09-28T00:00:00.000Z");   // a bare date is left alone
});
