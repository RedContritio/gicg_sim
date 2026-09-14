"""Build the versioned pilot report from validated fresh results."""

import json
from pathlib import Path

import numpy as np

from training.core.artifact_io import load_dataset, validate


def main():
    out = Path('openspec/changes/clean-training-v6')
    runs = {}
    for seed in (41, 42, 43):
        data = json.loads(Path(f'artifacts/clean_v6_seed{seed}/final_evaluation.json').read_text())
        validate(data['provenance'])
        assert len(data['results']) == 10
        assert all(r['truncated'] == 0 for group in data['results'].values() for r in group.values())
        runs[str(seed)] = data
    (out / 'learning-results.json').write_text(json.dumps(runs, indent=2) + '\n')
    cost = json.loads(Path('artifacts/clean_cost_v6/report.json').read_text())
    primitive = json.loads(Path('artifacts/clean_primitive_control_v6/report.json').read_text())
    for name, data in [('cost-results.json', cost), ('primitive-results.json', primitive)]:
        validate(data['provenance'])
        (out / name).write_text(json.dumps(data, indent=2) + '\n')
    with (
        load_dataset('artifacts/clean_cost_v6/a_train.npz') as a,
        load_dataset('artifacts/clean_cost_v6/b_train.npz') as b,
    ):
        kinds = np.concatenate([a['action_refs'][:, 0], b['action_refs'][:, 0]])
        costs = np.concatenate([a['costs'], b['costs']])
    means = {k: costs[kinds == k].mean() for k in set(kinds)}
    with load_dataset('artifacts/clean_cost_v6/combination_test.npz') as test:
        prediction = np.array([means.get(k, costs.mean()) for k in test['action_refs'][:, 0]])
        kind_mse = float(np.mean((prediction - test['costs']) ** 2))
    labels = {
        'random_base': '随机策略／原环境',
        'initial_base': '初始化网络／原环境',
        'trained_base': '训练 3000 帧／原环境',
        'random_held': '随机策略／新环境',
        'zero_shot': '零样本／新环境',
        'adapt_250': '微调 250 帧／新环境',
        'adapt_1000': '微调 1000 帧／新环境',
        'scratch_1000': '从零 1000 帧／新环境',
        'retention_250': '微调 250 后／原环境',
        'retention_1000': '微调 1000 后／原环境',
    }
    lines = [
        '# 干净训练试验结果（2026-09-11）',
        '',
        '本轮完成入口隔离与一组有限预算学习实验，不代表策略已收敛。原环境有学习信号；',
        '零样本未明显超过随机，微调有平均收益但种子差异与遗忘明显。',
        '',
        '## 真实对局',
        '',
        '原环境：赤蝶 vs 墨客，测试卡_增幅/测试卡_碎片；新环境：乘胜追击/速速茶点。',
        '5 回合上限，牌库补齐 15 张，3 个训练种子；每场景 16 个评估种子、交换位置。',
        '表内是 **胜=1、平=0.5、负=0 的平均得分**，不是纯胜率。',
        '逐场胜平负和按场景对 bootstrap 的区间见 [原始结果](learning-results.json)。',
        '共执行 1920 场正式评估，无步数截断；复用局面和重复随机基线不能算独立样本。',
        '',
        '| 模型/环境 | 对随机：种子 41/42/43 | 对随机均值 | 对 F1-D2 均值 |',
        '|---|---|---:|---:|',
    ]
    for key, label in labels.items():
        values = [runs[str(seed)]['results'][key]['random']['score'] for seed in (41, 42, 43)]
        heuristic = [runs[str(seed)]['results'][key]['F1-D2']['score'] for seed in (41, 42, 43)]
        lines.append(
            f'| {label} | '
            + '/'.join(f'{v:.1%}' for v in values)
            + f' | {np.mean(values):.1%} | {np.mean(heuristic):.1%} |'
        )
    lines += [
        '',
        '零样本对随机均值 38.5%，接近随机策略的 37.5%；没有可靠泛化证据。',
        '1000 帧微调对新环境优于同预算从零训练，但基础训练成本未计入这 1000 帧，不能宣称总算力更省。',
        '种子 41 的原环境得分由 59.4% 降至 12.5%，遗忘严重；250 帧微调也出现崩塌。',
        'F1-D2 得分仍低，当前不宜进入大规模长训。',
        '',
        '## 费用规则与原语表示',
        '',
        '费用标签直接来自引擎，训练/测试按整局种子分离，卡牌组合整体留出。探针是监督学习，不能代替整局胜率。',
        '训练 150 次更新；微调用 16/64 条新样本，与原环境混采 60 次更新。小样本来自 1 个训练局，局内相关性很强。',
        f'行动类别均值基线 MSE={kind_mse:.4f}；下表为三种子均值。',
        '',
        '| 费用探针 | 留出组合 MSE |',
        '|---|---:|',
    ]
    lines.append(f'| 零样本 | {np.mean([r["base"]["combination"]["mse"] for r in cost["results"]]):.4f} |')
    for count in (16, 64):
        value = np.mean([r[f'combination_{count}']['target']['mse'] for r in cost['results']])
        lines.append(f'| {count} 条样本微调 | {value:.4f} |')
    lines += [
        '',
        '探针零样本弱于简单行动类别基线，尚不能确认组合规则已被充分理解。',
        '以逸待劳/荷花酥组未产生新 opcode，原始 JSON 的 primitive 组名只表示候选组，不能当作真正原语留出。',
        '独立受控实验把已有减法重编码成新增 SUB opcode，词表 16→17，只改变表示，未新增引擎能力。',
        '',
        '| 新表示微调样本 | 新 SUB 编码 MSE | 保持原编码、同量训练 MSE |',
        '|---|---:|---:|',
    ]
    for count in (16, 64):
        values = [r[str(count)] for r in primitive['results']]
        lines.append(
            f'| {count} | {np.mean([v["target"]["mse"] for v in values]):.4f} | '
            f'{np.mean([v["unchanged_representation_control"]["mse"] for v in values]):.4f} |'
        )
    lines += [
        '',
        '新行参数确有更新，但必须结合不扩词表的训练对照解释；不能把额外训练的收益归因于新原语理解。',
        '原语样本与遗忘明细见 [原始数据](primitive-results.json)，费用探针见 [数据](cost-results.json)。',
        '',
        '## 可复现性与后续',
        '',
        '两个独立进程重复同 seed 的 4 局/61 帧训练，所有模型张量与逻辑状态完全一致，墙钟时间除外。',
        '完整配置、干净权重与采样数据在 artifacts/clean_*_v6 和 artifacts/clean_v6_seed{41,42,43}。',
        '旧评估入口覆盖随机策略 epsilon、混用含平局得分与纯胜率区间的问题已修复；错误的初步评估已删除。',
        '下一步应补齐观测缺口，并针对短程微调崩塌做稳定性实验；真正新增引擎原语仍需独立实现与语义验收。',
    ]
    (out / 'results.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
