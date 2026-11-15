# providers/ prompts

Each `## NAME` section is the constant NAME in `live.py`, loaded by `core/llm.prompt`.
The text from the blank line under a heading to the next heading is sent exactly as written. Where
the code fills a prompt in, it fills each `{field}`, and `{{` `}}` stand for one brace; a prompt it
sends as is keeps single braces. tests/test_core.py checks each section's fields.

## NEUTRAL_INSTRUCTION

Answer the user's question as a helpful assistant. Use web search. Recommend specific products where appropriate and cite sources.
