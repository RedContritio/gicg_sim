# GICG web frontend

React 19 + TypeScript + Vite frontend for the live board and replay views.
The backend serves the production build and provides the game-state APIs.

From the repository root:

```sh
npm --prefix web/frontend ci
npm --prefix web/frontend run build
.venv/bin/python -m uvicorn web.backend.app:app --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080/live> for a live game or
<http://localhost:8080/replay> for replay inspection.

For model compatibility, profiles, privacy boundaries, board behavior, and
artifact requirements, see the [web documentation](../README.md).

Available frontend checks:

```sh
npm --prefix web/frontend run lint
npm --prefix web/frontend run build
```
