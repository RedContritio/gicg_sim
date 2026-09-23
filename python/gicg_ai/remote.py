import argparse
import base64
import shutil
import subprocess
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Host:
    ssh: str
    hostname: str
    root: str
    python: str
    mac: str
    broadcast: str
    cargo_registry: str


def load_host(name: str, path: Path = Path("configs/hosts.toml")) -> Host:
    with path.open("rb") as file:
        raw = tomllib.load(file)[name]
    return Host(**raw)


def powershell(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode()


def ssh(host: Host, script: str, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            host.ssh,
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-OutputFormat",
            "Text",
            "-EncodedCommand",
            powershell("$ProgressPreference='SilentlyContinue'; " + script),
        ],
        check=True,
        capture_output=capture,
        text=True,
    )


def wake(host: Host, timeout: int = 180) -> None:
    executable = shutil.which("wakeonlan")
    if executable is None:
        raise RuntimeError("wakeonlan is required")
    subprocess.run([executable, "-i", host.broadcast, host.mac], check=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = ssh(host, "$env:COMPUTERNAME", capture=True)
        except subprocess.CalledProcessError:
            time.sleep(5)
            continue
        if host.hostname in result.stdout:
            return
        raise RuntimeError(f"connected to unexpected host: {result.stdout.strip()}")
    raise TimeoutError(f"{host.ssh} did not become ready within {timeout} seconds")


def sync(host: Host) -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "source.zip"
        subprocess.run(["git", "archive", "--format=zip", "HEAD", "-o", archive], check=True)
        ssh(host, f"New-Item -ItemType Directory -Force '{host.root}' | Out-Null")
        subprocess.run(["scp", "-q", archive, f"{host.ssh}:{host.root}/.source.zip"], check=True)
        ssh(
            host,
            f"Expand-Archive -Force '{host.root}/.source.zip' '{host.root}'; "
            f"Remove-Item '{host.root}/.source.zip'",
        )


def prepare(host: Host) -> None:
    cargo = "$env:USERPROFILE + '/.cargo/bin'"
    cargo_config = (
        '[source.crates-io]\nreplace-with = "mirror"\n\n'
        f'[source.mirror]\nregistry = "{host.cargo_registry}"\n'
    )
    ssh(
        host,
        f"New-Item -ItemType Directory -Force '{host.root}/.cargo' | Out-Null; "
        f"Set-Content -Encoding utf8 '{host.root}/.cargo/config.toml' '{cargo_config}'; "
        f"$env:PATH = ({cargo}) + ';' + $env:PATH; "
        f"Set-Location '{host.root}'; "
        f"& '{host.python}' -m pip install -e '.[train]'; "
        "if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }",
    )


def train(host: Host, config: str) -> None:
    artifacts = f"{host.root}/artifacts"
    ssh(
        host,
        f"New-Item -ItemType Directory -Force '{artifacts}' | Out-Null; "
        f"$process = Start-Process -PassThru -WorkingDirectory '{host.root}' "
        f"-FilePath '{host.python}' "
        f"-ArgumentList @('-m','gicg_ai.train','{config}','--artifacts','artifacts') "
        f"-RedirectStandardOutput '{artifacts}/train.out' "
        f"-RedirectStandardError '{artifacts}/train.err'; "
        f"Set-Content '{artifacts}/train.pid' $process.Id; $process.Id",
    )


def status(host: Host) -> None:
    script = (
        f"$pidFile = '{host.root}/artifacts/train.pid'; "
        "if (!(Test-Path $pidFile)) { Write-Output 'idle'; exit 0 }; "
        "$trainPid = [int](Get-Content $pidFile); "
        "$process = Get-Process -Id $trainPid -ErrorAction SilentlyContinue; "
        "if ($process) { Write-Output ('running pid=' + $trainPid) } "
        "else { Write-Output ('stopped pid=' + $trainPid) }; "
        f"Get-Content '{host.root}/artifacts/train.err' -Tail 20 -ErrorAction SilentlyContinue"
    )
    ssh(host, script)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("wake", "sync", "prepare", "train", "status"))
    parser.add_argument("host")
    parser.add_argument("config", nargs="?", default="configs/train/dmc.toml")
    arguments = parser.parse_args()
    host = load_host(arguments.host)
    actions = {
        "wake": wake,
        "sync": sync,
        "prepare": prepare,
        "train": lambda selected: train(selected, arguments.config),
        "status": status,
    }
    actions[arguments.action](host)


if __name__ == "__main__":
    main()
