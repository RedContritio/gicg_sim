"""Policy-retention arms over the paired-consequence objective.

The failure being isolated: ``paired_training.run`` put every parameter of the policy
network *and* the rule head into one AdamW under a pure regression loss (``objective``,
no main-task term), and the imitation-warm-started policy collapsed. Each arm here
varies exactly one preservation mechanism against the same checkpoint, the same paired
data, the same step budget and the same seed.

Gradient-cosine gating follows Du et al. (arXiv:1812.02224, "Adapting Auxiliary Losses
Using Gradient Similarity"): the auxiliary gradient is admitted only while its cosine
with the main-task gradient is non-negative. The main-task proxy is the D2-imitation
gradient on real teacher rows -- a fixed, non-degenerate reference that is identical
across arms at step 0, so the reported cosine is comparable between arms. A
KL-to-warmup proxy is deliberately *not* used for gating: that gradient is exactly zero
at initialisation (the current policy *is* the warmup policy), so its cosine is
undefined there. The KL term is still used, as the anchor it is.

Only the ``binary`` gate is implemented. Du et al. note the weighted variant needs
per-layer averaging to fight minibatch noise; deferring it keeps the arm interpretable.

The gate cancels only the *shared policy* contribution of the auxiliary gradient. The
rule head is trained by the auxiliary loss alone, so folding the gate into a scalar
loss weight would silently freeze the head on blocked steps.
"""

import copy
from dataclasses import dataclass
import random

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.imitation_loss import imitation_loss
from tools.experiments.semantic_training.paired_replay import PairedReplay
from tools.experiments.semantic_training.paired_training import assess
from tools.experiments.semantic_training.representation_drift import cosine_similarity
from tools.experiments.semantic_training.rule_auxiliary import attach_adapter


@dataclass(frozen=True)
class ArmSpec:
    """One preservation mechanism. Everything else is held fixed across arms."""

    name: str
    trainable: str  # 'all' | 'head' | 'isolated'
    learning_rate: float
    probe_fraction: float = 0.0  # >0 freezes the policy for the first fraction of steps
    replay_lambda: float = 0.0
    anchor_beta: float = 0.0
    gate: str = 'off'  # 'off' | 'binary'


def arm_specs(*, learning_rate=3e-4, finetune_learning_rate=3e-5, replay_lambda=1.0, anchor_beta=1.0):
    """The arm ladder. ``historical`` is deliberately absent: under a single code base it
    would duplicate ``full``, so the harm reproduction is carried by ``full`` alone."""
    return {
        'full': ArmSpec('full', 'all', learning_rate),
        'frozen': ArmSpec('frozen', 'head', learning_rate),
        'probe_then_finetune': ArmSpec('probe_then_finetune', 'all', finetune_learning_rate, probe_fraction=0.5),
        'full_lowlr': ArmSpec('full_lowlr', 'all', finetune_learning_rate),
        'replay': ArmSpec('replay', 'all', learning_rate, replay_lambda=replay_lambda),
        'anchored': ArmSpec('anchored', 'all', learning_rate, anchor_beta=anchor_beta, gate='binary'),
        'isolated_rule': ArmSpec('isolated_rule', 'isolated', learning_rate),
    }


def policy_trainable_names(agent):
    """Names the network itself considers trainable.

    ``SemanticQNet.__init__`` freezes the legacy identity encoders (counter, card, and
    the buff source shared with the counter SID embedding), so a blanket
    ``requires_grad_(True)`` would wrongly revive them.
    """
    return {name for name, parameter in agent.net.named_parameters() if parameter.requires_grad}


def apply_trainable(agent, names, trainable):
    for name, parameter in agent.net.named_parameters():
        if name in names:
            parameter.requires_grad_(trainable)


def trainable_parameters(agent):
    return [parameter for parameter in agent.net.parameters() if parameter.requires_grad]


def _sample_rows(rows, rng, count):
    if not rows:
        raise ValueError('teacher rows are required for this arm')
    return rng.choices(rows, k=count)


def _teacher_batch(agent, rows):
    return batch_observations([row['obs'] for row in rows], agent.cfg, agent.device)


def _masked_logits(agent, batch, net=None):
    return (net or agent.net)(batch).masked_fill(~batch['legal_mask'], -1e9)


def imitation_fit(agent, rows):
    """Expert-set NLL against the D2 teacher's tied action set (rehearsal objective)."""
    batch = _teacher_batch(agent, rows)
    logits = _masked_logits(agent, batch)
    loss, _, _ = imitation_loss(logits, [row['tied'] for row in rows], 'uniform', None, 0.0)
    return loss


def anchor_kl(agent, anchor_net, rows):
    """Differentiable forward KL(warmup || current) on real teacher states."""
    batch = _teacher_batch(agent, rows)
    logits = _masked_logits(agent, batch)
    with torch.no_grad():
        reference = _masked_logits(agent, batch, net=anchor_net).log_softmax(-1)
    logp = logits.log_softmax(-1)
    return (reference.exp() * (reference - logp)).sum(-1).mean()


def _gradients(loss, parameters):
    grads = torch.autograd.grad(loss, parameters, allow_unused=True)
    return [torch.zeros_like(p) if g is None else g for p, g in zip(parameters, grads)]


