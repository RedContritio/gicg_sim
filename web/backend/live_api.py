"""Live WebSocket games: new/action requests and human-perspective states."""

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
    record_action,
    sanitize_error,
)

router = APIRouter()

# F4 pinned default decks. The pre-F4 engine silently truncated the
# implicit eligible set to deck_padding.target_size (byte-order head);
# the default union pool ['v_legacy', 'test_basic'] has > 15 eligible
# cards, so under F4 fail-loud a default 'new' (no card_pool, no decks)
# would error out 100% of the time. These are the truncation-era
# effective decks — byte-order first 15 of each single-char team's
# eligible set, captured with the pre-F4 engine via
# `_f4_probe_decks.py before` (scenario union_chidie_moke, 2026-06-12;
# 守正 is 墨客-only, hence the per-team split; 以逸待劳 was a dead card
# in the truncation era so it is correctly absent). Applied only when
# the message leaves the whole deck context at defaults and both teams
# are pinned-known; client-supplied decks always win.
_DEFAULT_POOL = ['v_legacy', 'test_basic']
_DEFAULT_DECK_PADDING = {'card': '碌碌无为', 'target_size': 15}
_DEFAULT_DECKS_BY_TEAM = {
    ('赤蝶',): '乘胜追击 以攻代守 以牙还牙 伏兵之术 佛跳墙 占星 反制 测试卡_增幅 测试卡_碎片 '
    '测试卡_神秘水流 清洁时间 玄冰 瞬身之术 美味烧鸡 荷花酥'.split(),
    ('墨客',): '乘胜追击 以攻代守 以牙还牙 伏兵之术 佛跳墙 占星 反制 守正 测试卡_增幅 测试卡_碎片 '
    '测试卡_神秘水流 清洁时间 玄冰 瞬身之术 美味烧鸡'.split(),
}


def _default_decks(team_0, team_1, card_pool, pool, deck_padding):
    """Return the pinned truncation-era decks for the default-pool
    scenario, or None (implicit path — fail-loud on overflow). Any
    deviation from the default deck context (custom card_pool / pool /
    deck_padding) or a non-pinned team falls through to None."""
    if card_pool is not None or pool != _DEFAULT_POOL or deck_padding != _DEFAULT_DECK_PADDING:
        return None
    d0 = _DEFAULT_DECKS_BY_TEAM.get(tuple(team_0))
    d1 = _DEFAULT_DECKS_BY_TEAM.get(tuple(team_1))
    if d0 is None or d1 is None:
        return None
    return [list(d0), list(d1)]


async def _send_state(ws: WebSocket, sess: LiveSession) -> None:
    from web.backend.live_view import live_view

    view = live_view(sess.env, sess.human_player)
    payload = {
        'type': 'state',
        'view': view,
        'done': sess.env.done,
        'current_player': sess.env.acting_player,
        'legal_actions': build_legal_actions(sess.env),
        'human_player': sess.human_player,
        'history': sess.history[-100:],
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
    # F4: optional explicit per-player decks ([deck_p0, deck_p1], per-entry
    # None = implicit path). Without this, the engine fail-louds when the
    # eligible set exceeds deck_padding.target_size — silent truncation is
    # gone, so full-pool games must declare decks (or shrink card_pool).
    # When the client omits decks and the deck context is at defaults,
    # fall back to the pinned truncation-era decks (see module top).
    decks = msg.get('decks')
    if decks is None:
        decks = _default_decks(team_0, team_1, card_pool, pool, deck_padding)
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
    if opponent_spec.get('type') == 'semantic_rl' or (
        opponent_spec.get('type') == 'random' and msg.get('profile_rules')
    ):
        from web.backend.semantic_live import build_practice_session, build_session

        builder = build_session if opponent_spec.get('type') == 'semantic_rl' else build_practice_session
        sess = builder(msg, seed, human_player)
        try:
            auto_advance_agent(sess)
        except BaseException:
            sess.env.close()
            raise
        if prev is not None:
            prev.env.close()
        return sess

    player = build_opponent_player(opponent_spec, seed)
    env = GicgEnv(
        team_0,
        team_1,
        card_pool=card_pool,
        data_dir=data_dir,
        pool=pool,
        deck_padding=deck_padding,
        decks=decks,
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
    if sess.env.acting_player != sess.human_player:
        raise ValueError('not your turn')
    try:
        idx = int(msg.get('index'))
    except (TypeError, ValueError):
        raise ValueError('action index must be an integer')
    kinds, _ = sess.env.get_legal_actions()
    if idx < 0 or idx >= len(kinds):
        raise ValueError(f'illegal action index {idx}')
    record_action(sess, idx)
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
