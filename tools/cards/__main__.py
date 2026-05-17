"""tools.cards 入口 dispatch。

子命令::

    .venv/bin/python -m tools.cards fetch --type all
    .venv/bin/python -m tools.cards transform --raw-dir <dir> --out-dir <dir>

或直接 invoke 模块::

    .venv/bin/python -m tools.cards.fetch ...
    .venv/bin/python -m tools.cards.cli ...
"""

from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return 0
    sub = sys.argv[1]
    sys.argv = [f'tools.cards.{sub}'] + sys.argv[2:]
    if sub == 'fetch':
        from tools.cards.fetch import main as f

        return f()
    if sub in ('transform', 'cli'):
        from tools.cards.cli import main as c

        return c()
    print(f'unknown subcommand: {sub}', file=sys.stderr)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
