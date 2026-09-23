import json
from pathlib import Path

from gicg_ai.evaluate import evaluate
from gicg_ai.train import train

ROOT = Path(__file__).resolve().parent.parent


def test_training_resume_and_evaluation(tmp_path: Path) -> None:
    source = (ROOT / "configs" / "train" / "smoke.toml").read_text()
    config = tmp_path / "train.toml"
    config.write_text(source)
    overrides = ("training.episodes=1",)
    first = train(config, tmp_path, overrides=overrides)
    checkpoint = first / "checkpoint.pt"
    assert json.loads((first / "metadata.json").read_text())["overrides"] == list(overrides)
    first_metrics = json.loads((first / "metrics.jsonl").read_text().splitlines()[0])
    assert first_metrics["transitions"] > 0
    assert first_metrics["replay_size"] >= first_metrics["transitions"]
    assert first_metrics["updates"] > 0
    assert first_metrics["outcome"] in {-1.0, 0.0, 1.0}

    config.write_text(source.replace("max_steps = 4096", "max_steps = 1"))
    truncated = train(config, tmp_path, overrides=overrides)
    truncated_metrics = json.loads((truncated / "metrics.jsonl").read_text())
    assert truncated_metrics["outcome"] == 0.0
    assert truncated_metrics["truncated"] is True

    config.write_text(source)
    resumed_a = train(config, tmp_path, checkpoint)
    resumed_b = train(config, tmp_path, checkpoint)

    assert (resumed_a / "metrics.jsonl").read_text() == (resumed_b / "metrics.jsonl").read_text()
    result = evaluate(
        ROOT / "configs" / "eval" / "smoke.toml",
        candidate_checkpoint=resumed_a / "checkpoint.pt",
    )
    assert result["games"] == 4
    assert result["wins"] + result["losses"] + result["draws"] + result["truncations"] == 4

    evaluation_source = (ROOT / "configs" / "eval" / "smoke.toml").read_text()
    evaluation_config = tmp_path / "eval.toml"
    evaluation_config.write_text(evaluation_source.replace("max_steps = 4096", "max_steps = 1"))
    truncated_result = evaluate(evaluation_config)
    assert truncated_result["wins"] == 0
    assert truncated_result["losses"] == 0
    assert truncated_result["draws"] == 0
    assert truncated_result["truncations"] == 4
