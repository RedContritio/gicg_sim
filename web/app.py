import json
import secrets
import tomllib
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gicg_env import GameSession


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "web" / "static"


class CreateGame(BaseModel):
    seed: int | None = None


class Action(BaseModel):
    kind: Literal["redraw", "reroll", "skill", "card", "tune", "switch", "end"]
    action: str | None = None
    hand: int | None = None
    slot: int | None = None
    die: int | None = None
    payment: list[int] = Field(default_factory=list)
    selected: list[int] = Field(default_factory=list)


class Choice(BaseModel):
    decision: int
    option: int


def create_app(config_path: Path | None = None) -> FastAPI:
    config = load_config(config_path or ROOT / "configs" / "web" / "local.toml")
    games: dict[str, GameSession] = {}
    app = FastAPI(title="七圣召唤")

    def state(session: GameSession) -> dict:
        return json.loads(session.snapshot_json())

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
        return {"game_id": game_id, "state": state(session)}

    @app.get("/api/games/{game_id}")
    async def inspect(game_id: str) -> dict:
        return state(game(game_id))

    @app.post("/api/games/{game_id}/actions")
    async def act(game_id: str, body: Action) -> dict:
        session = game(game_id)
        try:
            if body.kind == "redraw":
                result = session.redraw(body.selected)
            elif body.kind == "reroll":
                result = session.reroll(body.payment)
            elif body.kind == "skill" and body.action is not None:
                result = session.action(body.action, body.payment)
            elif body.kind == "card" and body.hand is not None:
                result = session.play_card(body.hand, body.payment)
            elif body.kind == "tune" and body.hand is not None and body.die is not None:
                result = session.tune(body.hand, body.die)
            elif body.kind == "switch" and body.slot is not None:
                result = session.switch(body.slot, body.payment)
            elif body.kind == "end":
                result = session.end_round()
            else:
                raise HTTPException(422, "行动参数不完整")
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
