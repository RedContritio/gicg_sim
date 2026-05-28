"""Lifecycle methods for gicg_env.engine.GicgEngine — construction,
snapshot / restore / clone, per-player hidden-state setters (hand,
deck, dice), and close/cleanup. __init__ lives here because the
canonical construction path is init → _setup_api (from _ApiMixin) →
new_game → optional set_* injections."""

from __future__ import annotations

import ctypes
import json

from gicg_env._constants import DICE_COLOR_COUNT


class _LifecycleMixin:
    """Provides __init__, game creation, snapshot/restore/clone,
    hidden-state setters, and close/context-manager plumbing."""

    def __init__(self, lib_path=None):
        if lib_path is None:
            # Local import to avoid a load-time circular dependency
            # between gicg_env.engine and this mixin module.
            from gicg_env.engine import _find_lib

            lib_path = _find_lib()
        self._lib = ctypes.CDLL(lib_path)
        self._setup_api()
        self._handle = None
        # ADR-0019 §B.2/§B.3c — verify Go↔Python typed obs constants
        # agree (review B2). Catches silent drift if engine bumps
        # K=8/K_mod=4 etc. without Python following.
        self._verify_typed_obs_constants()

    def _verify_typed_obs_constants(self) -> None:
        """Cross-check Python OBS_* mirrors against engine source of truth.

        Round-2 review M2: also verify hand-block constants — typed segment
        slicing offset is derived from `c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
        + OBS_ENEMY_SIZES`, so any of those drifting Go↔Python silently
        misaligns the typed segment reads.
        """
        from gicg_env._constants import (
            OBS_ENEMY_SIZES,
            OBS_HAND_BUCKETS,
            OBS_MAX_CARD_TYPES,
            OBS_MODIFIER_LOG_SLOTS,
            OBS_PREPARE_SKILL_SLOTS,
            OBS_RECENT_DAMAGE_SLOTS,
        )

        # GameGetTypedObsConstants returns 8 ints (Round-2 M2 widened from 5)
        out = (ctypes.c_int * 8)()
        self._lib.GameGetTypedObsConstants(out)
        engine_recent_events = int(out[0])
        engine_recent_fields = int(out[1])
        engine_prepare_slots = int(out[2])
        engine_kmod = int(out[3])
        engine_mod_fields = int(out[4])
        engine_max_card_types = int(out[5])
        engine_hand_buckets = int(out[6])
        engine_enemy_sizes = int(out[7])

        py_recent_slots = OBS_RECENT_DAMAGE_SLOTS
        py_prepare_slots = OBS_PREPARE_SKILL_SLOTS
        py_modifier_slots = OBS_MODIFIER_LOG_SLOTS

        engine_recent_slots = engine_recent_events * engine_recent_fields
        engine_modifier_slots = engine_recent_events * engine_kmod * engine_mod_fields

        rebuild_msg = (
            "dylib likely stale; rebuild via 'go build -buildmode=c-shared "
            "-o gicg_env/libgicg.dylib ./gicg_engine/capi/'"
        )

        if engine_recent_slots != py_recent_slots:
            raise RuntimeError(
                f'OBS_RECENT_DAMAGE_SLOTS mismatch: engine={engine_recent_slots} '
                f'(events={engine_recent_events} × fields={engine_recent_fields}), '
                f'Python={py_recent_slots}. {rebuild_msg}'
            )
        if engine_prepare_slots != py_prepare_slots:
            raise RuntimeError(
                f'OBS_PREPARE_SKILL_SLOTS mismatch: engine={engine_prepare_slots}, '
                f'Python={py_prepare_slots}. {rebuild_msg}'
            )
        if engine_modifier_slots != py_modifier_slots:
            raise RuntimeError(
                f'OBS_MODIFIER_LOG_SLOTS mismatch: engine={engine_modifier_slots} '
                f'(K={engine_recent_events} × K_mod={engine_kmod} × fields={engine_mod_fields}), '
                f'Python={py_modifier_slots}. {rebuild_msg}'
            )
        # Round-2 M2: hand-block constants gate typed segment offset.
        if engine_max_card_types != OBS_MAX_CARD_TYPES:
            raise RuntimeError(
                f'OBS_MAX_CARD_TYPES mismatch: engine={engine_max_card_types}, '
                f'Python={OBS_MAX_CARD_TYPES}. {rebuild_msg}'
            )
        # Round-3 review S8: compare against Python source-of-truth
        # (training.core.obs_constants) rather than hard-coded 4/2.
        if engine_hand_buckets != OBS_HAND_BUCKETS:
            raise RuntimeError(
                f'OBS_HAND_BUCKETS mismatch: engine={engine_hand_buckets}, Python={OBS_HAND_BUCKETS}. {rebuild_msg}'
            )
        if engine_enemy_sizes != OBS_ENEMY_SIZES:
            raise RuntimeError(
                f'OBS_ENEMY_SIZES mismatch: engine={engine_enemy_sizes}, Python={OBS_ENEMY_SIZES}. {rebuild_msg}'
            )

    def new_game(
        self,
        players,
        seed=42,
        data_dir=None,
        card_pool=None,
        obs_config=None,
        max_rounds=0,
        fix_dice=None,
        deck_padding=None,
        pool=None,
    ):
        """Create a new game.

        Args:
            players: list of 2 player configs, each a list of character names
                e.g. [["赤蝶", "墨客", "猫咪"], ["刻师傅", "天星", "赤蝶"]]
            seed: random seed
            data_dir: path to data/ directory (auto-detected if None)
            card_pool: list of card names to load. None = all cards.
                Empty list = filler-only deck.
            obs_config: optional dict mirroring Go ObsConfigJSON schema
                (keys: include_char_skill_refs, shuffle_counters,
                shuffle_hooks, shuffle_cards, shuffle_skill_slots). When
                None, Go side applies the legacy all-on default. Callers
                constructing a ``training.config.ObsConfig`` should pass
                ``obs_config=cfg.obs.to_engine_json()``.
            max_rounds: hard cap on episode length. 0 = unbounded (legacy).
                When > 0, the game auto-terminates with winner=2 (draw)
                after the round-end phase of the capped round. Used by
                curriculum Stage 0 to bound episodes deterministically.
            fix_dice: length-DICE_COLOR_COUNT int list. When provided,
                overrides the random per-round dice roll to produce
                exactly these per-color counts. None = random roll.
                Curriculum Stage 0 uses [2,2,2,2,0,0,0,0] or similar to
                eliminate dice stochasticity.
            deck_padding: optional dict {"card": str, "target_size": int}
                or None. When set, BuildDeck pads short decks up to
                target_size using the named card; the padding card is
                auto-included in the loaded ruleset. None = deck length
                equals the eligible-card count (no padding). See
                ADR-0011 — replaces the previous engine-level "碌碌无为"
                hardcode.
            pool: pool ID(s) under data/pools/ to load chars + cards
                from. Accepts str (single pool), list[str] (sibling
                pools, union semantics), or None (engine default
                ["v_legacy"]). v_legacy is the placeholder pool
                ADR-0011 created from the pre-existing prod cards
                and chars; pass "test_basic" or ["v_legacy",
                "test_basic"] to include synthetic 测试角色 / 测试卡
                fixtures.
        """
        config = {
            'seed': seed,
            'players': [{'chars': [{'name': n} for n in p]} for p in players],
        }
        if data_dir:
            config['data_dir'] = data_dir
        if card_pool is not None:
            config['card_pool'] = list(card_pool)
        if obs_config is not None:
            config['obs'] = dict(obs_config)
        if max_rounds:
            config['max_rounds'] = int(max_rounds)
        if fix_dice is not None:
            fd = list(fix_dice)
            if len(fd) != DICE_COLOR_COUNT:
                raise ValueError(f'fix_dice must be length {DICE_COLOR_COUNT}, got {len(fd)}')
            config['fix_dice'] = [int(x) for x in fd]
        if deck_padding is not None:
            if not isinstance(deck_padding, dict):
                raise TypeError(f'deck_padding must be dict or None, got {type(deck_padding).__name__}')
            if 'card' not in deck_padding or 'target_size' not in deck_padding:
                raise ValueError(f'deck_padding requires "card" and "target_size" keys, got {sorted(deck_padding)}')
            config['deck_padding'] = {
                'card': str(deck_padding['card']),
                'target_size': int(deck_padding['target_size']),
            }
        if pool is not None:
            if isinstance(pool, str):
                pools = [pool]
            else:
                pools = [str(p) for p in pool]
            config['pools'] = pools

        config_json = json.dumps(config).encode('utf-8')
        handle = self._lib.GameNew(config_json)
        if handle < 0:
            raise RuntimeError('Failed to create game')
        self._handle = handle
        # Round-6 S-1: per-game DSL declare_reaction count vs encoder
        # vocab capacity. Catches DSL adding reactions beyond the trained
        # network's REACTION_VOCAB at game init (远比 forward path raise
        # 提前 + 错误位置更准)。
        self._verify_reaction_count_within_vocab()
        return self

    def _verify_reaction_count_within_vocab(self) -> None:
        """Round-6 S-1: assert engine ReactionCount ≤ REACTION_VOCAB-3.

        REACTION_VOCAB - 3 = max real reaction kind id (the encoder
        +2 offset reserves slot 0 for padding, slot 1 for "real -1" /
        unused, leaving idx 2..VOCAB-1 for real values; -3 reserves 1
        spare). Engine count is per-game (DSL declare_reaction at load),
        not static, so this lives in new_game not __init__.
        """
        from training.core.network.typed_damage import REACTION_VOCAB

        count = int(self._lib.GameGetReactionCount(self._handle))
        max_allowed = REACTION_VOCAB - 3
        if count > max_allowed:
            raise RuntimeError(
                f'Engine declared {count} reactions, exceeds encoder '
                f'REACTION_VOCAB-3={max_allowed} (vocab={REACTION_VOCAB}). '
                'Either DSL stripped a reaction or training/framework/network/'
                'typed_damage.py REACTION_VOCAB needs raising (BREAKING ckpt).'
            )

    def reset_dynamic(self, seed):
        """Restart the dynamic state of the current game without re-loading
        DSL files. The team and card pool are preserved."""
        self._check()
        self._lib.GameReset(self._handle, seed)

    def reset_dynamic_with_seeds(self, dice_seed, deck_seed_p0, deck_seed_p1):
        """Review D.5 (2026-05-14): 3-axis seed reset for daemon eval
        'team 同 deck 不同' ablation. dice_seed controls Rng (dice rolls
        + DSL randomness + obs perm); deck_seed_p0 / deck_seed_p1
        independently seed per-player deck Fisher-Yates shuffle."""
        self._check()
        self._lib.GameResetSeeds(self._handle, dice_seed, deck_seed_p0, deck_seed_p1)

    def clone(self):
        """Return a new GicgEngine wrapping a clone of this game.

        The clone shares the static Ruleset (DSL definitions) but owns its
        own dynamic state — stepping the clone does not affect this engine.
        """
        self._check()
        new_handle = self._lib.GameClone(self._handle)
        if new_handle < 0:
            raise RuntimeError('Failed to clone game')
        from gicg_env.engine import GicgEngine

        twin = GicgEngine.__new__(GicgEngine)
        twin._lib = self._lib
        twin._handle = new_handle
        return twin

    def snapshot(self):
        """Capture the current dynamic state into a cheap handle. Use
        restore(snap_id) to roll back, snapshot_free(snap_id) to release.
        Snapshots are valid only at quiescent points (between Step calls).
        """
        self._check()
        sid = self._lib.GameSnapshot(self._handle)
        if sid < 0:
            raise RuntimeError('Failed to snapshot game')
        return sid

    def restore(self, snap_id):
        """Restore dynamic state from a snapshot taken via snapshot()."""
        self._check()
        if self._lib.GameRestore(self._handle, snap_id) < 0:
            raise RuntimeError(f'Failed to restore snapshot {snap_id}')

    def snapshot_free(self, snap_id):
        """Release a snapshot handle."""
        self._lib.GameSnapshotFree(snap_id)

    def log_suspend(self):
        """Detach the event log so subsequent engine events aren't
        recorded. Use around MCTS rollouts (or any speculative forward
        simulation): the inner events don't belong in the replay, and
        skipping the Log.Append + string-formatting overhead per step
        is a meaningful speedup. Idempotent: calling while already
        suspended raises."""
        self._check()
        rc = self._lib.GameLogSuspend(self._handle)
        if rc < 0:
            raise RuntimeError(f'GameLogSuspend failed (rc={rc}); is the log already suspended?')

    def log_resume(self):
        """Re-attach the event log suspended by ``log_suspend``.
        Events written while suspended are permanently lost — that's
        the point of this API. Raises if no log was suspended."""
        self._check()
        rc = self._lib.GameLogResume(self._handle)
        if rc < 0:
            raise RuntimeError(f'GameLogResume failed (rc={rc}); was log_suspend() called first?')

    def set_player_hand(self, player, refs):
        """Overwrite a player's hand with the given card refs. Each ref
        becomes a new CardInst with DrawnAtRound stamped to the current
        round.

        Intended for IS-MCTS determinization: the sampler generates a
        hypothetical opponent hand and injects it into a cloned engine
        before rolling forward. Caller is responsible for ref validity.

        Args:
            player: 0 or 1
            refs: list/sequence of int card refs. Empty list clears hand.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_hand: player must be 0 or 1, got {player}')
        n = len(refs)
        arr = (ctypes.c_int * n)(*refs) if n > 0 else (ctypes.c_int * 0)()
        rc = self._lib.GameSetPlayerHand(self._handle, int(player), arr, n)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerHand failed for player {player}')

    def set_player_deck(self, player, refs):
        """Overwrite a player's deck with the given card refs. ``refs[0]``
        is the top of the deck (next to be drawn). Each ref becomes a
        new CardInst with DrawnAtRound=0.

        Intended for IS-MCTS determinization.

        Args:
            player: 0 or 1
            refs: list/sequence of int card refs. Empty list clears deck.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_deck: player must be 0 or 1, got {player}')
        n = len(refs)
        arr = (ctypes.c_int * n)(*refs) if n > 0 else (ctypes.c_int * 0)()
        rc = self._lib.GameSetPlayerDeck(self._handle, int(player), arr, n)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerDeck failed for player {player}')

    def set_player_dice(self, player, counts):
        """Overwrite a player's dice pool with exact per-color counts.

        ``counts`` must be an 8-length sequence indexed by dice color
        (fire=0, ice=1, water=2, electro=3, geo=4, anemo=5, dendro=6,
        omni=7). Negative values are clamped to zero on the Go side.
        Intended for IS-MCTS determinization — the sampler draws a
        multinomial dice distribution for the opponent and injects it
        into the cloned engine before rolling forward.

        Args:
            player: 0 or 1
            counts: sequence of 8 ints. Longer/shorter inputs raise.
        """
        self._check()
        if player not in (0, 1):
            raise ValueError(f'set_player_dice: player must be 0 or 1, got {player}')
        if len(counts) != DICE_COLOR_COUNT:
            raise ValueError(f'set_player_dice expects {DICE_COLOR_COUNT} counts, got {len(counts)}')
        ints = [int(x) for x in counts]
        for i, v in enumerate(ints):
            if v < 0:
                raise ValueError(f'set_player_dice: counts[{i}]={v} is negative')
        arr = (ctypes.c_int * DICE_COLOR_COUNT)(*ints)
        rc = self._lib.GameSetPlayerDice(self._handle, int(player), arr)
        if rc < 0:
            raise RuntimeError(f'GameSetPlayerDice failed for player {player}')

    def close(self):
        """Free the game resources."""
        if self._handle is not None:
            self._lib.GameFree(self._handle)
            self._handle = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check(self):
        if self._handle is None:
            raise RuntimeError('No active game')
