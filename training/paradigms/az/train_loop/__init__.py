"""Async training loop + per-iteration helpers used by
``training.paradigms.az.train_az`` (mv from ``legacy/train_loop/`` per
FU-W4-AZ-rewrite Phase 2 T2.ζ — final adapter zero-legacy step).

Legacy siblings ``legacy/train_loop/*.py`` stay alive (Phase 5 git rm);
tools / probes / smoke-style scripts that imported them directly still
function until those callers redirect in Phase 3+.
"""
