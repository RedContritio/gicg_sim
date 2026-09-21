"""Expert-set likelihood and optional frozen-policy regularization."""

import torch


def imitation_loss(logits, tied, objective='uniform', anchor_logits=None, anchor_beta=0.0, executed=None):
    if objective not in ('uniform', 'set', 'executed') or anchor_beta < 0:
        raise ValueError('invalid imitation objective')
    logp = logits.log_softmax(-1)
    terms = []
    if objective == 'executed':
        if executed is None or len(executed) != len(tied):
            raise ValueError('executed actions required for the executed objective')
    for i, indices in enumerate(tied):
        if not indices or len(indices) != len(set(indices)):
            raise ValueError('expert set must be nonempty and unique')
        if objective == 'executed':
            terms.append(-logp[i, executed[i]])
        else:
            values = logp[i, indices]
            terms.append(-values.mean() if objective == 'uniform' else -values.logsumexp(0))
    fit = torch.stack(terms).mean()
    kl = logits.new_zeros(())
    if anchor_beta:
        if anchor_logits is None:
            raise ValueError('anchor logits required')
        old = anchor_logits.detach().log_softmax(-1)
        kl = (old.exp() * (old - logp)).sum(-1).mean()
    return fit + anchor_beta * kl, fit.detach(), kl.detach()
