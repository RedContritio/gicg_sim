from pathlib import Path

from gicg_ai.train import train

ROOT = Path(__file__).resolve().parent.parent


def test_training_produces_checkpoint(tmp_path: Path) -> None:
    run = train(ROOT / "configs" / "train" / "smoke.toml", tmp_path)

    assert (run / "checkpoint.pt").stat().st_size > 0
    assert len((run / "metrics.jsonl").read_text().splitlines()) == 2
