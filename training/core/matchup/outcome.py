"""Strict terminal outcome shared by file evaluation tools."""


def terminal_outcome(winner: int, perspective: int) -> int:
    if perspective not in (0, 1):
        raise ValueError('outcome perspective must be 0 or 1')
    if winner not in (0, 1, 2):
        raise ValueError('outcome requires a terminal winner (0/1/2)')
    return 0 if winner == 2 else (1 if winner == perspective else -1)
