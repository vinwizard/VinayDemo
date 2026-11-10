# web/ — the React app people use

- `src/api.ts` mirrors `core/schemas.py`, and `src/labels.ts` mirrors `core/labels.py`: change both sides together.
- Logic that needs a test goes in a plain `.ts` file beside its component (`quickwins.ts`, `tour.ts`) so `node --test` runs it.
- Must not: score answers (the engine does), or show a replay without its label.
- Check: `npx tsc -b && npx oxlint && npm test`.
