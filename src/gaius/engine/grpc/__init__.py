"""gRPC server and servicers for Gaius Engine.

This module provides:
- GrpcServer: Main gRPC server lifecycle management
- InferenceServicer: KServe Open Inference Protocol (OIP) implementation
- GaiusServicer: Custom Gaius extensions

The gRPC server is the primary transport for gaius-engine, replacing the
non-functional Aeron IPC with a production-ready, standards-compliant
gRPC/OIP implementation.

Usage:
    from gaius.engine.grpc import GrpcServer, GrpcConfig

    config = GrpcConfig(port=50051)
    server = GrpcServer(config)
    await server.start()
"""

from .server import GrpcServer, GrpcConfig

__all__ = ["GrpcServer", "GrpcConfig"]
