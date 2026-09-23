import json
import secrets
import tomllib
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gicg_env import GameSession

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"
VENDOR = ROOT / "node_modules"


class CreateGame(BaseModel):
    seed: int | None = None
    player_one: list[str] | None = None
    player_two: list[str] | None = None
    player_one_deck: list[str] | None = None
    player_two_deck: list[str] | None = None


class Choice(BaseModel):
    decision: int
    option: int


def snapshot(session: GameSession) -> dict:
    return json.loads(session.snapshot_json())


def selected_players(
    body: CreateGame, defaults: list[list[str]], team_size: int
) -> list[list[str]]:
    players = [
        body.player_one if body.player_one is not None else defaults[0],
        body.player_two if body.player_two is not None else defaults[1],
    ]
    if any(len(player) != team_size for player in players):
        raise HTTPException(409, f"每位玩家需要选择 {team_size} 名角色")
    if any(len(set(player)) != len(player) for player in players):
        raise HTTPException(409, "同一队伍不能重复选择角色")
    return players


def new_session(game_config: dict, players: list[list[str]], seed: int = 1) -> GameSession:
    return configured_session(
        game_config,
        players,
        [game_config["player_one_deck"], game_config["player_two_deck"]],
        seed,
    )


def configured_session(
    game_config: dict,
    players: list[list[str]],
    decks: list[list[str]],
    seed: int,
) -> GameSession:
    return GameSession(
        ROOT / game_config["ruleset"],
        players[0],
        players[1],
        (decks[0], decks[1]),
        (
            game_config["team_size"],
            game_config["deck_size"],
            game_config["max_card_copies"],
        ),
        seed,
    )


def selected_decks(body: CreateGame, defaults: list[list[str]]) -> list[list[str]]:
    return [
        body.player_one_deck if body.player_one_deck is not None else defaults[0],
        body.player_two_deck if body.player_two_deck is not None else defaults[1],
    ]


def requested_session(
    game_config: dict,
    players: list[list[str]],
    decks: list[list[str]],
    seed: int,
) -> GameSession:
    try:
        return configured_session(game_config, players, decks, seed)
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


def stored_game(games: dict[str, GameSession], game_id: str) -> GameSession:
    try:
        return games[game_id]
    except KeyError as error:
        raise HTTPException(404, "对局不存在") from error


def runtime_json(operation: Callable[[], str]) -> dict:
    try:
        return json.loads(operation())
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from error


@lru_cache(maxsize=4096)
def evaluation_summary(path: Path, modified: int) -> dict:
    del modified
    data = json.loads(path.read_text())
    keys = (
        "candidate",
        "opponent",
        "games",
        "wins",
        "losses",
        "draws",
        "truncations",
        "win_rate",
        "seat_0_wins",
        "seat_1_wins",
        "average_m1",
    )
    summary = {key: data.get(key) for key in keys}
    summary.update(evaluation_names(data, path))
    return summary


def evaluation_names(data: dict, path: Path) -> dict[str, str]:
    opponent = data.get("opponent_name") or policy_name(data["opponent"])
    if "pruned" in path.stem:
        opponent = f"{opponent}P8"
    return {
        "candidate_name": data.get("candidate_name") or policy_name(data["candidate"]),
        "opponent_name": opponent,
    }


def policy_name(value: str) -> str:
    if value == "random":
        return "Random"
    source = Path(value.replace("\\", "/"))
    if source.suffix != ".pt":
        return value
    checkpoint = (ROOT / source).resolve()
    if ROOT not in checkpoint.parents:
        return "DMC"
    metadata = checkpoint.parent / "metadata.json"
    if not metadata.is_file():
        return "DMC"
    return str(json.loads(metadata.read_text())["algorithm"]).upper()


def evaluation_record(root: Path, path: Path) -> dict:
    relative = path.relative_to(root)
    record = evaluation_summary(path, path.stat().st_mtime_ns).copy()
    record.update({"id": relative.as_posix(), "record": path.stem})
    return record


def evaluation_runs(root: Path) -> list[dict]:
    grouped: dict[Path, list[Path]] = {}
    for path in root.glob("*/*/eval*.json"):
        grouped.setdefault(path.parent, []).append(path)
    reports = [run_summary(root, directory, paths) for directory, paths in grouped.items()]
    return sorted(reports, key=lambda report: (report["run"], report["id"]), reverse=True)


