"""Read a training pipeline's progress in at most 200 UTF-8 bytes, including newline."""

import argparse
import json
from pathlib import Path
import time


def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def describe(root, now=None):
    root = Path(root)
    now = time.time() if now is None else now
    source = root / 'completion.json'
    if not source.exists():
        source = root / 'status.json'
    status = read(source)
    if not status:
        return '暂无进度记录（可能尚在冒烟）'
    state = status.get('status')
    if state == 'failed':
        text = '失败｜' + status.get('error', '查看 console.log')
    elif state == 'complete':
        score = status.get('selected_recheck', {}).get('score')
        text = f'完成｜耗时{status.get("wall_s", 0) / 60:.1f}m'
        if score is not None:
            text += f'｜复核胜率{score:.1%}'
    elif 'pairs_total' in status:
        if status.get('stage') == 'building':
            detail = f'样本{status.get("pairs_done", 0)}/{status["pairs_total"]}对'
        else:
            arm = {'paired': '配对', 'absolute': '绝对监督'}.get(status.get('arm'), '评估')
            detail = f'{arm}{status.get("step", 0)}/{status["steps"]}步'
        age = max(0, now - source.stat().st_mtime)
        text = f'进度记录｜{detail}｜累计{status.get("wall_s", 0) / 60:.1f}m｜{age:.0f}s前更新'
    else:
        round_ = status.get('round', 0)
        stage = status.get('stage')
        detail = {}
        path = source
        label = '初始化'
        if stage == 'rl' and 'arm' in status:
            path = root / status['arm'] / 'result.json'
            training = read(path)
            round_ = min(len(training.get('iterations', [])) + 1, status['iterations'])
            directory = Path(training['run']) / f'rollouts/iteration_{round_}' if 'run' in training else None
            files = list(directory.glob('episode_*.pt')) if directory else []
            detail = {'episodes_done': len(files)}
            label = '采集' if len(files) < status['episodes'] else '更新/待评估'
            if files:
                path = max(files, key=lambda p: p.stat().st_mtime)
            evaluation = root / status['arm'] / f'dev_{round_}/result.json'
            if evaluation.exists():
                path, detail, label = evaluation, read(evaluation), '开发评估'
        elif stage in ('variant_selection', 'independent_development_recheck') and 'panel' in status:
            path = root / status['panel'] / 'result.json'
            detail, label = read(path), status['panel']
        elif stage == 'dagger':
            path = root / f'round_{round_}/result.json'
            detail = read(path)
            label = '采集'
            if detail.get('status') == 'complete':
                path = root / f'dev_{round_}/result.json'
                detail = read(path)
                label = '开发评估'
            elif detail.get('status') == 'training':
                label = '更新'
        elif stage == 'initial_evaluation':
            path = root / 'dev_0/result.json'
            detail = read(path)
            label = '基线评估'
        elif stage == 'independent_development_recheck':
            path = root / 'baseline_recheck/result.json'
            detail = read(path)
            label = '基线复核'
            if detail.get('status') == 'complete':
                path = root / 'selected_recheck/result.json'
                detail = read(path)
                label = '候选复核'
        count = ''
        if 'games' in detail:
            count = f'{len(detail["games"])}/{detail["scenarios"] * 2 * detail["layouts"]}局'
        elif label == '更新':
            count = f'{detail.get("step", 0)}/{detail.get("steps", status["steps"])}步'
        elif label == '采集':
            count = f'{detail.get("episodes_done", 0)}/{status["episodes"]}局'
        elapsed = max(0, now - source.stat().st_mtime + status.get('wall_s', 0))
        age = max(0, now - (path if path.exists() else source).stat().st_mtime)
        prefix = '失败记录' if detail.get('status') == 'failed' else '进度记录'
        arm = {'auxiliary': '辅助', 'control': '对照'}.get(status.get('arm'), '')
        total = status.get('rounds', status.get('iterations', '?'))
        text = f'{prefix}{arm}｜轮{round_}/{total}｜{label}{count}｜累计{elapsed / 60:.1f}m｜{age:.0f}s前更新'
    return text.encode('utf-8')[:199].decode('utf-8', errors='ignore')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('root')
    p.add_argument('--local', action='store_true')
    a = p.parse_args()
    if a.local:
        print(describe(a.root))
        return
    from tools.runs._host import load_remote_from_cfg, discover_remote_python, scp_to, ssh_run, ps_quote

    remote = load_remote_from_cfg(Path(a.config))
    if remote is None:
        print(describe(a.root))
        return
    if remote.os != 'windows':
        raise ValueError('remote progress currently supports Windows hosts')
    relative = 'tools/experiments/semantic_training/progress.py'
    scp_to(remote, Path(relative), relative).check_returncode()
    python = discover_remote_python(remote)
    command = (
        f'Set-Location {ps_quote(remote.root)}; & {ps_quote(python)} -X utf8 '
        f'-m tools.experiments.semantic_training.progress {ps_quote(a.config)} {ps_quote(a.root)} --local'
    )
    result = ssh_run(remote, command, timeout=30)
    result.check_returncode()
    print(result.stdout.strip().encode('utf-8')[:199].decode('utf-8', errors='ignore'))


if __name__ == '__main__':
    main()
