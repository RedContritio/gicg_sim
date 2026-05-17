"""IPC primitives — SHM ring + queue wrappers."""

from training.core.actor.ipc.queue import IPCQueue
from training.core.actor.ipc.ring import SHMRing

__all__ = ['IPCQueue', 'SHMRing']
