from pathlib import Path

from gicg_ai.evaluate import evaluate
from gicg_ai.train import train

ROOT = Path(__file__).resolve().parent.parent


def test_training_resume_and_evaluation(tmp_path: Path) -> None:
    source = (ROOT / "configs" / "train" / "smoke.toml").read_text()
    config = tmp_path / "train.toml"
    config.write_text(source.replace("episodes = 2", "episodes = 1", 1))
    first = train(config, tmp_path)
    checkpoint = first / "checkpoint.pt"

    config.write_text(source)
    resumed_a = train(config, tmp_path, checkpoint)
    resumed_b = train(config, tmp_path, checkpoint)

    assert (resumed_a / "metrics.jsonl").read_text() == (resumed_b / "metrics.jsonl").read_text()
    result = evaluate(
        ROOT / "configs" / "eval" / "smoke.toml",
        candidate_checkpoint=resumed_a / "checkpoint.pt",
    )
    assert result["games"] == 4
    assert result["wins"] + result["losses"] == 4