def policy_gradient_cosine(agent, sampler, rows, rng, teacher_batch=32):
    """cos(main-task grad, auxiliary grad) over the shared policy parameters.

    ``None`` when the arm trains no shared parameter (the head-only arm has no policy
    conflict to measure) or when either gradient has zero norm -- a zero-norm cosine is
    undefined, not orthogonal.
    """
    parameters = trainable_parameters(agent)
    if not parameters:
        return None
    main = _gradients(imitation_fit(agent, _sample_rows(rows, rng, teacher_batch)), parameters)
    aux = _gradients(sampler(agent), parameters)
    return cosine_similarity(main, aux)


def run_arm(
    agent,
    spec,
    pairs,
    teacher_rows,
    *,
    steps,
    beta=1.0,
    seed=0,
    batch_pairs=8,
    teacher_batch=32,
    diag_every=50,
    cos_momentum=0.9,
):
    """Train one arm in place and return ``(agent, report)``.

    The same agent object is mutated; callers own checkpoint writing so this stays
    testable without touching the filesystem.
    """
    if steps < 1:
        raise ValueError('steps must be positive')
    if spec.gate not in ('off', 'binary'):
        raise ValueError(f'unsupported gate {spec.gate!r}')
    if beta < 0 or spec.replay_lambda < 0 or spec.anchor_beta < 0:
        raise ValueError('loss weights must be non-negative')
    if diag_every < 1 or not 0 <= cos_momentum < 1:
        raise ValueError('invalid diagnostic cadence or cosine momentum')
    needs_teacher = spec.replay_lambda or spec.anchor_beta or spec.gate != 'off'
    if needs_teacher and not teacher_rows:
        raise ValueError('this arm requires teacher rows')

    rng = random.Random(seed)
    torch.manual_seed(seed)
    agent.net.eval()
    names = policy_trainable_names(agent)
    if spec.trainable == 'isolated' and not hasattr(agent, 'rule_adapter'):
        attach_adapter(agent)
    anchor = copy.deepcopy(agent.net).eval().requires_grad_(False) if spec.anchor_beta else None
    replay = PairedReplay(pairs, seed, batch_pairs=batch_pairs)
    diagnostic = PairedReplay(pairs, seed + 7919, batch_pairs=batch_pairs)
    probe_steps = int(steps * spec.probe_fraction)
    report = {
        'arm': spec.name,
        'trainable': spec.trainable,
        'learning_rate': spec.learning_rate,
        'probe_steps': probe_steps,
        'replay_lambda': spec.replay_lambda,
        'anchor_beta': spec.anchor_beta,
        'gate': spec.gate,
        'cos_momentum': cos_momentum,
        'steps': steps,
        'beta': beta,
        'initial': assess(agent, pairs),
        'probe_exit': None,
        'trace': [],
        'undefined_cos': 0,
        'gate_blocks': 0,
        'cos_ema_final': None,
    }
    optimizer = None
    frozen = None
    eta = None
    for step in range(1, steps + 1):
        freeze_policy = spec.trainable != 'all' or step <= probe_steps
        if freeze_policy != frozen:
            frozen = freeze_policy
            apply_trainable(agent, names, not frozen)
            rule_parameters = list(agent.rule_head.parameters())
            if spec.trainable == 'isolated':
                rule_parameters = list(agent.rule_adapter.parameters()) + rule_parameters
            optimizer = torch.optim.AdamW(
                trainable_parameters(agent) + rule_parameters,
                lr=spec.learning_rate,
                weight_decay=0,
            )
            if step == probe_steps + 1:
                report['probe_exit'] = assess(agent, pairs)

        measured = spec.gate != 'off' or step == 1 or step % diag_every == 0 or step == steps
        cos = policy_gradient_cosine(agent, diagnostic, teacher_rows, rng, teacher_batch) if measured else None
        if measured:
            if cos is None:
                report['undefined_cos'] += 1
            else:
                eta = cos if eta is None else cos_momentum * eta + (1 - cos_momentum) * cos
                report['trace'].append({'step': step, 'cos': cos, 'cos_ema': eta})
        blocked = spec.gate == 'binary' and eta is not None and eta < 0
        if blocked:
            report['gate_blocks'] += 1

        optimizer.zero_grad(set_to_none=True)
        auxiliary = replay(agent)
        if not torch.isfinite(auxiliary):
            raise ValueError(f'nonfinite auxiliary loss in arm {spec.name}')
        auxiliary.backward()
        if blocked:
            # Drop only the shared-policy contribution; the head keeps learning.
            for parameter in trainable_parameters(agent):
                parameter.grad = None
        if spec.replay_lambda:
            (spec.replay_lambda * imitation_fit(agent, _sample_rows(teacher_rows, rng, teacher_batch))).backward()
        if spec.anchor_beta:
            (spec.anchor_beta * anchor_kl(agent, anchor, _sample_rows(teacher_rows, rng, teacher_batch))).backward()
        parameters = optimizer.param_groups[0]['params']
        norm = torch.nn.utils.clip_grad_norm_(parameters, 5)
        if not torch.isfinite(norm):
            raise ValueError(f'nonfinite gradient in arm {spec.name}')
        optimizer.step()

    report.update(
        final=assess(agent, pairs),
        frozen_at_end=frozen,
        cos_ema_final=eta,
        steps_done=steps,
    )
    return agent, report
