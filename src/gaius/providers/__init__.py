"""Cloud GPU providers for Gaius.

Provides clients for external compute resources used when models
are too large for local hardware.
"""

from .lambdalabs import LambdaLabsClient, InstanceType, InstanceAvailability
from .cerebras import CerebrasClient, CerebrasModel

__all__ = [
    "LambdaLabsClient",
    "InstanceType",
    "InstanceAvailability",
    "CerebrasClient",
    "CerebrasModel",
]
