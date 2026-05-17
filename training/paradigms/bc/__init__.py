"""BC paradigm adapter — implements core.protocols.Paradigm.

Bridges the unified pipeline driver (training.core.pipeline.run_pipeline)
to BC (behavior cloning) static-dataset training. First-class per D1 —
abstracted out of training/az/bc_*.py + training/ppo/bc_*.py (those
remain in place until P5 physical mv dedupe).

BC is production fallback per ADR-0009 (r009 epoch_3 vs F1-D2 = 0.75).
"""

from training.paradigms.bc.paradigm import BCParadigm

__all__ = ['BCParadigm']
