# judge/ — what did each answer actually say about each claim?

- `evaluator_model.py` asks a model to propose labels; it is never trusted. `evaluation.py` checks every label against the raw answer, the same way for live and replay.
- A quote must be verbatim in the answer; a domain that appears only in a citation is not a mention; a competitor counts only when named in the answer body.
- Prompts live in `prompts.md` here, one `## NAME` section per constant: edit the text there, not in code.
- Must not: compute scores (score/ does), or keep a label code could not verify.
- More: skill `evaluation-and-scoring`.
