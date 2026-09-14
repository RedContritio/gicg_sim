"""Reject semantic action aliases before sampling, allowing duplicate hand copies."""

import numpy as np


def check_action_aliases(env):
    refs = np.asarray(env.get_action_refs())
    payments = np.asarray(env.get_legal_action_payments())
    identities = np.asarray(env.get_action_identities())
    if not len(refs) == len(payments) == len(identities):
        raise AssertionError('action identity alignment failed')
    seen = {}
    for ref, pay, identity in zip(refs, payments, identities):
        key = tuple(ref.tolist() + pay.tolist())
        native = tuple(identity.tolist())
        if key in seen and seen[key] != native:
            raise AssertionError(f'NN cannot distinguish actions: {seen[key]} vs {native}; ref/payment={key}')
        seen[key] = native
    return len(seen)
