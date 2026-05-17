"""Phase-1 架构诊断：定位 hook channel 失效在哪一层.

跑 5 个子实验，输出判读矩阵能用的数据:

1. hook_emb 置零 ablation — 网络是否使用 hook channel
2. HookEncoder unit test — encoder 本身是否 work
3. 训练前后权重对比 — 梯度是否流到 hook 通路
4. 梯度流静态测试 — 单次 forward+backward 的 per-module grad norm
5. CrossAttention weights — hook 方向的 attention 分布

依赖:
    artifacts/202604170616_az_c1_random_500/final_champion.pt

Usage:
    .venv/bin/python -m tools.diag_hook_path
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

from gicg_env import GicgEnv
from training.paradigms.az.config import random_1v1_config
from training.paradigms.az.network import Agent

import sys as _sys

CKPT = Path(_sys.argv[1]) if len(_sys.argv) > 1 else Path('artifacts/202604170616_az_c1_random_500/final_champion.pt')


def _prepare_obs():
    """Build a real mid-game obs + eval inputs (copied from
    probe_numeric_sensitivity.py)."""
    cfg = random_1v1_config(data_dir='data')
    env = GicgEnv(
        team_0=cfg.scenario.team_0,
        team_1=cfg.scenario.team_1,
        card_pool=cfg.scenario.card_pool,
        seed=7,
        data_dir='data',
    )
    rng = np.random.default_rng(7)
    env.reset(seed=7)
    for _ in range(2):
        if env.done:
            break
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            break
        env.step(int(rng.integers(0, len(kinds))))
    static = env.static_obs
    dyn = env._get_obs()
    refs = env.get_action_refs()
    payments = env.get_legal_action_payments()
    return cfg, static, dyn, refs, payments


def _inputs_tensors(agent, static, dyn, refs, payments):
    """Convert to batched tensors used by agent.net.forward."""
    agent.encode_static(static)
    counter_values, meta, card_buckets, enemy_sizes = agent._parse_dynamic_single(dyn)
    refs_padded = agent._pad_action_refs(refs)
    pay_padded = agent._pad_action_payments(payments)
    refs_t = torch.tensor(refs_padded, dtype=torch.long, device=agent.device).unsqueeze(0)
    pay_t = torch.tensor(pay_padded, dtype=torch.float32, device=agent.device).unsqueeze(0)
    structural_values = counter_values.gather(1, agent._structural_obspos)
    return {
        'counter_values': counter_values,
        'counter_sids': agent._counter_sids,
        'active_slot_mask': agent._active_slot_mask,
        'hook_emb_cached': agent._hook_emb,
        'hook_mask': agent._hook_mask,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'meta': meta,
        'action_refs': refs_t,
        'action_payments': pay_t,
        'structural_values': structural_values,
    }


# --------------------------------------------------------------------------- #
# sub-experiments


def sub1_hook_emb_ablation(agent, inputs):
    print('\n=== Sub-1: hook_emb 置零 ablation ===')
    with torch.no_grad():
        logits_base, v_base, _ = agent.net(**{k: v for k, v in inputs.items()})
        inputs_zero = dict(inputs)
        inputs_zero['hook_emb_cached'] = torch.zeros_like(inputs['hook_emb_cached'])
        logits_zero, v_zero, _ = agent.net(**inputs_zero)

        inputs_rand = dict(inputs)
        inputs_rand['hook_emb_cached'] = torch.randn_like(inputs['hook_emb_cached'])
        logits_rand, v_rand, _ = agent.net(**inputs_rand)

    n_legal = (inputs['action_refs'][0, :, 0] != 193).sum().item()
    pi_base = torch.softmax(logits_base[0, :n_legal], -1)
    pi_zero = torch.softmax(logits_zero[0, :n_legal], -1)
    pi_rand = torch.softmax(logits_rand[0, :n_legal], -1)
    print(f'  baseline:    v={v_base.item():+.5f}  top1_pi={pi_base.max():.5f} idx={pi_base.argmax()}')
    print(f'  hook=zero:   v={v_zero.item():+.5f}  top1_pi={pi_zero.max():.5f} idx={pi_zero.argmax()}')
    print(f'  hook=random: v={v_rand.item():+.5f}  top1_pi={pi_rand.max():.5f} idx={pi_rand.argmax()}')
    dv_zero = abs(v_base.item() - v_zero.item())
    dv_rand = abs(v_base.item() - v_rand.item())
    print(f'  Δv(zero)={dv_zero:.6f}  Δv(rand)={dv_rand:.6f}')
    print(f'  VERDICT: {"HOOK IGNORED (Δv<1e-4)" if dv_zero < 1e-4 and dv_rand < 1e-4 else "HOOK USED"}')


def sub2_encoder_unit_test(agent, static):
    print('\n=== Sub-2: HookEncoder unit test ===')
    # 取两个不同的 token seq 直接喂 hook_encoder
    n_cnt = agent.cfg.n_counter_slots
    meta_size = n_cnt * 3
    hook_data = torch.tensor(static[meta_size:], dtype=torch.float32, device=agent.device).view(
        agent.cfg.n_hooks, agent.cfg.max_tokens_per_hook, 2
    )
    types = hook_data[:, :, 0].long()
    values = hook_data[:, :, 1].float()
    active_mask = types.sum(-1) != 0
    # take 2 different active hooks
    active_idx = active_mask.nonzero(as_tuple=True)[0][:2]
    if len(active_idx) < 2:
        print('  SKIP: fewer than 2 active hooks')
        return
    h1, h2 = active_idx[0].item(), active_idx[1].item()

    with torch.no_grad():
        emb_pair = agent.net.hook_encoder(
            types[active_idx].unsqueeze(0),
            values[active_idx].unsqueeze(0),
            torch.ones(1, 2, dtype=torch.bool, device=agent.device),
        )[0]
    emb1, emb2 = emb_pair[0], emb_pair[1]
    cos = torch.nn.functional.cosine_similarity(emb1, emb2, dim=0).item()
    l2 = (emb1 - emb2).norm().item()
    print(f'  hook {h1} tokens[:10]: {types[h1, :10].tolist()}')
    print(f'  hook {h2} tokens[:10]: {types[h2, :10].tolist()}')
    print(f'  emb cosine similarity: {cos:.4f}')
    print(f'  emb L2 distance: {l2:.4f}')
    print(f'  emb1 norm: {emb1.norm():.4f}  emb2 norm: {emb2.norm():.4f}')
    print(f'  VERDICT: {"ENCODER DEAD (cos>0.99)" if cos > 0.99 else "ENCODER WORKS"}')


def sub3_weight_delta(agent_trained, cfg):
    print('\n=== Sub-3: 训练前后权重对比 (L2 norm of Δ per module) ===')
    agent_init = Agent(cfg.agent)  # random init, same arch
    trained_sd = agent_trained.net.state_dict()
    init_sd = agent_init.net.state_dict()

    per_module = {}  # module prefix → (delta_l2_sum, param_l2_sum, n_params)
    for name, p in trained_sd.items():
        if name not in init_sd:
            continue
        delta = (p - init_sd[name]).norm().item()
        base = init_sd[name].norm().item()
        mod = name.split('.')[0]
        agg = per_module.setdefault(mod, [0.0, 0.0, 0])
        agg[0] += delta
        agg[1] += base
        agg[2] += p.numel()

    print(f'  {"module":<25} {"Δ_L2":>10} {"init_L2":>10} {"ratio":>7}')
    for mod in sorted(per_module.keys()):
        d, b, n = per_module[mod]
        ratio = d / b if b > 0 else 0
        flag = ' ← STAGNANT' if ratio < 0.05 else ''
        print(f'  {mod:<25} {d:>10.3f} {b:>10.3f} {ratio * 100:>6.2f}%{flag}')


def sub4_grad_flow(agent, inputs):
    print('\n=== Sub-4: 梯度流测试 (single fwd+bwd, per-module grad norm) ===')
    agent.net.train()
    agent.net.zero_grad()
    logits, value, _ = agent.net(**inputs)
    # synthetic target: max value, uniform policy
    loss = ((value - 0.5) ** 2).mean() + (-torch.log_softmax(logits, -1)).mean()
    loss.backward()

    per_module = {}
    for name, p in agent.net.named_parameters():
        if p.grad is None:
            continue
        mod = name.split('.')[0]
        agg = per_module.setdefault(mod, [0.0, 0])
        agg[0] += p.grad.norm().item() ** 2
        agg[1] += p.numel()

    print(f'  {"module":<25} {"grad_L2":>12} {"n_params":>10}')
    for mod in sorted(per_module.keys()):
        g_sq, n = per_module[mod]
        flag = ' ← NO GRAD' if g_sq**0.5 < 1e-4 else ''
        print(f'  {mod:<25} {g_sq**0.5:>12.6f} {n:>10}{flag}')
    agent.net.eval()


def sub5_cross_attention_weights(agent, inputs):
    print('\n=== Sub-5: CrossAttention weights 统计 ===')
    # hook into each cross layer's counter_to_hook MultiheadAttention
    attn_records = []
    hooks = []
    for i, layer in enumerate(agent.net.cross_layers):
        for name, attn in [
            ('c→h', layer.counter_to_hook),
            ('h→c', layer.hook_to_counter),
        ]:

            def make_hook(layer_i, n):
                def hook(module, inp, out):
                    # nn.MultiheadAttention forward returns (attn_output, attn_weights)
                    if isinstance(out, tuple) and len(out) >= 2 and out[1] is not None:
                        attn_records.append((f'L{layer_i}-{n}', out[1].detach()))

                return hook

            hooks.append(attn.register_forward_hook(make_hook(i, name)))

    # MultiheadAttention needs need_weights=True — default is True in torch
    with torch.no_grad():
        # we need to force return_attn — monkey-patch forward temporarily
        _orig_forwards = []
        for layer in agent.net.cross_layers:
            for attn in (layer.counter_to_hook, layer.hook_to_counter):
                orig = attn.forward
                _orig_forwards.append((attn, orig))

                def patched(self=attn, _orig=orig):
                    def f(*a, **kw):
                        kw['need_weights'] = True
                        kw['average_attn_weights'] = True
                        return _orig(*a, **kw)

                    return f

                attn.forward = patched()
        agent.net(**inputs)
        for attn, orig in _orig_forwards:
            attn.forward = orig
    for h in hooks:
        h.remove()

    if not attn_records:
        print('  SKIP: could not capture attention weights')
        return

    print(f'  {"layer":<12} {"shape":<18} {"max":>8} {"mean":>8} {"std":>8} {"entropy":>10}')
    for name, w in attn_records:
        # w: (B, Lq, Lk) — average over B and query dim, look at key (hook dim) distribution
        if w.dim() == 3:
            w_mean = w[0].mean(0)  # (Lk,)
        else:
            w_mean = w.mean()
        mx = w.max().item()
        mn = w.mean().item()
        sd = w.std().item()
        probs = w_mean.clamp(min=1e-12)
        probs = probs / probs.sum()
        ent = -(probs * probs.log()).sum().item()
        ent_max = float(torch.log(torch.tensor(float(probs.numel()))))
        print(f'  {name:<12} {str(tuple(w.shape)):<18} {mx:>8.4f} {mn:>8.5f} {sd:>8.5f} {ent:>6.3f}/{ent_max:.2f}')


def main():
    if not CKPT.exists():
        print(f'ERROR: ckpt not found: {CKPT}')
        return 1

    print(f'Loading: {CKPT}')
    cfg, static, dyn, refs, payments = _prepare_obs()
    agent = Agent(cfg.agent)
    agent.load(str(CKPT))
    agent.net.eval()
    inputs = _inputs_tensors(agent, static, dyn, refs, payments)

    sub1_hook_emb_ablation(agent, inputs)
    sub2_encoder_unit_test(agent, static)
    sub3_weight_delta(agent, cfg)
    sub4_grad_flow(agent, inputs)
    sub5_cross_attention_weights(agent, inputs)
    print('\n=== diagnostics done ===')
    return 0


if __name__ == '__main__':
    sys.exit(main())
