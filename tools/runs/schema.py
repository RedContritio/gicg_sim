"""Run metadata TOML schema (per spec T5).

Dataclass-based schema + strict validator + minimal hand-rolled TOML
emitter (depend only on stdlib ``tomllib`` for read).

Layout: top-level scalars (incl. ``cfg_run_label`` — snapshot of
``cfg.meta.run_label`` at register time — and ``artifacts_dir`` —
repo-relative path to the artifacts dir, backfilled by ``complete``
or train driver after the run finishes) + nested ``[summary]`` /
``[notes]``; ``[result.gauntlet]`` and ``[result.training]`` optional.
"""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

TYPES: frozenset[str] = frozenset({'r', 's'})
PARADIGMS: frozenset[str] = frozenset({'az', 'bc', 'cfr', 'dmc', 'ppo'})
STATUSES: frozenset[str] = frozenset({'pending', 'running', 'done', 'failed', 'killed'})

RUN_ID_RE = re.compile(r'^([rs])(\d{3})$')
SHA256_RE = re.compile(r'^sha256:[0-9a-f]{64}$')


@dataclass
class Summary:
    wall: str = ''
    description: str = ''


@dataclass
class GauntletResult:
    """``n`` = sample size; ``metrics`` = {opponent_name: win_rate}."""

    n: int = 0
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class TrainingResult:
    final_loss: float = 0.0
    n_games_completed: int = 0


@dataclass
class Result:
    gauntlet: GauntletResult | None = None
    training: TrainingResult | None = None


@dataclass
class Notes:
    text: str = ''


@dataclass
class RunMetadata:
    run_id: str
    label: str
    type: str
    timestamp: str
    paradigm: str
    cfg_file: str
    cfg_checksum: str
    cfg_run_label: str
    git_commit: str
    host: str
    status: str
    artifacts_dir: str = ''
    summary: Summary = field(default_factory=Summary)
    result: Result = field(default_factory=Result)
    notes: Notes = field(default_factory=Notes)


def validate(meta: RunMetadata) -> None:
    """Raise ValueError on any schema violation. Strict — no silent fix."""
    m = RUN_ID_RE.match(meta.run_id)
    if not m:
        raise ValueError(f'run_id {meta.run_id!r} must match <r|s><NNN> (3 digits)')
    if meta.type not in TYPES:
        raise ValueError(f'type {meta.type!r} must be one of {sorted(TYPES)}')
    if m.group(1) != meta.type:
        raise ValueError(f'run_id prefix {m.group(1)!r} disagrees with type {meta.type!r}')
    if meta.paradigm not in PARADIGMS:
        raise ValueError(f'paradigm {meta.paradigm!r} must be one of {sorted(PARADIGMS)}')
    if meta.status not in STATUSES:
        raise ValueError(f'status {meta.status!r} must be one of {sorted(STATUSES)}')
    if not meta.label:
        raise ValueError('label is required (non-empty)')
    if not meta.timestamp:
        raise ValueError('timestamp is required (non-empty iso8601)')
    if not meta.cfg_file:
        raise ValueError('cfg_file is required (non-empty)')
    if not SHA256_RE.match(meta.cfg_checksum):
        raise ValueError(f'cfg_checksum {meta.cfg_checksum!r} must match sha256:<64 hex chars>')
    if not meta.cfg_run_label:
        raise ValueError('cfg_run_label is required (non-empty; cfg.meta.run_label snapshot at register time)')
    if not meta.git_commit:
        raise ValueError("git_commit is required (use 'unknown' if unavailable)")
    if not meta.host:
        raise ValueError('host is required (non-empty)')


def _to_plain_dict(meta: RunMetadata) -> dict[str, Any]:
    """Convert to dict suitable for TOML dump. ``result.*`` sub-tables
    only emitted when set (per spec ``# optional``)."""
    d: dict[str, Any] = {
        'run_id': meta.run_id,
        'label': meta.label,
        'type': meta.type,
        'timestamp': meta.timestamp,
        'paradigm': meta.paradigm,
        'cfg_file': meta.cfg_file,
        'cfg_checksum': meta.cfg_checksum,
        'cfg_run_label': meta.cfg_run_label,
        'git_commit': meta.git_commit,
        'host': meta.host,
        'status': meta.status,
        'artifacts_dir': meta.artifacts_dir,
        'summary': asdict(meta.summary),
        'notes': asdict(meta.notes),
    }
    result_block: dict[str, Any] = {}
    if meta.result.gauntlet is not None:
        g = meta.result.gauntlet
        gd: dict[str, Any] = {'n': g.n}
        gd.update(g.metrics)  # arbitrary metric_name = float pairs
        result_block['gauntlet'] = gd
    if meta.result.training is not None:
        result_block['training'] = asdict(meta.result.training)
    if result_block:
        d['result'] = result_block
    return d


