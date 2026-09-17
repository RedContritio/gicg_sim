"""Run a command locally or on the cfg-declared remote host.

CLI:

    .venv/bin/python -m tools.runs.exec <cfg.toml> [--stream] [--timeout S] -- <argv...>

The cfg ``[meta].host`` value selects local vs remote dispatch. Long-running
commands should use ``--stream`` so stdout and stderr remain visible.
"""

from __future__ import annotations

import sys

from tools.runs._ssh import main as _main


def main(argv: list[str] | None = None) -> int:
    return _main(argv, prog='tools.runs.exec')


if __name__ == '__main__':
    sys.exit(main())
