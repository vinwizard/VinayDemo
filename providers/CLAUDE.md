# providers/ — where answers come from

- `live.py` is the measured model (OpenAI Responses with web search). Every ask forces search (`TOOL_CHOICE`) and retries once when none ran. `fixture.py` replays authored scenarios; everything it returns is `synthetic`. `company.py` builds questions for a saved company.
- Must not: fall back to fixtures when a live key is missing (error instead), or label a replay as measured.
- More: skill `evidence-modes`; settings in WEB.md "Live mode".
