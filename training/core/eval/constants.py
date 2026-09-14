"""Shared network defaults for the evaluation service."""

from __future__ import annotations


# Bind to loopback by default. Deployments that expose the service must
# opt in by passing a different host.
DEFAULT_HOST = 'localhost'

# Default TCP port for the evaluation service.
DEFAULT_PORT = 9100
