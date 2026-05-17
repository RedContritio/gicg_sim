"""ctypes prototype setup for gicg_env.engine.GicgEngine.

Split out as a mixin so gicg_env/engine.py stays under the 500-line
cap — _setup_api is pure boilerplate declaring argtypes / restype
for every C function libgicg.dylib exports, and dominates the line
count of the engine wrapper."""

from __future__ import annotations

import ctypes


class _ApiMixin:
    """Provides _setup_api(self). Expects self._lib to already be a
    loaded ctypes.CDLL on libgicg.dylib."""

    def _setup_api(self):
        lib = self._lib

        lib.DSLPreload.argtypes = [ctypes.c_char_p]
        lib.DSLPreload.restype = ctypes.c_int

        lib.GameNew.argtypes = [ctypes.c_char_p]
        lib.GameNew.restype = ctypes.c_int

        lib.GameFree.argtypes = [ctypes.c_int]
        lib.GameFree.restype = None

        lib.GameReset.argtypes = [ctypes.c_int, ctypes.c_long]
        lib.GameReset.restype = None

        # review D.5: 3-axis seed reset (dice / deck_p0 / deck_p1)
        lib.GameResetSeeds.argtypes = [ctypes.c_int, ctypes.c_long, ctypes.c_long, ctypes.c_long]
        lib.GameResetSeeds.restype = None

        lib.GameClone.argtypes = [ctypes.c_int]
        lib.GameClone.restype = ctypes.c_int

        lib.GameSnapshot.argtypes = [ctypes.c_int]
        lib.GameSnapshot.restype = ctypes.c_int

        lib.GameRestore.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameRestore.restype = ctypes.c_int

        lib.GameSnapshotFree.argtypes = [ctypes.c_int]
        lib.GameSnapshotFree.restype = None

        lib.GameLogSuspend.argtypes = [ctypes.c_int]
        lib.GameLogSuspend.restype = ctypes.c_int

        lib.GameLogResume.argtypes = [ctypes.c_int]
        lib.GameLogResume.restype = ctypes.c_int

        lib.GameGetActingPlayer.argtypes = [ctypes.c_int]
        lib.GameGetActingPlayer.restype = ctypes.c_int

        lib.GameHasPending.argtypes = [ctypes.c_int]
        lib.GameHasPending.restype = ctypes.c_int

        lib.GameSetPlayerHand.argtypes = [
            ctypes.c_int,  # game id
            ctypes.c_int,  # player
            ctypes.POINTER(ctypes.c_int),  # refs
            ctypes.c_int,  # n
        ]
        lib.GameSetPlayerHand.restype = ctypes.c_int

        lib.GameSetPlayerDeck.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        lib.GameSetPlayerDeck.restype = ctypes.c_int

        lib.GameSetPlayerDice.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameSetPlayerDice.restype = ctypes.c_int

        lib.GameStep.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameStep.restype = ctypes.c_int

        lib.GameStepTarget.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameStepTarget.restype = ctypes.c_int

        lib.GameRandomRollout.argtypes = [
            ctypes.c_int,  # handle
            ctypes.c_ulonglong,  # seed
            ctypes.c_int,  # max_steps
            ctypes.POINTER(ctypes.c_int),  # n_steps_out
        ]
        lib.GameRandomRollout.restype = ctypes.c_int

        lib.GameGetLegalActionCount.argtypes = [ctypes.c_int]
        lib.GameGetLegalActionCount.restype = ctypes.c_int

        lib.GameGetLegalActions.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetLegalActions.restype = None

        lib.GameGetActionRefs.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetActionRefs.restype = None

        lib.GameGetActionIdentities.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetActionIdentities.restype = None

        lib.GameGetLegalActionPayments.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetLegalActionPayments.restype = None

        lib.GameGetDiceColorCount.argtypes = []
        lib.GameGetDiceColorCount.restype = ctypes.c_int

        lib.GameIsForcedSwitchPending.argtypes = [ctypes.c_int]
        lib.GameIsForcedSwitchPending.restype = ctypes.c_int

        lib.GameGetCounterCount.argtypes = [ctypes.c_int]
        lib.GameGetCounterCount.restype = ctypes.c_int

        lib.GameGetCounters.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_int,
        ]
        lib.GameGetCounters.restype = None

        lib.GameGetPhase.argtypes = [ctypes.c_int]
        lib.GameGetPhase.restype = ctypes.c_int

        lib.GameGetWinner.argtypes = [ctypes.c_int]
        lib.GameGetWinner.restype = ctypes.c_int

        lib.GameGetTurn.argtypes = [ctypes.c_int]
        lib.GameGetTurn.restype = ctypes.c_int

        lib.GameGetActiveChar.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameGetActiveChar.restype = ctypes.c_int

        lib.GameGetHandCount.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameGetHandCount.restype = ctypes.c_int

        lib.GameGetDeckCount.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameGetDeckCount.restype = ctypes.c_int

        lib.GameGetDiscardCount.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameGetDiscardCount.restype = ctypes.c_int

        lib.GameGetDiceTotal.argtypes = [ctypes.c_int, ctypes.c_int]
        lib.GameGetDiceTotal.restype = ctypes.c_int

        lib.GameGetDiscardRefs.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDiscardRefs.restype = None

        lib.GameGetHandRefs.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetHandRefs.restype = None

        lib.GameGetDeckRefs.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDeckRefs.restype = None

        lib.GameGetDicePaid.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDicePaid.restype = None

        lib.GameGetDiceCounts.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDiceCounts.restype = None

        lib.GameGetDiceTunedOut.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDiceTunedOut.restype = None

        lib.GameGetDiceTunedIn.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDiceTunedIn.restype = None

        lib.GameGetRewardEvents.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetRewardEvents.restype = None

        lib.GameResetReward.argtypes = [ctypes.c_int]
        lib.GameResetReward.restype = None

        lib.GameGetStaticObsSize.argtypes = []
        lib.GameGetStaticObsSize.restype = ctypes.c_int

        lib.GameGetDynamicObsSize.argtypes = []
        lib.GameGetDynamicObsSize.restype = ctypes.c_int

        # ADR-0019 §B.2/§B.3c — typed obs constants (review B2 sync)
        lib.GameGetTypedObsConstants.argtypes = [ctypes.POINTER(ctypes.c_int)]
        lib.GameGetTypedObsConstants.restype = None

        # Round-6 S-1: per-game reaction count (DSL declare_reaction 注册数)
        lib.GameGetReactionCount.argtypes = [ctypes.c_int]
        lib.GameGetReactionCount.restype = ctypes.c_int

        lib.GameGetStaticObs.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        lib.GameGetStaticObs.restype = None

        lib.GameGetDynamicObs.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.GameGetDynamicObs.restype = None

        lib.GameGetCurrentRound.argtypes = [ctypes.c_int]
        lib.GameGetCurrentRound.restype = ctypes.c_int

        lib.GameGetCardNames.argtypes = [ctypes.c_int]
        lib.GameGetCardNames.restype = ctypes.c_void_p

        lib.GameGetActiveHookLabels.argtypes = [ctypes.c_int]
        # c_void_p (not c_char_p) so ctypes returns the raw pointer without
        # auto-copying; we must call GameFreeString ourselves.
        lib.GameGetActiveHookLabels.restype = ctypes.c_void_p

        lib.GameGetActiveCounterSlotLabels.argtypes = [ctypes.c_int]
        lib.GameGetActiveCounterSlotLabels.restype = ctypes.c_void_p

        lib.GameGetActionLabels.argtypes = [ctypes.c_int]
        lib.GameGetActionLabels.restype = ctypes.c_void_p

        lib.GameExportReplay.argtypes = [ctypes.c_int]
        lib.GameExportReplay.restype = ctypes.c_void_p

        lib.GameExportViewJSON.argtypes = [ctypes.c_int]
        lib.GameExportViewJSON.restype = ctypes.c_void_p

        lib.GameReplayToJSON.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        lib.GameReplayToJSON.restype = ctypes.c_void_p

        lib.RecordExtractInfoJSON.argtypes = [ctypes.c_char_p]
        lib.RecordExtractInfoJSON.restype = ctypes.c_void_p

        lib.GameFreeString.argtypes = [ctypes.c_void_p]
        lib.GameFreeString.restype = None

        # Sanity: Go-side DiceColorCount must match our Python constant.
        # This catches drift if DiceColor gets a new color added on one
        # side but not the other.
        from gicg_env._constants import DICE_COLOR_COUNT

        go_count = int(lib.GameGetDiceColorCount())
        if go_count != DICE_COLOR_COUNT:
            raise RuntimeError(f'DiceColorCount mismatch: Go={go_count} Python={DICE_COLOR_COUNT}')
