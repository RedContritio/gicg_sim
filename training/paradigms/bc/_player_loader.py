"""Register the explicit, unsupported BC gauntlet loader.

``BCNetwork`` wraps ``ActorCritic`` directly and has no
``select_action(env)`` adapter. BC evaluation currently uses supervised
dataset loss, so loading a BC checkpoint as a matchup player raises a
clear ``NotImplementedError``.
"""

from __future__ import annotations

from training.core.matchup.loaders import PlayerBuilder, register_loader


def _loader_bc(spec: dict) -> PlayerBuilder:
    raise NotImplementedError(
        'BC player loader is not implemented: BCNetwork has no `select_action(env)` adapter for gauntlet evaluation.'
    )


register_loader('bc', _loader_bc)
