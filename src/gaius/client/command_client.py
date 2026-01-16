"""Command client for unified command routing.

This module provides the CommandClient for the thin client architecture.
All commands from TUI/CLI/MCP are routed through here to the gRPC CommandService.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Optional

import grpc
from grpc import aio

from ..engine.generated import (
    ExecuteCommandRequest,
    ExecuteCommandResponse,
    ReindexRequest,
    ReindexResponse,
    ReindexProgress,
    GaiusServiceAsyncStub,
)

logger = logging.getLogger(__name__)


class ReindexPhase(Enum):
    """Reindex phases matching proto enum."""

    STARTED = 0
    SCANNING = 1
    EMBEDDING = 2
    PROJECTING = 3
    TDA = 4
    SAVING = 5
    COMPLETE = 6
    ERROR = 7


@dataclass
class CommandResult:
    """Result from executing a command."""

    success: bool
    command: str
    message: str
    data: Optional[dict] = None
    generation: int = 0
    duration_ms: int = 0


@dataclass
class ReindexStatus:
    """Status update from reindexing."""

    phase: ReindexPhase
    progress: float  # 0.0 to 1.0
    message: str
    documents_processed: int = 0
    documents_total: int = 0


class CommandClient:
    """Client for unified command routing via gRPC.

    This is the single entry point for all commands in the thin client
    architecture. Commands are routed through the CommandService RPC.

    Usage:
        client = await get_command_client()
        result = await client.execute("goto", "5,5")

        # Or use streaming for long operations
        async for status in client.reindex_stream("build/dev"):
            print(f"{status.phase.name}: {status.progress:.0%}")
    """

    def __init__(self, channel: aio.Channel, stub: GaiusServiceAsyncStub):
        self._channel = channel
        self._stub = stub
        self._client_id = "command-client"

    async def execute(
        self,
        command: str,
        args: str = "",
        kb_root: str = "build/dev",
        context: Optional[dict[str, str]] = None,
    ) -> CommandResult:
        """Execute a command via the CommandService.

        Args:
            command: Command name (e.g., "goto", "domain", "reindex")
            args: Command arguments as string
            kb_root: KB root for context
            context: Additional context dict (cursor_x, cursor_y, etc.)

        Returns:
            CommandResult with success status and data
        """
        try:
            request = ExecuteCommandRequest(
                command=command,
                args=args,
                kb_root=kb_root,
                client_id=self._client_id,
                context=context or {},
            )

            response: ExecuteCommandResponse = await self._stub.ExecuteCommand(request)

            # Parse JSON result if present
            data = None
            if response.result_json:
                try:
                    data = json.loads(response.result_json)
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse result_json for {command}")

            return CommandResult(
                success=response.success,
                command=response.command,
                message=response.message,
                data=data,
                generation=response.generation,
                duration_ms=response.duration_ms,
            )

        except grpc.RpcError as e:
            logger.error(f"gRPC error executing command {command}: {e}")
            return CommandResult(
                success=False,
                command=command,
                message=f"gRPC error: {e.code().name}",
            )

    async def reindex(
        self,
        kb_root: str = "build/dev",
        force: bool = False,
        embedding_model: str = "",
    ) -> CommandResult:
        """Execute a blocking reindex operation.

        For progress updates, use reindex_stream() instead.

        Args:
            kb_root: KB root to reindex
            force: Force reindex even if up-to-date
            embedding_model: Override default embedding model

        Returns:
            CommandResult with reindex results
        """
        try:
            request = ReindexRequest(
                kb_root=kb_root,
                client_id=self._client_id,
                force=force,
                embedding_model=embedding_model,
            )

            response: ReindexResponse = await self._stub.Reindex(request)

            return CommandResult(
                success=response.success,
                command="reindex",
                message=response.message,
                data={
                    "documents_indexed": response.documents_indexed,
                    "documents_skipped": response.documents_skipped,
                    "generation": response.generation,
                    "duration_ms": response.duration_ms,
                },
                generation=response.generation,
                duration_ms=response.duration_ms,
            )

        except grpc.RpcError as e:
            logger.error(f"gRPC error during reindex: {e}")
            return CommandResult(
                success=False,
                command="reindex",
                message=f"gRPC error: {e.code().name}",
            )

    async def reindex_stream(
        self,
        kb_root: str = "build/dev",
        force: bool = False,
        embedding_model: str = "",
    ) -> AsyncIterator[ReindexStatus]:
        """Stream reindex progress updates.

        Args:
            kb_root: KB root to reindex
            force: Force reindex even if up-to-date
            embedding_model: Override default embedding model

        Yields:
            ReindexStatus updates as reindexing progresses
        """
        try:
            request = ReindexRequest(
                kb_root=kb_root,
                client_id=self._client_id,
                force=force,
                embedding_model=embedding_model,
            )

            async for progress in self._stub.ReindexStream(request):
                yield ReindexStatus(
                    phase=ReindexPhase(progress.phase),
                    progress=progress.progress,
                    message=progress.message,
                    documents_processed=progress.documents_processed,
                    documents_total=progress.documents_total,
                )

        except grpc.RpcError as e:
            logger.error(f"gRPC error during reindex stream: {e}")
            yield ReindexStatus(
                phase=ReindexPhase.ERROR,
                progress=0.0,
                message=f"gRPC error: {e.code().name}",
            )

    async def close(self) -> None:
        """Close the client connection."""
        await self._channel.close(grace=None)


# Singleton instance
_command_client: Optional[CommandClient] = None
_client_lock = asyncio.Lock()


async def get_command_client(
    host: str = "localhost",
    port: int = 50051,
) -> CommandClient:
    """Get or create the global CommandClient instance.

    Args:
        host: gRPC server host
        port: gRPC server port

    Returns:
        CommandClient singleton instance
    """
    global _command_client

    async with _client_lock:
        if _command_client is None:
            channel = aio.insecure_channel(f"{host}:{port}")
            stub = GaiusServiceAsyncStub(channel)
            _command_client = CommandClient(channel, stub)
            logger.info(f"Created CommandClient connected to {host}:{port}")

        return _command_client


async def close_command_client() -> None:
    """Close the global CommandClient instance."""
    global _command_client

    async with _client_lock:
        if _command_client is not None:
            await _command_client.close()
            _command_client = None
            logger.info("Closed CommandClient")
