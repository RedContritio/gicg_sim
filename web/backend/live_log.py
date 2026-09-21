"""Durable event and replay recording for Web live matches."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


class LiveGameLog:
    def __init__(self, root: Path, config: dict[str, Any], seed: int, env) -> None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        self.session_id = f'{stamp}_web_live_{uuid4().hex[:8]}'
        self.directory = root / self.session_id / 'web'
        self.replay_path = self.directory / 'replays' / 'match.yaml'
        self.events_path = self.directory / 'events.jsonl'
        self.metadata_path = self.directory / 'metadata.json'
        self._lock = Lock()
        self._sequence = 0
        self._finished = False
        self.replay_path.parent.mkdir(parents=True, exist_ok=False)
        metadata = {
            'schema': 'gicg.web.live-log/1',
            'session_id': self.session_id,
            'started_at': self._now(),
            'seed': seed,
            'config': config,
        }
        self.metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + '\n',
            encoding='utf-8',
        )
        self._append('session_started', {'seed': seed})
        self.record_state(env, 'initial')

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append(self, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            payload = {
                'sequence': self._sequence,
                'timestamp': self._now(),
                'event': event,
                **data,
            }
            self._sequence += 1
            with self.events_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')

    def _write_replay(self, env) -> None:
        replay = env.export_replay()
        temporary = self.replay_path.with_suffix('.yaml.tmp')
        temporary.write_text(replay, encoding='utf-8')
        temporary.replace(self.replay_path)

    def record_action(self, env, action: int, source: str) -> None:
        labels = env.get_action_labels()
        identities = env.get_action_identities()
        payments = env.get_legal_action_payments()
        refs = env.get_action_refs()
        kind, name, slot = labels[action]
        self._append(
            'action_selected',
            {
                'source': source,
                'player': int(env.acting_player),
                'round': int(env.export_view()['round']),
                'phase': str(env.export_view()['phase']),
                'action': {
                    'index': action,
                    'kind': kind,
                    'name': name,
                    'slot': int(slot),
                    'identity': identities[action].tolist(),
                    'payment': payments[action].tolist(),
                    'refs': refs[action].tolist(),
                },
            },
        )

    def record_state(self, env, reason: str) -> None:
        view = env.export_view()
        self._append(
            'state_advanced',
            {
                'reason': reason,
                'done': bool(env.done),
                'acting_player': int(env.acting_player),
                'view': view,
            },
        )
        self._write_replay(env)

    def record_error(self, message: str) -> None:
        self._append('error', {'message': message})

    def finish(self, env, reason: str) -> None:
        if self._finished:
            return
        self.record_state(env, 'final')
        view = env.export_view()
        self._append(
            'session_finished',
            {
                'reason': reason,
                'done': bool(env.done),
                'winner': int(view.get('winner', -1)),
                'round': int(view.get('round', 0)),
            },
        )
        self._finished = True
