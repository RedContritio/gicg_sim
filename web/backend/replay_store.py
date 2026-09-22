"""Index of replay files under artifacts/. Walked once at startup (or
refreshed on demand) to populate the /api/replays list endpoint.

Replay YAMLs live under a top-level experiment tag:
    artifacts/web_live/sessions/<session_id>/web/replays/<scenario>.yaml
    artifacts/<tag>/runs/<run_id>/<curriculum_parts>/<stage>/replays/<scenario>.yaml

The store records only metadata (path, session, stage, scenario) — the
actual YAML is parsed lazily when the frontend requests a specific
replay's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ReplayEntry:
    """One indexed replay YAML file."""

    rel_path: str  # stable id relative to artifacts_root (URL-safe)
    abs_path: str  # absolute filesystem path
    session_id: str  # parent session id, or "go_tests" for engine replays
    curriculum: List[str]  # nested curriculum names, may be empty
    stage: Optional[str]  # leaf stage name, or None for go_tests
    scenario: str  # filename stem
    size_bytes: int


def _classify(rel: Path) -> tuple[str, List[str], Optional[str], str]:
    """Parse artifacts/<...>/replays/<scenario>.yaml into (session, curriculum, stage, scenario).

    Tagged Web sessions and training runs are normalized before the
    session/curriculum/stage fields are derived.
    """
    parts = rel.parts
    scenario = rel.stem
    if len(parts) >= 3 and parts[:2] == ('web_live', 'sessions'):
        parts = parts[2:]
    elif len(parts) >= 3 and parts[1] == 'runs':
        parts = parts[2:]
    if len(parts) < 4 or parts[-2] != 'replays':
        return 'unknown', [], None, scenario
    session_id = parts[0]
    stage = parts[-3]
    curriculum = list(parts[1:-3])
    return session_id, curriculum, stage, scenario


class ReplayStore:
    """Lazy index of replay YAMLs. Call refresh() to rescan the tree."""

    def __init__(self, artifacts_root: Path):
        self.artifacts_root = artifacts_root
        self._entries: List[ReplayEntry] = []
        # rel_path → entry index for O(1) find() lookups. Several
        # thousand replays per long-running training session make the
        # earlier linear scan visible on /api/replay hits.
        self._index: Dict[str, ReplayEntry] = {}

    def refresh(self) -> None:
        self._entries.clear()
        self._index.clear()
        if not self.artifacts_root.exists():
            return
        for path in self.artifacts_root.rglob('*.yaml'):
            # Replay YAMLs live in either a per-session "replays/" dir
            # OR the go_tests fixture dir whose parent ends in "_replays".
            parts = path.parts
            if 'replays' not in parts and not any(p.endswith('_replays') for p in parts):
                continue
            rel = path.relative_to(self.artifacts_root)
            session_id, curriculum, stage, scenario = _classify(rel)
            entry = ReplayEntry(
                rel_path=str(rel),
                abs_path=str(path),
                session_id=session_id,
                curriculum=curriculum,
                stage=stage,
                scenario=scenario,
                size_bytes=path.stat().st_size,
            )
            self._entries.append(entry)
            self._index[entry.rel_path] = entry
        self._entries.sort(key=lambda e: (e.session_id, tuple(e.curriculum), e.stage or '', e.scenario))

    def list(self) -> List[ReplayEntry]:
        return list(self._entries)

    def find(self, rel_path: str) -> Optional[ReplayEntry]:
        return self._index.get(rel_path)
