"""Replay browsing + step-by-step playback REST API.

Endpoints:
- GET /api/replays
    List all indexed replay YAMLs under artifacts/.
- POST /api/replays/refresh
    Force a rescan of the artifacts tree (after a new training run).
- GET /api/replay/{rel_path:path}?step=N&ckpt=...
    Rewind a replay to step N, return the view + optional agent
    inspection. When ckpt is supplied we run an agent forward pass on
    the rewound state and include attention/policy/value.

Rewind is driven by the Go-side record.ReplayTo, wired through
GameReplayToJSON (capi). Each request builds a fresh GicgEnv
matching the record's team roster (extracted via
record_extract_info), jumps to the target round via record.Load,
and step-forwards the remaining in-round actions. Fast enough for
a dev tool — no caching yet.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from gicg_env import GicgEnv
from gicg_env.engine import record_extract_info
from web.backend.agent_inspector import AgentInspector
from web.backend.replay_store import ReplayStore


def make_router(store: ReplayStore) -> APIRouter:
    """Factory so the store instance is closed over — avoids module
    globals for the FastAPI dependency wiring. A fresh APIRouter is
    created per call so re-invoking make_router() doesn't pile up
    duplicate routes on a shared module-level router."""
    router = APIRouter()

    @router.get('/api/replays')
    def list_replays() -> dict:
        return {
            'replays': [
                {
                    'rel_path': e.rel_path,
                    'session_id': e.session_id,
                    'curriculum': e.curriculum,
                    'stage': e.stage,
                    'scenario': e.scenario,
                    'size_bytes': e.size_bytes,
                }
                for e in store.list()
            ]
        }

    @router.post('/api/replays/refresh')
    async def refresh_replays() -> dict:
        # rglob over GB-scale artifacts/ can take multiple seconds.
        # Run in a threadpool so the event loop can serve other
        # requests + WebSockets in parallel.
        await asyncio.to_thread(store.refresh)
        return {'count': len(store.list())}

    @router.get('/api/replay/{rel_path:path}')
    def get_replay(
        rel_path: str,
        step: int = Query(0, ge=0),
        ckpt: Optional[str] = Query(None),
    ) -> dict:
        entry = store.find(rel_path)
        if entry is None:
            raise HTTPException(404, f'replay not found: {rel_path}')
        try:
            info = record_extract_info(entry.abs_path)
        except RuntimeError as e:
            raise HTTPException(500, f'extract info: {e}')
        if step > info['total_steps']:
            raise HTTPException(
                400,
                f'step {step} exceeds total {info["total_steps"]}',
            )
        # Replays may reference cards/chars from any pool (historical
        # 赤蝶_vs_刻师傅.yaml mixes prod chars with 测试卡 + v_phase2 卡
        # like 最好的伙伴！/ 派蒙 / 旅行剑). Union all 3 bootstrap pools
        # so any pre-ADR-0011 replay still loads.
        env = GicgEnv(
            info['teams'][0],
            info['teams'][1],
            pool=['v_legacy', 'test_basic', 'v_phase2'],
        )
        try:
            try:
                result = env.replay_to(entry.abs_path, step)
            except RuntimeError as e:
                raise HTTPException(500, f'replay: {e}')
            agent_payload = None
            if ckpt:
                try:
                    insp = AgentInspector(ckpt, env).inspect(env)
                    agent_payload = {
                        'value': insp.value,
                        'entropy': insp.entropy,
                        'policy': insp.policy,
                        'top_k': insp.top_k,
                        'attention': insp.attention,
                        'legal_actions': insp.legal_actions,
                    }
                except NotImplementedError:
                    # Inspector is explicitly a stub (see
                    # agent_inspector.py). Give the client a stable
                    # "service unavailable" signal instead of the
                    # internal error text; frontend shows a friendly
                    # placeholder when agent field is null.
                    agent_payload = None
                except Exception:
                    # Any other failure (ckpt load, forward) is an
                    # internal problem — don't leak its details to
                    # the client. Log server-side is a future item;
                    # today just swallow and mark unavailable.
                    agent_payload = None
            return {
                'rel_path': entry.rel_path,
                'stage': entry.stage,
                'step': step,
                'total_steps': info['total_steps'],
                'rounds': info['rounds'],
                'winner': result.get('winner', info.get('winner', -1)),
                'teams': info['teams'],
                'view': result['view'],
                'agent': agent_payload,
            }
        finally:
            env.close()

    return router
