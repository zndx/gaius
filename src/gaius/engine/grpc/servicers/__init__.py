"""gRPC servicer implementations for Gaius Engine.

This module provides servicer classes that implement the gRPC service interfaces:
- InferenceServicer: KServe OIP GRPCInferenceService
- GaiusServicer: Custom Gaius extensions (GaiusService)
"""

from .inference_servicer import InferenceServicer
from .gaius_servicer import GaiusServicer

__all__ = ["InferenceServicer", "GaiusServicer"]
