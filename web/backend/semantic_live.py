"""Config-driven live service for an independently evaluated semantic model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import tomllib

from tools.experiments.semantic_training.player_loader import FORMAT, load_semantic_agent, register_semantic_loader
from training.core.artifact_io import fingerprint
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from web.backend.live_session import LiveSession, build_opponent_player


ROOT = Path(__file__).resolve().parents[2]
SERVICE_CONFIG = ROOT / 'configs/web/semantic_live.toml'
register_semantic_loader()


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    model_type: str
    cfg_path: Path
    ckpt_path: Path
    report_path: Path


def _resolve_under(root: Path, value: object, directory: str, label: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError(f'{label} must be a non-empty repository-relative path')
    allowed = (root / directory).resolve()
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError(f'{label} must stay under {directory}/') from exc
    return resolved


def load_service_definition(
    service_config: Path | None = None,
    root: Path | None = None,
) -> tuple[ServiceDefinition, object]:
    root = (root or ROOT).resolve()
    path = (service_config or SERVICE_CONFIG).resolve()
    try:
        path.relative_to((root / 'configs').resolve())
    except ValueError as exc:
        raise ValueError('live model service config must stay under configs/') from exc
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    allowed = {'name', 'type', 'cfg', 'ckpt', 'report'}
    if unknown := set(raw) - allowed:
        raise ValueError(f'unknown live model service fields: {sorted(unknown)}')
    if set(raw) != allowed:
        raise ValueError(f'live model service config requires fields: {sorted(allowed)}')
    definition = ServiceDefinition(
        name=str(raw['name']),
        model_type=str(raw['type']),
        cfg_path=_resolve_under(root, raw['cfg'], 'configs', 'cfg'),
        ckpt_path=_resolve_under(root, raw['ckpt'], 'artifacts', 'ckpt'),
        report_path=_resolve_under(root, raw['report'], 'artifacts', 'report'),
    )
    # 09-19: AZ 支持 — live 服务不再限定 D2 时代的 semantic_rl；ExIt/AZ
    # ckpt（player_spec type='az'，argmax 着法）同样可对战。旧 semantic_rl
    # 行为不变。
    if definition.model_type not in ('semantic_rl', 'az'):
        raise ValueError('semantic live service requires type semantic_rl or az')
    return definition, load_cfg(definition.cfg_path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_report(definition: ServiceDefinition, cfg) -> dict:
    if not definition.ckpt_path.is_file():
        raise ValueError('configured checkpoint is not installed')
    if not definition.report_path.is_file():
        raise ValueError('configured evaluation report is not installed')
    report = json.loads(definition.report_path.read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        raise ValueError('configured evaluation report must be a JSON object')
    if report.get('status') != 'complete':
        raise ValueError('configured evaluation report is incomplete')
    if report.get('checkpoint_sha256') != _sha256(definition.ckpt_path):
        raise ValueError('configured checkpoint does not match its evaluation report')
    report_provenance = report.get('provenance')
    source = report_provenance.get('source_observation_sha256') if isinstance(report_provenance, dict) else None
    if source != fingerprint():
        raise ValueError('configured evaluation report is incompatible with current rules and observations')
    if report.get('scenario') != asdict(cfg.scenario):
        raise ValueError('configured evaluation report does not match the training rule config')
    if definition.model_type == 'semantic_rl':
        load_semantic_agent(str(definition.ckpt_path))
    # az: report 校验（sha/指纹/场景）已锁定 ckpt，真正的 builder 加载在
    # build_session 经 matchup loaders 完成并缓存 — 此处不再重复装载。
    return report


def _validate_teams(msg: dict, cfg) -> tuple[list[str], list[str]]:
    scenario = cfg.scenario
    teams = [msg.get('team_0', scenario.team_0), msg.get('team_1', scenario.team_1)]
    if not all(
        isinstance(team, list)
        and len(team) == scenario.team_size
        and len(set(team)) == scenario.team_size
        and all(isinstance(char, str) for char in team)
        for team in teams
    ):
        raise ValueError(f'双方各选择 {scenario.team_size} 名不同角色')
    pool = set(scenario.char_pool or scenario.team_0 + scenario.team_1)
    if not set(teams[0] + teams[1]).issubset(pool):
        raise ValueError('队伍包含训练角色池以外的角色')
    if scenario.disjoint_teams and set(teams[0]) & set(teams[1]):
        raise ValueError('双方角色不能重叠')
    forbidden = ('card_pool', 'decks', 'pool', 'deck_padding', 'data_dir')
    if any(key in msg for key in forbidden):
        raise ValueError('RL 对战使用训练时的固定牌组与规则')
    return teams[0], teams[1]


def build_session(msg: dict, seed: int, human_player: int) -> LiveSession:
    definition, cfg = load_service_definition()
    _validated_report(definition, cfg)
    team_0, team_1 = _validate_teams(msg, cfg)
    player = build_opponent_player(
        {'type': definition.model_type, 'ckpt': str(definition.ckpt_path)},
        seed,
        ckpt_allow_root=ROOT / 'artifacts',
    )
    game_cfg = replace(cfg, scenario=replace(cfg.scenario, team_0=team_0, team_1=team_1))
    env = make_env_factory(game_cfg, None, seed)(0)
    try:
        # semantic agents cache static hook embeddings per game; az argmax
        # players manage their own per-decision setup (same contract as
        # evaluate.py — game_start is optional protocol).
        if hasattr(player, 'game_start'):
            player.game_start(env.static_obs)
        return LiveSession(env, player, human_player)
    except BaseException:
        env.close()
        raise


def build_practice_session(msg: dict, seed: int, human_player: int) -> LiveSession:
    """Explicit random practice opponent using the same configured game rules."""
    _, cfg = load_service_definition()
    team_0, team_1 = _validate_teams(msg, cfg)
    player = build_opponent_player({'type': 'random'}, seed)
    game_cfg = replace(cfg, scenario=replace(cfg.scenario, team_0=team_0, team_1=team_1))
    env = make_env_factory(game_cfg, None, seed)(0)
    return LiveSession(env, player, human_player)


def profile() -> dict:
    definition, cfg = load_service_definition()
    scenario = cfg.scenario
    report = None
    error = None
    try:
        report = _validated_report(definition, cfg)
    except (FileNotFoundError, OSError, ValueError) as exc:
        error = str(exc)
    metrics = {
        key: report[key]
        for key in ('score', 'opponent_depth', 'scenarios', 'layouts')
        if report is not None and key in report
    }
    return {
        'name': definition.name,
        'model_type': definition.model_type,
        'available': error is None,
        'unavailable_reason': error,
        'characters': scenario.char_pool or sorted(set(scenario.team_0 + scenario.team_1)),
        'team_0': scenario.team_0,
        'team_1': scenario.team_1,
        'team_size': scenario.team_size,
        'disjoint_teams': scenario.disjoint_teams,
        'allow_overlap': not scenario.disjoint_teams,
        'max_rounds': scenario.max_rounds,
        'evaluation': metrics,
        'checkpoint_format': FORMAT if definition.model_type == 'semantic_rl' else 'az',
    }
