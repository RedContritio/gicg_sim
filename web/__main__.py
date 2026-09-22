import argparse
from pathlib import Path

import uvicorn

from web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("configs/web/local.toml"))
    args = parser.parse_args()
    config = load_server(args.config)
    uvicorn.run(create_app(args.config), host=config["host"], port=config["port"])


def load_server(path: Path) -> dict:
    import tomllib

    with path.open("rb") as file:
        return tomllib.load(file)["server"]


if __name__ == "__main__":
    main()
