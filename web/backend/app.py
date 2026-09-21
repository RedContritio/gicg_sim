"""FastAPI entry point for the GICG web UI backend.

Wires together:
- /api/replays*                REST (see replay_api.py)
- /ws/live                     WebSocket (see live_api.py)
- /                            static frontend (mounted if web/frontend/dist exists)

Run with:
    .venv/bin/uvicorn web.backend.app:app --reload --port 8080

The --reload flag is fine for development but will reload the module
on every edit — for live play sessions you probably want to run
without --reload so WebSocket connections survive file saves.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from web.backend import live_api, replay_api
from web.backend.replay_store import ReplayStore


# Resolve paths relative to the repo root (the directory containing
# `web/`, `data/`, `artifacts/`) so uvicorn launched from a
# non-repo-root cwd still finds everything. Previously these were
# bare "artifacts" / "data" Paths, silently empty when cwd differed.
_REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS_ROOT = _REPO_ROOT / 'artifacts'
FRONTEND_DIST = _REPO_ROOT / 'web' / 'frontend' / 'dist'
DATA_ROOT = _REPO_ROOT / 'data'


# /api/checkpoints cache: rglob over artifacts/ can scan thousands of
# .pt files. Cache the result, bust on TTL or manual refresh.
_CHECKPOINTS_CACHE_TTL_S = 5.0
_checkpoints_cache: dict = {'entries': None, 't': 0.0}


def create_app() -> FastAPI:
    app = FastAPI(
        title='GICG Web UI',
        description='Replay browser + live-play agent inspector',
        version='0.1.0',
    )

    # CORS: allow the Vite dev server (port 5173) to call the backend
    # during development. In production the frontend is served from
    # the same origin, so this is only for the split dev setup.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # Replay store — scanned once at startup; client can force a
    # rescan via POST /api/replays/refresh.
    store = ReplayStore(ARTIFACTS_ROOT)
    store.refresh()

    app.include_router(replay_api.make_router(store))
    app.include_router(live_api.router)

    @app.get('/api/health')
    def health() -> dict:
        return {'ok': True, 'replay_count': len(store.list())}

    @app.get('/api/live/profile')
    def live_profile():
        from web.backend.semantic_live import profile

        return profile()

    @app.get('/api/data/chars')
    def list_chars() -> dict:
        """Character roster — union of every data/pools/<id>/characters/
        directory. The team picker shows everything the engine could
        load; per-game pool selection happens at run-config time. New
        chars appear here automatically when added under any pool.
        See ADR-0011 for the pool layout."""
        pools_dir = DATA_ROOT / 'pools'
        if not pools_dir.is_dir():
            return {'chars': []}
        names: set[str] = set()
        for pool in pools_dir.iterdir():
            chars_dir = pool / 'characters'
            if not chars_dir.is_dir():
                continue
            for p in chars_dir.iterdir():
                if p.is_dir() and (p / f'{p.name}.lua').exists():
                    names.add(p.name)
        return {'chars': sorted(names)}

    @app.get('/api/data/cards')
    def list_cards() -> dict:
        """Card roster — union of every data/pools/<id>/cards/ tree.
        Walks recursively so legacy L1..L6 subdirs and any future
        flat layouts are both covered. See ADR-0011."""
        pools_dir = DATA_ROOT / 'pools'
        if not pools_dir.is_dir():
            return {'cards': []}
        names: set[str] = set()
        for pool in pools_dir.iterdir():
            cards_dir = pool / 'cards'
            if not cards_dir.is_dir():
                continue
            for f in cards_dir.rglob('*.lua'):
                names.add(f.stem)
        return {'cards': sorted(names)}

    @app.get('/api/checkpoints')
    def list_checkpoints() -> dict:
        """Discover trained checkpoints under artifacts/. Used by the
        Replay and Live pages to populate a ckpt picker instead of
        requiring users to type paths manually. Classifies each .pt by
        its directory structure:
          - main:    <session>/<curriculum>/<stage>/checkpoint.pt
          - partial: same but suffix .partial.pt (G-scheme fallback)
          - failed:  same but suffix .failed.pt
          - pool:    <session>/pool/pool_*.pt
          - main:    <session>/ckpts/*.pt
          - legacy:  artifacts/checkpoints/*.pt (pre-session layout)
        Sorted by mtime desc so recent runs float to the top.

        Cached for _CHECKPOINTS_CACHE_TTL_S (5s) — the Live page hits
        this endpoint on every mount. Previous implementation rglob'd
        the full artifacts tree every time, which on a long-running
        training workspace (~GB of .pt files) adds a few-hundred-ms
        tax per page visit."""
        now = time.monotonic()
        cached = _checkpoints_cache['entries']
        if cached is not None and (now - _checkpoints_cache['t']) < _CHECKPOINTS_CACHE_TTL_S:
            return {'checkpoints': cached}
        if not ARTIFACTS_ROOT.is_dir():
            _checkpoints_cache['entries'] = []
            _checkpoints_cache['t'] = now
            return {'checkpoints': []}
        entries: list[dict] = []
        for p in ARTIFACTS_ROOT.rglob('*.pt'):
            rel = p.relative_to(ARTIFACTS_ROOT)
            parts = rel.parts
            # Default classification — overwritten below for matched shapes.
            session_id = parts[0] if parts else ''
            stage = ''
            kind = 'other'
            label = str(rel)
            if len(parts) >= 2 and parts[1] == 'pool':
                kind = 'pool'
                stage = parts[-1]  # pool_NNNN.pt
                label = f'{session_id}/pool/{stage}'
            elif len(parts) >= 3 and parts[-1].startswith('checkpoint'):
                # Supports both layouts:
                #   <session>/<curriculum...>/<stage>/checkpoint*.pt  (≥4)
                #   <session>/<stage>/checkpoint*.pt                  (==3)
                stage = parts[-2]
                curriculum = '/'.join(parts[1:-2])  # empty for 3-part layout
                fname = parts[-1]
                if fname == 'checkpoint.pt':
                    kind = 'main'
                elif fname == 'checkpoint.partial.pt':
                    kind = 'partial'
                elif fname == 'checkpoint.failed.pt':
                    kind = 'failed'
                label_parts = [session_id]
                if curriculum:
                    label_parts.append(curriculum)
                label_parts.append(stage)
                label = '/'.join(label_parts)
                if kind != 'main':
                    label += f' [{kind}]'
            elif len(parts) >= 3 and parts[1] == 'ckpts':
                kind = 'main'
                stage = parts[-1]
                label = f'{session_id}/{stage}'
            elif parts[:1] == ('checkpoints',):
                kind = 'legacy'
                session_id = 'checkpoints'
                label = f'legacy/{rel.name}'
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0.0
            entries.append(
                {
                    'path': str(p),
                    'session_id': session_id,
                    'stage': stage,
                    'kind': kind,
                    'label': label,
                    'mtime': mtime,
                }
            )
        entries.sort(key=lambda e: e['mtime'], reverse=True)
        _checkpoints_cache['entries'] = entries
        _checkpoints_cache['t'] = now
        return {'checkpoints': entries}

    # Static frontend — only mount when the dist dir exists, so
    # running the backend without a built frontend doesn't 500.
    if FRONTEND_DIST.exists():

        @app.get('/live')
        @app.get('/replay')
        def frontend_route():
            return FileResponse(FRONTEND_DIST / 'index.html')

        app.mount('/', StaticFiles(directory=str(FRONTEND_DIST), html=True), name='frontend')
    else:

        @app.get('/')
        def root() -> JSONResponse:
            return JSONResponse(
                {
                    'message': 'GICG web UI backend running. Frontend not yet built.',
                    'hint': 'cd web/frontend && npm run build, or use the Vite dev server at http://localhost:5173',
                    'api': {
                        'health': '/api/health',
                        'replays': '/api/replays',
                        'live': '/ws/live (WebSocket)',
                    },
                }
            )

    return app


app = create_app()
