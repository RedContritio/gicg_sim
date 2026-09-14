"""Inspect/remove pre-reset Windows training outputs via the repository SSH wrapper.

Only timestamped old run directories and known legacy log/index containers are
eligible. Never follows reparse points. Refuses cleanup while repo Python runs.
"""

import argparse
from pathlib import Path

from tools.runs._host import load_remote_from_cfg, ps_quote, ssh_run


def script(root, apply=False):
    action = '$dirs | Remove-Item -Recurse -Force' if apply else ''
    return f"""
$ErrorActionPreference='Stop';
$root={ps_quote(root)};
if (!(Test-Path -LiteralPath $root -PathType Container)) {{ throw 'Repository missing' }};
$procs=@(Get-Process | Where-Object {{ $_.ProcessName -match '^(python|pythonw)$' }});
if ($procs.Count -gt 0) {{ $procs | Select-Object Id,ProcessName | ConvertTo-Json; throw 'Python processes present; stop training first' }};
$art=Join-Path $root 'artifacts';
$names=@('replays_final_fixed_F1D4', 'replays_final_sid1', 'replays_peak_fixed_F1D4', 'replays_pilot20k_F1D4', '_perf_logs_n16_B', '_perf_logs_n16_I25', '_perf_logs_n24_B', '_perf_logs_n24_I25', '_perf_logs_n4_after', '_perf_logs_n4_B', '_perf_logs_n8_after', '_perf_logs_n8_B', 'eval_4cls.log', 'eval_final.log', 'eval_fixed.log', 'eval_peak.log', 'eval_peak_hist.log', 'pilot.err', 'pilot.log', 'pilot20k.log', 'pilot20k_fixed.log', '_b_train2.log', '_b_train3.log', '_b_train_inline.log', '_eval_service.err.log', '_eval_service.log', '_i25.err', '_i25.log', '_mem_probe.log', '_mem_trajectory.log', '_n16_probe.log', '_n24_probe.log', '_test.log', '_test_b.log', '_test_pilot.log');
$dirs=@($names | ForEach-Object {{ Get-Item -LiteralPath (Join-Path $art $_) -ErrorAction SilentlyContinue }});
$links=@($dirs | Where-Object {{ $_.Attributes -band [IO.FileAttributes]::ReparsePoint }});
$links+=@($dirs | Get-ChildItem -Recurse -Force | Where-Object {{ $_.Attributes -band [IO.FileAttributes]::ReparsePoint }});
if ($links.Count -gt 0) {{ throw 'Refusing reparse points' }};
$inventory=@($dirs | ForEach-Object {{
 $files=@(Get-ChildItem -LiteralPath $_.FullName -File -Recurse -Force);
 [pscustomobject]@{{path=$_.FullName;files=$files.Count;bytes=($files | Measure-Object Length -Sum).Sum}}
}});
$recent=@($dirs | Get-ChildItem -Recurse -Force | Where-Object {{ $_.LastWriteTimeUtc -ge [datetime]'2026-07-01T00:00:00Z' }});
$recent+=@($dirs | Where-Object {{ $_.LastWriteTimeUtc -ge [datetime]'2026-07-01T00:00:00Z' }});
if ($recent.Count) {{ throw 'Refusing entries newer than the inspected pre-reset period' }};
$inventory | ConvertTo-Json -Depth 4;
{action};
if ({'$true' if apply else '$false'}) {{
 $remaining=@($dirs | Where-Object {{ Test-Path -LiteralPath $_.FullName }});
 if ($remaining.Count) {{ throw 'Cleanup incomplete' }};
 Write-Output 'CLEANUP_VERIFIED';
}}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cfg', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if remote is None or remote.os != 'windows':
        parser.error('requires Windows remote config')
    result = ssh_run(remote, script(remote.root, args.apply), timeout=60)
    print(result.stdout)
    print(result.stderr)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
