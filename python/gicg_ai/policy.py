import re


def greedy_spec(name: str) -> tuple[int, int]:
    match = re.fullmatch(r"F([1-5])D([1-9][0-9]*)", name)
    if match is None:
        raise RuntimeError(f"unknown policy {name!r}")
    return int(match[1]), int(match[2])


def validate_opponent(name: str) -> None:
    if name != "random":
        greedy_spec(name)