def from_dict(d: dict[str, Any]) -> RunMetadata:
    """Construct RunMetadata from a parsed TOML dict. Strict."""
    required = (
        'run_id',
        'label',
        'type',
        'timestamp',
        'paradigm',
        'cfg_file',
        'cfg_checksum',
        'cfg_run_label',
        'git_commit',
        'host',
        'status',
    )
    missing = [k for k in required if k not in d]
    if missing:
        raise ValueError(f'missing required keys: {missing}')
    summary_d = d.get('summary') or {}
    notes_d = d.get('notes') or {}
    result_d = d.get('result') or {}
    g_d = result_d.get('gauntlet')
    t_d = result_d.get('training')

    gauntlet: GauntletResult | None = None
    if g_d is not None:
        gauntlet = GauntletResult(
            n=int(g_d.get('n', 0)),
            metrics={k: float(v) for k, v in g_d.items() if k != 'n'},
        )
    training: TrainingResult | None = None
    if t_d is not None:
        training = TrainingResult(
            final_loss=float(t_d.get('final_loss', 0.0)),
            n_games_completed=int(t_d.get('n_games_completed', 0)),
        )

    meta = RunMetadata(
        run_id=str(d['run_id']),
        label=str(d['label']),
        type=str(d['type']),
        timestamp=str(d['timestamp']),
        paradigm=str(d['paradigm']),
        cfg_file=str(d['cfg_file']),
        cfg_checksum=str(d['cfg_checksum']),
        cfg_run_label=str(d['cfg_run_label']),
        git_commit=str(d['git_commit']),
        host=str(d['host']),
        status=str(d['status']),
        artifacts_dir=str(d.get('artifacts_dir', '')),
        summary=Summary(
            wall=str(summary_d.get('wall', '')),
            description=str(summary_d.get('description', '')),
        ),
        result=Result(gauntlet=gauntlet, training=training),
        notes=Notes(text=str(notes_d.get('text', ''))),
    )
    validate(meta)
    return meta


# TOML emitter — supports only the shapes produced by `_to_plain_dict`
# (scalars + nested dict tables). No arrays-of-tables, no inline tables.


def _format_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = repr(v)
        if '.' not in s and 'e' not in s and 'n' not in s and 'i' not in s:
            s += '.0'  # force decimal so re-parse gives float
        return s
    if isinstance(v, str):
        escaped = (
            v.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        )
        return f'"{escaped}"'
    raise TypeError(f'unsupported TOML scalar type: {type(v).__name__}')


def _dump_table(d: dict[str, Any], prefix: str, lines: list[str]) -> None:
    """Emit one table. Scalars first, then nested tables (TOML rule)."""
    scalars = {k: v for k, v in d.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in d.items() if isinstance(v, dict)}
    if prefix:
        lines.append(f'[{prefix}]')
    for k, v in scalars.items():
        lines.append(f'{k} = {_format_scalar(v)}')
    for k, v in tables.items():
        if scalars or prefix:
            lines.append('')
        sub_prefix = f'{prefix}.{k}' if prefix else k
        _dump_table(v, sub_prefix, lines)


def dumps(meta: RunMetadata) -> str:
    """Serialize RunMetadata to a TOML string."""
    validate(meta)
    lines: list[str] = []
    _dump_table(_to_plain_dict(meta), '', lines)
    return '\n'.join(lines) + '\n'


def loads(text: str) -> RunMetadata:
    return from_dict(tomllib.loads(text))


def load_file(path: Path) -> RunMetadata:
    """Load + validate. Also enforces M7 filename invariant:
    `path.stem` MUST equal `meta.run_id` (a hand-rename or copy-paste
    mislabel is corruption, not a legitimate query miss)."""
    meta = loads(path.read_text(encoding='utf-8'))
    if meta.run_id != path.stem:
        raise ValueError(
            f'metadata at {path} has run_id={meta.run_id!r} != filename stem {path.stem!r} (file mislabeled)'
        )
    return meta


def save_file(meta: RunMetadata, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(meta), encoding='utf-8')


DEFAULT_RUNS_DIR = Path('artifacts/runs')


def runs_dir(root: Path | None = None) -> Path:
    """Canonical runs dir, optionally rooted under ``root`` (for tests)."""
    return DEFAULT_RUNS_DIR if root is None else root / DEFAULT_RUNS_DIR


def run_path(run_id: str, root: Path | None = None) -> Path:
    if not RUN_ID_RE.match(run_id):
        raise ValueError(f'run_id {run_id!r} must match <r|s><NNN>')
    return runs_dir(root) / f'{run_id}.toml'
