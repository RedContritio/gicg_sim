import json
import secrets
import tomllib
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from gicg_env import GameSession

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"


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


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path or ROOT / "configs" / "web" / "local.toml")
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

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def load_config(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)