def run_summary(root: Path, directory: Path, paths: list[Path]) -> dict:
    relative = directory.relative_to(root)
    records = [evaluation_record(root, path) for path in paths]
    return {
        "id": relative.as_posix(),
        "experiment": relative.parts[0],
        "run": relative.parts[1],
        "candidates": sorted({record["candidate_name"] for record in records}),
        "opponents": sorted({record["opponent_name"] for record in records}),
        "evaluations": len(records),
        "games": sum(record["games"] for record in records),
        "m1_evaluations": sum(record["average_m1"] is not None for record in records),
    }


def run_directory(root: Path, report_id: str) -> Path:
    directory = (root / report_id).resolve()
    if root not in directory.parents or not directory.is_dir():
        raise HTTPException(404, "评测报告不存在")
    relative = directory.relative_to(root)
    if len(relative.parts) != 2 or not any(directory.glob("eval*.json")):
        raise HTTPException(404, "评测报告不存在")
    return directory


def run_report(root: Path, report_id: str) -> dict:
    directory = run_directory(root, report_id)
    paths = sorted(directory.glob("eval*.json"))
    report = run_summary(root, directory, paths)
    report["results"] = [evaluation_result(root, path) for path in paths]
    return report


def evaluation_result(root: Path, path: Path) -> dict:
    data = json.loads(path.read_text())
    data.update(evaluation_names(data, path))
    data.update({"id": path.relative_to(root).as_posix(), "record": path.stem})
    return data


def register_report_routes(app: FastAPI, artifact_root: Path) -> None:
    @app.get("/api/reports")
    async def report_index() -> list[dict]:
        return evaluation_runs(artifact_root)

    @app.get("/api/reports/{report_id:path}")
    async def report_result(report_id: str) -> dict:
        return run_report(artifact_root, report_id)

    @app.get("/reports")
    async def reports() -> FileResponse:
        return FileResponse(STATIC / "reports.html")

    @app.get("/reports/view/{report_id:path}")
    async def report(report_id: str) -> FileResponse:
        run_directory(artifact_root, report_id)
        return FileResponse(STATIC / "report.html")


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path or ROOT / "configs" / "web" / "local.toml")
    artifact_root = (ROOT / config["server"]["artifacts"]).resolve()
    game_config = config["game"]
    defaults = [game_config["player_one"], game_config["player_two"]]
    default_decks = [game_config["player_one_deck"], game_config["player_two_deck"]]
    catalog = new_session(game_config, defaults)
    rules = json.loads(catalog.rules_json())
    games: dict[str, GameSession] = {}
    app = FastAPI(title="七圣召唤")

    @app.get("/api/setup")
    async def setup() -> dict:
        return {
            "characters": rules["characters"],
            "team_size": game_config["team_size"],
            "players": defaults,
            "cards": rules["cards"],
            "decks": default_decks,
        }

    @app.post("/api/games")
    async def create(body: CreateGame) -> dict:
        players = selected_players(body, defaults, game_config["team_size"])
        decks = selected_decks(body, default_decks)
        session = requested_session(
            game_config,
            players,
            decks,
            body.seed if body.seed is not None else secrets.randbits(64),
        )
        game_id = secrets.token_urlsafe(12)
        games[game_id] = session
        return {
            "game_id": game_id,
            "rules": rules,
            "state": snapshot(session),
        }

    @app.get("/api/games/{game_id}")
    async def inspect(game_id: str) -> dict:
        return snapshot(stored_game(games, game_id))

    @app.post("/api/games/{game_id}/actions")
    async def act(game_id: str, body: dict) -> dict:
        session = stored_game(games, game_id)
        return runtime_json(lambda: session.submit(json.dumps(body)))

    @app.post("/api/games/{game_id}/choices")
    async def choose(game_id: str, body: Choice) -> dict:
        session = stored_game(games, game_id)
        return runtime_json(lambda: session.choose(body.decision, body.option))

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    register_report_routes(app, artifact_root)
    app.mount(
        "/vendor/echarts",
        StaticFiles(directory=VENDOR / "echarts" / "dist"),
        name="echarts",
    )
    app.mount(
        "/vendor/simple-statistics",
        StaticFiles(directory=VENDOR / "simple-statistics" / "dist"),
        name="simple-statistics",
    )
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def load_config(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)
