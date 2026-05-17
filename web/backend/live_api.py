"""Live-play WebSocket endpoint.

One WebSocket connection = one GicgEnv + one AI opponent. The human
drives their side of the board; the server auto-advances the AI side
between human decisions.

Opponent construction delegates to training.core.matchup.matchup.load_player — same
LOADERS registry used by the gauntlet, so every opponent type the
eval pipeline supports is available for live play without duplicate
glue. Supported types: ``az``, ``cfr``, ``mcts_pure``, ``random``.

Message protocol (JSON):

    Client → server: start a new game
        {"type": "new",
         "team_0": ["赤蝶"], "team_1": ["墨客"],
         "card_pool": [...] | null,
         "data_dir": "data",
         "human_player": 0,               # 0 (default) or 1
         "opponent": {"type": "mcts_pure", "n_simulations": 200}}

        # Other opponent specs:
        # {"type": "az",        "ckpt": "...", "n_simulations": 200}
        # {"type": "cfr",       "ckpt": "...", "n_simulations": 0}
        # {"type": "random"}

    Server → client: board state after AI has auto-advanced up to the
    human's next decision point (or terminal)
        {"type": "state",
         "view": {...StateView...},
         "done": false,
         "current_player": 0,
         "winner": -1,
         "legal_actions": [
             {"index": 0, "kind": 0, "kind_name": "Skill", "name": "枪"},
             ...
         ]}

    Client → server: human picks an action
        {"type": "action", "index": 3}

    Server → client: error (malformed input, illegal move, etc.)
        {"type": "error", "message": "..."}

Session-building, ckpt validation, agent advancement, and the
LRU builder cache live in ``web.backend.live_session`` — this file
owns only the router, websocket handler, and message dispatch.
"""

from __future__ import annotations

import asyncio
import random
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gicg_env import GicgEnv
from web.backend.live_session import (
    WS_IDLE_TIMEOUT_S,
    LiveSession,
    auto_advance_agent,
    build_legal_actions,
    build_opponent_player,
    get_winner,
    sanitize_error,
)

router = APIRouter()


async def _send_state(ws: WebSocket, sess: LiveSession) -> None:
    view = sess.env.export_view()
    payload = {
        'type': 'state',
        'view': view,
        'done': sess.env.done,
        'current_player': sess.env.current_player,
        'legal_actions': build_legal_actions(sess.env),
        'human_player': sess.human_player,
    }
    if sess.env.done:
        payload['winner'] = get_winner(sess.env)
    await ws.send_json(payload)


async def _handle_new(
    ws: WebSocket,
    msg: dict,
    prev: Optional[LiveSession],
) -> Optional[LiveSession]:
    """Build a new LiveSession from a 'new' message. Returns the new
    session or None if construction failed (error already sent). Also
    releases the previous session's env on success — done after the
    new env is constructed so a failure leaves the old session alive
    (C2 from the review)."""
    team_0 = msg.get('team_0') or ['赤蝶']
    team_1 = msg.get('team_1') or ['墨客']
    if not isinstance(team_0, list) or not team_0:
        raise ValueError('team_0 must be a non-empty list of char names')
    if not isinstance(team_1, list) or not team_1:
        raise ValueError('team_1 must be a non-empty list of char names')

    card_pool = msg.get('card_pool')
    data_dir = msg.get('data_dir', 'data')
    pool = msg.get('pool', ['v_legacy', 'test_basic'])
    deck_padding = msg.get('deck_padding', {'card': '碌碌无为', 'target_size': 15})
    human_player = int(msg.get('human_player', 0))
    if human_player not in (0, 1):
        raise ValueError(f'human_player must be 0 or 1, got {human_player}')

    opponent_spec = msg.get('opponent')
    if not isinstance(opponent_spec, dict):
        raise ValueError(
            "missing 'opponent' field; expected a spec dict like {'type': 'mcts_pure', 'n_simulations': 200}"
        )
    # seed: client-supplied or fresh random — no hardcoded default so
    # "restart with same config" gives a fresh game (H5 from review).
    if 'seed' in msg:
        seed = int(msg['seed'])
    else:
        seed = random.randrange(1, 2**31)

    # Construct new player + env FIRST so a failure doesn't kill the
    # previous session. Only release prev after both succeed.
    player = build_opponent_player(opponent_spec, seed)
    env = GicgEnv(
        team_0,
        team_1,
        card_pool=card_pool,
        data_dir=data_dir,
        pool=pool,
        deck_padding=deck_padding,
    )
    env.reset(seed=seed)

    if prev is not None:
        try:
            prev.env.close()
        except Exception:
            pass
        # Explicit drop of old player / env references; without this,
        # the caller's `session` variable still held a LiveSession that
        # could only be GC'd after re-assignment, which briefly pinned
        # old weights alongside the new ones. Zeroing here makes the
        # old player eligible for GC the moment `_handle_new` returns.
        prev.env = None  # type: ignore[assignment]
        prev.player = None  # type: ignore[assignment]

    sess = LiveSession(env=env, player=player, human_player=human_player)
    auto_advance_agent(sess)
    return sess


async def _handle_action(ws: WebSocket, msg: dict, sess: LiveSession) -> None:
    """Process a human action message. Raises ValueError on malformed
    input (bubbled up to the main loop's try block, which sends an
    error frame)."""
    if sess.env.done:
        raise ValueError('game already ended')
    if sess.env.current_player != sess.human_player:
        raise ValueError('not your turn')
    try:
        idx = int(msg.get('index'))
    except (TypeError, ValueError):
        raise ValueError('action index must be an integer')
    kinds, _ = sess.env.get_legal_actions()
    if idx < 0 or idx >= len(kinds):
        raise ValueError(f'illegal action index {idx}')
    sess.env.step(idx)
    auto_advance_agent(sess)


@router.websocket('/ws/live')
async def live_ws(ws: WebSocket) -> None:
    """Main WebSocket handler. Every per-message action is wrapped in
    try/except so a single bad input or a player.select_action
    exception sends an error frame instead of killing the connection
    (A1 from the review)."""
    await ws.accept()
    session: Optional[LiveSession] = None
    try:
        while True:
            try:
                msg = await asyncio.wait_for(
                    ws.receive_json(),
                    timeout=WS_IDLE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                # Idle too long — close the socket so the server can
                # release the session's player / env / ckpt.
                try:
                    await ws.send_json(
                        {
                            'type': 'error',
                            'message': 'idle timeout; reconnect to resume',
                        }
                    )
                except Exception:
                    pass
                break
            except WebSocketDisconnect:
                break
            kind = msg.get('type')
            try:
                if kind == 'new':
                    new_sess = await _handle_new(ws, msg, session)
                    if new_sess is not None:
                        session = new_sess
                        await _send_state(ws, session)
                elif kind == 'action':
                    if session is None:
                        await ws.send_json(
                            {
                                'type': 'error',
                                'message': "no active session; send 'new' first",
                            }
                        )
                        continue
                    await _handle_action(ws, msg, session)
                    await _send_state(ws, session)
                else:
                    await ws.send_json(
                        {
                            'type': 'error',
                            'message': f'unknown message type {kind!r}',
                        }
                    )
            except WebSocketDisconnect:
                raise
            except Exception as exc:
                try:
                    await ws.send_json(
                        {
                            'type': 'error',
                            'message': sanitize_error(exc),
                        }
                    )
                except Exception:
                    # Client went away mid-send; we'll hit
                    # WebSocketDisconnect on the next recv.
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        if session is not None:
            try:
                session.env.close()
            except Exception:
                pass
