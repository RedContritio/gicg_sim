"""EpisodeRunner — actor + eval shared episode driver.

Spec: design/episode-runner.md.

Runner is paradigm-agnostic: its decisions come from ``EpisodeSpec`` and the
injected ``EpisodePolicy``. It drives ordinary single-sided actor and eval
episodes. AZ's two-sided self-play collector uses its dedicated lifecycle
adapter around ``play_self_game``.
"""

from __future__ import annotations

from typing import Any

from training.core.perf import trace
from training.core.protocols import (
    EpisodePolicy,
    EpisodeRecord,
    EpisodeSpec,
    NetworkProvider,
    Transition,
)


class EpisodeRunner:
    """Drives one full episode through a paradigm-agnostic loop.

    Args:
        env_factory: callable ``(scenario_seed) → env``. The environment
            must expose step, termination/player state, and either get_obs
            or _get_obs.
        opponent_registry: ``OpponentRegistry`` with ``get(opp_id) → Player``.
    """

    def __init__(self, env_factory: Any, opponent_registry: Any) -> None:
        self.env_factory = env_factory
        self.opponent_registry = opponent_registry

    def run(
        self,
        spec: EpisodeSpec,
        policy: EpisodePolicy,
        provider: NetworkProvider,
        *,
        our_player: int = 0,
    ) -> EpisodeRecord:
        """Run one episode end-to-end.

        Args:
            spec: scenario_seed / opponent_id / deterministic / etc.
            policy: paradigm-specific act logic.
            provider: forward interface.
            our_player: which player slot is "us" (default 0).
        Returns:
            EpisodeRecord — transitions (only OUR actions captured) +
            final reward + length + winner.
        """
        env = self.env_factory(spec.scenario_seed)
        opp = self.opponent_registry.get(spec.opponent_id, seed=spec.scenario_seed)
        policy.reset()

        transitions: list = []
        # The env is assumed reset by env_factory; if not, callers call
        # env.reset(seed=spec.scenario_seed) inside their env_factory.
        steps = 0
        max_steps = 600  # Defensive cap for malformed/non-terminating episodes.
        winner = -1
        while steps < max_steps:
            if getattr(env, 'done', False):
                winner = self._winner(env)
                break
            cur = getattr(env, 'current_player', 0)
            if cur == our_player:
                with trace.span('episode_runner.get_obs'):
                    obs = self._get_obs(env)
                with trace.span('episode_runner.get_legal_mask'):
                    mask = self._get_legal_mask(env)
                # Some providers need the environment to build their
                # paradigm-specific observation before ``policy.act``.
                if hasattr(provider, 'observe_env'):
                    with trace.span('episode_runner.observe_env'):
                        provider.observe_env(env)
                with trace.span('episode_runner.policy_act'):
                    action, meta = policy.act(obs, mask, provider)
                with trace.span('episode_runner.env_step_our'):
                    step_out = env.step(action)
                reward = self._reward_from_step(step_out)
                done = bool(getattr(env, 'done', False))
                with trace.span('episode_runner.transition_build'):
                    transitions.append(
                        Transition(
                            obs=obs,
                            action=int(action),
                            legal_mask=mask,
                            reward=float(reward),
                            done=done,
                            payload=meta,
                        )
                    )
            else:
                with trace.span('episode_runner.opp_select_action'):
                    opp_action = opp.select_action(env)
                with trace.span('episode_runner.env_step_opp'):
                    env.step(int(opp_action))
            steps += 1
        else:
            winner = self._winner(env)

        final_reward = transitions[-1].reward if transitions else 0.0
        return EpisodeRecord(
            transitions=transitions,
            final_reward=float(final_reward),
            length=len(transitions),
            winner=winner,
            opponent_id=spec.opponent_id,
            scenario_seed=spec.scenario_seed,
        )

    @staticmethod
    def _get_obs(env: Any) -> Any:
        if hasattr(env, 'get_obs'):
            return env.get_obs()
        if hasattr(env, '_get_obs'):
            return env._get_obs()
        return None

    @staticmethod
    def _get_legal_mask(env: Any) -> Any:
        # Prefer get_legal_actions kinds list (no max_actions arg
        # needed) — GicgEnv.get_legal_mask requires a max_actions
        # parameter we don't carry through this layer.
        if hasattr(env, 'get_legal_actions'):
            kinds, _ = env.get_legal_actions()
            return kinds
        if hasattr(env, 'get_legal_mask'):
            return env.get_legal_mask()
        return None

    @staticmethod
    def _reward_from_step(step_out: Any) -> float:
        # GicgEnv.step returns various shapes; default to scalar attr.
        if isinstance(step_out, tuple) and len(step_out) >= 2:
            return float(step_out[1])
        if isinstance(step_out, dict) and 'reward' in step_out:
            return float(step_out['reward'])
        return 0.0

    @staticmethod
    def _winner(env: Any) -> int:
        eng = getattr(env, '_engine', None)
        if eng is not None and hasattr(eng, 'winner'):
            return int(eng.winner)
        return -1
