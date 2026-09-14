"""Q network with explicit rule incidence; arbitrary counter/card IDs are pointers."""

import torch
from torch import nn

from training.core.network import make_actor_critic
from training.core.network.action_embedding import encode_actions
from training.core.network.perspective import relative_structural
from training.core.obs_constants import N_STRUCTURAL, OBS_MAX_CARD_TYPES
from training.core.structural import compute_structural_obspos, compute_structural_values


def gather(rows, indices):
    return rows.gather(1, indices.unsqueeze(-1).expand(-1, -1, rows.shape[-1]))


def mean_scatter(messages, indices, valid, size):
    out = messages.new_zeros((messages.shape[0], size, messages.shape[-1]))
    counts = messages.new_zeros((messages.shape[0], size, 1))
    out.scatter_add_(1, indices.unsqueeze(-1).expand_as(messages), messages * valid.unsqueeze(-1))
    counts.scatter_add_(1, indices.unsqueeze(-1), valid.unsqueeze(-1).to(messages.dtype))
    return out / counts.clamp_min(1)


class SemanticQNet(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.base = make_actor_critic(cfg, head_kinds={'q'}, use_typed_damage=True)
        d = cfg.d_model
        self.structure = nn.Embedding(N_STRUCTURAL + 1, d)
        self.owner = nn.Embedding(3, d)
        self.character = nn.Embedding(7, d)
        self.binding = nn.Embedding(129, d)
        self.method = nn.Embedding(2048, d)
        self.numeric = nn.Sequential(nn.Linear(3, d), nn.ReLU(), nn.Linear(d, d))
        self.relation = nn.Sequential(nn.Linear(d * 2, d), nn.ReLU(), nn.Linear(d, d))
        self.counter_norm = nn.LayerNorm(d)
        self.hook_norm = nn.LayerNorm(d)
        self.bucket = nn.Embedding(4, d)
        self.card_count = nn.Sequential(nn.Linear(2, d), nn.ReLU(), nn.Linear(d, d))
        self.enemy = nn.Linear(2, d)
        # Legacy identity encoders are not used by this model.
        self.base.counter_encoder.requires_grad_(False)
        self.base.card_encoder.requires_grad_(False)
        self.base.buff_encoder.source.requires_grad_(False)

    @property
    def hook_encoder(self):
        return self.base.hook_encoder

    def forward(self, x, *, return_state=False, return_actions=False):
        base = self.base
        values, sids, valid = x['counter_values'], x['counter_sids'], x['active_slot_mask']
        hooks = x.get('hook_emb')
        if hooks is None:
            hooks = self.hook_encoder(x['hook_ir'], x['hook_mask'])
        owners = x['counter_owners']
        numbers = torch.stack((values / 10, values.sign() * values.abs().log1p(), (values != 0).float()), -1)
        counter = (
            self.numeric(numbers)
            + self.structure(sids.clamp(0, N_STRUCTURAL))
            + self.owner((owners[..., 0] + 1).clamp(0, 2))
            + self.character((owners[..., 1] + 1).clamp(0, 6))
        )
        links = x['counter_links']
        edge_valid = links[..., 0] >= 0
        ci, hi = links[..., 0].clamp_min(0), links[..., 1].clamp_min(0)
        rel = self.binding((links[..., 2] + 1).clamp(0, 128)) + self.method(links[..., 3].clamp(0, 2047))
        counter_msg = self.relation(torch.cat((gather(hooks, hi), rel), -1))
        hook_msg = self.relation(torch.cat((gather(counter, ci), rel), -1))
        counter = self.counter_norm(counter + mean_scatter(counter_msg, ci, edge_valid, values.shape[1]))
        hooks = self.hook_norm(hooks + mean_scatter(hook_msg, hi, edge_valid, hooks.shape[1]))
        sl = torch.cat((x['skill_links'], x['card_hook_links']), dim=1)
        sv = sl[..., 0] >= 0
        canonical, effect = sl[..., 0].clamp_min(0), sl[..., 1].clamp_min(0)
        definition_links = torch.where(sv.unsqueeze(-1), torch.stack((canonical, effect), -1), -1)
        hooks = base.definition_relation(hooks, definition_links)
        # Preserve unlinked counters too, including their owner and value.
        source_counter = counter
        count = int(valid.sum(1).max().clamp_min(1))
        positions = valid.float().argsort(dim=1, descending=True, stable=True)[:, :count]
        counter = gather(counter, positions)
        mask = valid.gather(1, positions)
        for layer in base.cross_layers:
            counter, hooks = layer(counter, hooks, mask, x['hook_mask'])
        counter_pool = (counter * mask.unsqueeze(-1)).sum(1) / mask.sum(1, keepdim=True).clamp_min(1)
        hook_pool = (hooks * x['hook_mask'].unsqueeze(-1)).sum(1) / x['hook_mask'].sum(1, keepdim=True).clamp_min(1)
        cl = x['card_links']
        cv = cl[..., 0] >= 0
        card_rules = mean_scatter(
            gather(hooks, cl[..., 1].clamp_min(0)), cl[..., 0].clamp_min(0), cv, OBS_MAX_CARD_TYPES
        )
        counts = x['card_buckets']
        buckets = self.bucket(torch.arange(4, device=values.device))[None, :, None, :]
        ct = self.card_count(torch.stack((counts / 10, counts.log1p()), -1))
        tokens = self.relation(torch.cat(((card_rules[:, None] + buckets).expand_as(ct), ct), -1))
        present = counts > 0
        cards = (tokens * present.unsqueeze(-1)).sum((1, 2)) / present.sum((1, 2)).clamp_min(1)[:, None]
        cards = cards + self.enemy(x['enemy_sizes'])
        structural = compute_structural_values(values, compute_structural_obspos(sids, valid))
        pools = [
            counter_pool,
            hook_pool,
            base.char_skill_pooler(hooks, x['char_skill_refs']),
            cards,
            base.meta_proj(x['meta']),
            base.readout(relative_structural(structural, x['meta'])),
            base.typed_damage(x['recent_damage'], x['prepare_skill'], x['modifier_log']),
        ]
        combined = torch.cat([norm(p) for norm, p in zip(base.pool_norms, pools)], -1)
        buffs = x['buffs']
        # Buff source SIDs resolve to semantic counter tokens; no random-ID embedding.
        sid_to_position = torch.zeros((values.shape[0], 2000), device=values.device, dtype=torch.long)
        pos = torch.arange(values.shape[1], device=values.device)[None].expand_as(sids)
        sid_to_position.scatter_reduce_(1, sids.clamp(0, 1999), (pos + 1) * valid, reduce='amax')
        sources = buffs[..., 13].long()
        binding = gather(source_counter, (sid_to_position.gather(1, sources.clamp(0, 1999)) - 1).clamp_min(0))
        binding = binding * (sources >= 0).unsqueeze(-1)
        buff_pool, buff_tokens = base.buff_encoder(buffs, hooks, source_features=binding, return_tokens=True)
        state = base.state_proj(combined) + buff_pool
        actions = encode_actions(base, hooks, x['action_refs'], x['action_payments'], buffs, buff_tokens)
        logits = base.heads['q'](state, actions)
        if return_actions:
            return logits, state, actions
        return (logits, state) if return_state else logits
