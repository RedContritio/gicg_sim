import json
import secrets
import tomllib
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


class Choice(BaseModel):
    decision: int
    option: int


def snapshot(session: GameSession) -> dict:
    return json.loads(session.snapshot_json())


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path or ROOT / "configs" / "web" / "local.toml")
    games: dict[str, GameSession] = {}
    app = FastAPI(title="七圣召唤")

    def game(game_id: str) -> GameSession:
        try:
            return games[game_id]
        except KeyError as error:
            raise HTTPException(404, "对局不存在") from error

    @app.post("/api/games")
    async def create(body: CreateGame) -> dict:
        game_config = config["game"]
        session = GameSession(
            ROOT / game_config["ruleset"],
            [game_config["character"]],
            [game_config["character"]],
            [game_config["deck_card"]] * game_config["deck_size"],
            body.seed if body.seed is not None else secrets.randbits(64),
        )
        game_id = secrets.token_urlsafe(12)
        games[game_id] = session
        return {
            "game_id": game_id,
            "rules": json.loads(session.rules_json()),
            "state": snapshot(session),
        }

    @app.get("/api/games/{game_id}")
    async def inspect(game_id: str) -> dict:
        return snapshot(game(game_id))

    @app.post("/api/games/{game_id}/actions")
    async def act(game_id: str, body: dict) -> dict:
        session = game(game_id)
        try:
            result = session.submit(json.dumps(body))
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return json.loads(result)

    @app.post("/api/games/{game_id}/choices")
    async def choose(game_id: str, body: Choice) -> dict:
        try:
            return json.loads(game(game_id).choose(body.decision, body.option))
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def load_config(path: Path) -> dict:
    with path.open("rb") as file:
        return tomllib.load(file)
