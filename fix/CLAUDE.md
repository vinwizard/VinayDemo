# fix/ — why does AI say this, and what would change it?

- `why.py` experiments on a recorded reading list (drop a source, drop a passage, edit a page). `fleet.py` runs several at once with a coordinator, critic and planner; `verify.py` re-asks once a fix is live. `win_back.py` proposes one fix per claim; `retrieval.py` simulates which passage AI would read, before and after a rewrite.
- Replays are `counterfactual_replay`, kept in their own `Investigation` record.
- Must not: change a saved run, move any score, or keep a model-proposed fix whose references code cannot check.
- More: WEB.md "Investigation fleet".
