"""KServe Open Inference Protocol (OIP) servicer implementation.

This module implements the GRPCInferenceService as defined by KServe OIP v2.
It provides standard inference endpoints that are compatible with any OIP client.

Reference:
- https://github.com/kserve/open-inference-protocol
- https://kserve.github.io/website/latest/modelserving/v1beta1/torchserve/
"""

import logging
import time
from typing import TYPE_CHECKING

import grpc
from grpc import aio

from ...generated import (
    # Request/Response types
    ServerLiveRequest,
    ServerLiveResponse,
    ServerReadyRequest,
    ServerReadyResponse,
    ModelReadyRequest,
    ModelReadyResponse,
    ServerMetadataRequest,
    ServerMetadataResponse,
    ModelMetadataRequest,
    ModelMetadataResponse,
    ModelInferRequest,
    ModelInferResponse,
    InferTensorContents,
    # Servicer base class
    GRPCInferenceServiceServicer,
)
from gaius.core.budgets import REASONING_MAX_TOKENS

if TYPE_CHECKING:
    from ..server import ServiceRegistry

logger = logging.getLogger(__name__)

# Server version
SERVER_VERSION = "0.2.0"
SERVER_NAME = "gaius-engine"


class InferenceServicer(GRPCInferenceServiceServicer):
    """KServe OIP GRPCInferenceService implementation.

    Implements the standard inference protocol endpoints:
    - ServerLive: Is the server alive?
    - ServerReady: Is the server ready to accept inference requests?
    - ModelReady: Is a specific model ready?
    - ServerMetadata: Get server information
    - ModelMetadata: Get model information
    - ModelInfer: Perform inference

    The servicer delegates actual inference to the backend router,
    which manages optillm and vLLM endpoints.
    """

    def __init__(self, services: "ServiceRegistry"):
        self._services = services

    async def ServerLive(
        self,
        request: ServerLiveRequest,
        context: aio.ServicerContext,
    ) -> ServerLiveResponse:
        """Check if the server is live (able to respond).

        This is the most basic health check - just confirms the server
        is running and can respond to requests.
        """
        return ServerLiveResponse(live=True)

    async def ServerReady(
        self,
        request: ServerReadyRequest,
        context: aio.ServicerContext,
    ) -> ServerReadyResponse:
        """Check if the server is ready for inference.

        Returns ready=True if at least one backend is available.
        """
        ready = False

        # Check if backend router is available
        if self._services.backend_router:
            status = self._services.backend_router.get_status()
            # Ready if any backend is healthy
            ready = any(
                b.get("healthy", False)
                for b in status.get("backends", {}).values()
            )
        else:
            # No backend router yet - server not ready
            ready = False

        return ServerReadyResponse(ready=ready)

    async def ModelReady(
        self,
        request: ModelReadyRequest,
        context: aio.ServicerContext,
    ) -> ModelReadyResponse:
        """Check if a specific model is ready for inference.

        Args:
            request: Contains model_name to check

        Returns:
            ModelReadyResponse with ready status
        """
        model_name = request.name
        ready = False

        if self._services.backend_router:
            status = self._services.backend_router.get_status()

            # Check if model is available via any backend
            for backend_name, backend_status in status.get("backends", {}).items():
                if backend_status.get("healthy", False):
                    # Check if this backend serves this model/agent
                    if model_name in backend_status.get("models", []):
                        ready = True
                        break
                    # Also check agent aliases
                    if model_name in backend_status.get("agents", []):
                        ready = True
                        break

            # Check configured agents
            if self._services.config and not ready:
                agents = self._services.config.agents
                if model_name in agents:
                    # Agent is configured, check if backend is healthy
                    agent = agents[model_name]
                    backend = status.get("backends", {}).get(agent.backend, {})
                    ready = backend.get("healthy", False)

        return ModelReadyResponse(ready=ready)

    async def ServerMetadata(
        self,
        request: ServerMetadataRequest,
        context: aio.ServicerContext,
    ) -> ServerMetadataResponse:
        """Get server metadata.

        Returns server name, version, and available extensions.
        """
        extensions = []

        # Add extensions based on available services
        if self._services.backend_router:
            extensions.append("inference")
        if self._services.get_health_metrics:
            extensions.append("health_streaming")
        if self._services.get_evolution_status:
            extensions.append("evolution")

        return ServerMetadataResponse(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            extensions=extensions,
        )

    async def ModelMetadata(
        self,
        request: ModelMetadataRequest,
        context: aio.ServicerContext,
    ) -> ModelMetadataResponse:
        """Get metadata for a specific model.

        Args:
            request: Contains model_name

        Returns:
            ModelMetadataResponse with model information
        """
        model_name = request.name

        # Default response for unknown model
        response = ModelMetadataResponse(
            name=model_name,
            versions=[],
            platform="unknown",
            inputs=[],
            outputs=[],
        )

        if self._services.config:
            agents = self._services.config.agents

            if model_name in agents:
                agent = agents[model_name]
                response = ModelMetadataResponse(
                    name=model_name,
                    versions=["v1"],
                    platform=agent.backend,
                    inputs=[],  # LLM: text input
                    outputs=[],  # LLM: text output
                )

        return response

    async def ModelInfer(
        self,
        request: ModelInferRequest,
        context: aio.ServicerContext,
    ) -> ModelInferResponse:
        """Perform inference using a model.

        This is the main inference endpoint. It extracts the prompt from
        the request inputs, routes to the appropriate backend, and
        returns the result.

        OIP expects tensor inputs/outputs, but for LLMs we use:
        - Input: "prompt" tensor with string data
        - Output: "completion" tensor with string data

        Args:
            request: ModelInferRequest with model_name and inputs

        Returns:
            ModelInferResponse with inference results
        """
        start_time = time.time()
        model_name = request.model_name

        # Check if backend router is available
        if not self._services.backend_router:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Backend router not initialized")
            return ModelInferResponse(model_name=model_name, id=request.id)

        # Extract prompt from inputs
        prompt = ""
        system_prompt = ""
        max_tokens = REASONING_MAX_TOKENS
        temperature = 0.7

        for input_tensor in request.inputs:
            if input_tensor.name == "prompt":
                # Get prompt from tensor contents
                if input_tensor.contents.bytes_contents:
                    prompt = input_tensor.contents.bytes_contents[0].decode("utf-8")
            elif input_tensor.name == "system_prompt":
                if input_tensor.contents.bytes_contents:
                    system_prompt = input_tensor.contents.bytes_contents[0].decode("utf-8")

        # Extract parameters
        for key, value in request.parameters.items():
            if key == "max_tokens":
                max_tokens = int(value.int64_param)
            elif key == "temperature":
                temperature = float(value.double_param)

        if not prompt:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("No prompt provided in inputs")
            return ModelInferResponse(model_name=model_name, id=request.id)

        try:
            # Perform inference via backend router
            result = await self._services.backend_router.complete(
                prompt=prompt,
                agent_alias=model_name,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Build response
            latency_ms = (time.time() - start_time) * 1000

            # Create output tensor with completion
            output_contents = InferTensorContents(
                bytes_contents=[result.content.encode("utf-8")]
            )

            response = ModelInferResponse(
                model_name=model_name,
                model_version="v1",
                id=request.id,
            )

            # Add output tensor
            output = response.outputs.add()
            output.name = "completion"
            output.datatype = "BYTES"
            output.shape.extend([1])
            output.contents.CopyFrom(output_contents)

            # Add metadata as parameters
            response.parameters["tokens_used"].int64_param = result.output_tokens
            response.parameters["latency_ms"].double_param = latency_ms
            response.parameters["backend"].string_param = result.backend
            response.parameters["model"].string_param = result.model

            logger.debug(
                f"ModelInfer: {model_name} completed in {latency_ms:.1f}ms "
                f"({result.output_tokens} tokens)"
            )

            return response

        except Exception as e:
            logger.error(f"ModelInfer error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return ModelInferResponse(model_name=model_name, id=request.id)
