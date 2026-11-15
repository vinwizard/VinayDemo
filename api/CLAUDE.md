# api/ — the HTTP server over the engine, and the owner's /admin page

- `main.py` serves the engine and the built web app (`web/dist`); `why.py` and `fleet.py` stream investigations; `admin.py` manages access passes.
- Must not: hold engine logic or arithmetic, or change a saved run. Routes call the engine and save what it returns.
- Routes and settings: WEB.md.
