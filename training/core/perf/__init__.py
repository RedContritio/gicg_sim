"""training.core.perf — opt-in perf tracing infrastructure.

Zero overhead when ``cfg.debug.perf_trace`` is False (default). See
``trace.py`` for the public API + ``tools/perf/analyze.py`` for the
offline analyzer.
"""

from training.core.perf import trace

__all__ = ['trace']
