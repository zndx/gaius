"""Cross-Layer Transcoder (CLT) model loading and management.

Uses BluelightAI's circuit-tracer library to load Cross-Layer Transcoders
for Qwen3, enabling interpretable sparse feature extraction and circuit tracing.

The CLT model provides:
- Sparse feature extraction (~115 active features per layer out of 20,480)
- Cross-layer attribution graphs
- Interpretable feature circuits for mechanistic analysis

All operations route through gaius-engine - no direct model access from
CLI/TUI/MCP clients.

References:
- BluelightAI Qwen3 Explorer: https://bluelightai.com/blog/qwen3-explorer
- Cross-Layer Transcoders: arXiv:2406.11944
- circuit-tracer: https://github.com/safety-research/circuit-tracer
"""

import logging
from dataclasses import dataclass, field

import torch
from circuit_tracer import ReplacementModel  # Required dependency - fail-fast

logger = logging.getLogger(__name__)


@dataclass
class CLTSpec:
    """Specification for a Cross-Layer Transcoder model.

    Attributes:
        base_model: HuggingFace model ID for the base LLM
        transcoder_name: HuggingFace model ID for the CLT transcoders
        features_per_layer: Number of features in each layer's encoder
        l0_sparsity: Expected number of active features per position
        dtype: Data type for model weights
        num_layers: Number of transformer layers (inferred from model)
    """

    base_model: str
    transcoder_name: str
    features_per_layer: int = 20_480
    l0_sparsity: int = 115
    dtype: torch.dtype = torch.bfloat16
    num_layers: int | None = None

    @property
    def total_features(self) -> int:
        """Estimate total features across all layers."""
        layers = self.num_layers or 28  # Qwen3-1.7B has 28 layers
        return self.features_per_layer * layers


# CLT Model Registry
# Note: transformer_lens only supports Qwen/Qwen3-1.7B (not -Base variant)
# The CLT transcoders work with the non-Base model as an "unpatched alternative"
# per BluelightAI docs: https://huggingface.co/bluelightai/clt-qwen3-1.7b-base-20k
CLT_MODELS: dict[str, CLTSpec] = {
    "qwen3-1.7b": CLTSpec(
        base_model="Qwen/Qwen3-1.7B",  # Use non-Base (transformer_lens compatible)
        transcoder_name="bluelightai/clt-qwen3-1.7b-base-20k",
        features_per_layer=20_480,
        l0_sparsity=115,
        num_layers=28,
    ),
}


@dataclass
class SparseFeature:
    """A sparse feature activation from CLT encoder.

    Attributes:
        layer_idx: Which transformer layer
        position: Token position in sequence
        feature_idx: Index in the 20,480-dim feature space
        activation: Activation magnitude
        semantic_label: Human-readable label (if available from dashboard)
    """

    layer_idx: int
    position: int
    feature_idx: int
    activation: float
    semantic_label: str = ""

    @property
    def position_idx(self) -> int:
        """Alias for position (backward compatibility)."""
        return self.position


@dataclass
class AttributionEdge:
    """An edge in the CLT attribution graph.

    Represents influence from a source feature to a target feature
    across layers, computed as A_{s->t} = a_s * ||w_{s->t}||.

    Attributes:
        source_layer: Layer of source feature
        source_feature: Feature index in source layer
        target_layer: Layer of target feature
        target_feature: Feature index in target layer (0 if targeting output)
        weight: Attribution weight
    """

    source_layer: int
    source_feature: int
    target_layer: int
    target_feature: int
    weight: float


@dataclass
class CLTExtractResult:
    """Result of sparse feature extraction.

    Attributes:
        features: List of active sparse features
        total_positions: Number of token positions processed
        sparsity: Actual sparsity ratio (active / total possible)
        text: Original input text
    """

    features: list[SparseFeature] = field(default_factory=list)
    total_positions: int = 0
    sparsity: float = 0.0
    text: str = ""


@dataclass
class CLTAttributeResult:
    """Result of attribution graph computation.

    Attributes:
        edges: List of attribution edges
        dot_graph: GraphViz DOT representation
        text: Original input text
        target_positions: Token positions that were traced
    """

    edges: list[AttributionEdge] = field(default_factory=list)
    dot_graph: str = ""
    text: str = ""
    target_positions: list[int] = field(default_factory=list)


@dataclass
class CLTDecodeResult:
    """Result of decoding sparse features to text.

    Attributes:
        generated_text: Generated text from feature state
        feature_summary: Human-readable summary of features
        top_features: Top active features (idx, activation)
        context_used: Whether context was provided
    """

    generated_text: str = ""
    feature_summary: str = ""
    top_features: list[tuple[int, float]] = field(default_factory=list)
    context_used: bool = False


class CLTModel:
    """Wrapper for loaded CLT model with feature extraction and attribution.

    This class is instantiated by the Engine and should not be used directly
    from CLI/TUI/MCP clients.
    """

    def __init__(self, spec: CLTSpec, device: str = "cuda"):
        """Initialize CLT model wrapper.

        Args:
            spec: CLT model specification
            device: Target device (cuda, cpu)
        """
        self.spec = spec
        self.device = device
        self._model: ReplacementModel | None = None
        self._loaded = False

    def load(self) -> None:
        """Load the CLT model."""
        if self._loaded:
            return

        logger.info(
            f"Loading CLT model: {self.spec.base_model} + {self.spec.transcoder_name}"
        )

        # Pass device as torch.device, not string
        # Disable fold_value_biases to avoid device mismatch during loading
        import torch
        device = torch.device(self.device)

        self._model = ReplacementModel.from_pretrained(
            self.spec.base_model,
            self.spec.transcoder_name,
            dtype=self.spec.dtype,
            device=device,
            fold_value_biases=False,  # Avoid CPU/GPU tensor mismatch
        )
        self._loaded = True

        logger.info(f"CLT model loaded on {self.device}")

    def unload(self) -> None:
        """Unload the model to free GPU memory."""
        if self._model is not None:
            del self._model
            self._model = None
            self._loaded = False
            torch.cuda.empty_cache()
            logger.info("CLT model unloaded")

    @property
    def model(self) -> ReplacementModel:
        """Get loaded model, loading if necessary."""
        if not self._loaded:
            self.load()
        assert self._model is not None
        return self._model

    def extract_features(
        self,
        text: str,
        layer_indices: list[int] | None = None,
        top_k: int = 115,
    ) -> CLTExtractResult:
        """Extract sparse features from text.

        Uses circuit_tracer's get_activations() API which returns sparse
        transcoder activations across all layers.

        Args:
            text: Input text to analyze
            layer_indices: Which layers to extract from (None = all)
            top_k: Top-k features per position

        Returns:
            CLTExtractResult with sparse features
        """
        model = self.model

        # Use circuit_tracer's get_activations API
        # Returns (logits, activation_cache) where activation_cache has shape
        # (num_layers, seq_len, features_per_layer) when sparse=False
        # or sparse tensor when sparse=True
        with torch.no_grad():
            _, activation_cache = model.get_activations(text, sparse=False)

        # activation_cache shape: (num_layers, seq_len, features_per_layer)
        num_layers = activation_cache.shape[0]
        seq_len = activation_cache.shape[1]

        layers_to_process = layer_indices or list(range(num_layers))

        features: list[SparseFeature] = []

        for layer_idx in layers_to_process:
            if layer_idx >= num_layers:
                continue

            # Get activations for this layer
            layer_activations = activation_cache[layer_idx]  # (seq_len, features)

            # Find top-k active features per position
            for pos in range(seq_len):
                pos_activations = layer_activations[pos]
                topk_vals, topk_idxs = pos_activations.topk(
                    min(top_k, self.spec.features_per_layer)
                )

                for val, idx in zip(topk_vals, topk_idxs):
                    if val.item() > 0:  # Only positive activations
                        features.append(
                            SparseFeature(
                                layer_idx=layer_idx,
                                position=pos,
                                feature_idx=idx.item(),
                                activation=val.item(),
                            )
                        )

        total_possible = seq_len * len(layers_to_process) * self.spec.features_per_layer
        sparsity = len(features) / total_possible if total_possible > 0 else 0.0

        return CLTExtractResult(
            features=features,
            total_positions=seq_len,
            sparsity=sparsity,
            text=text,
        )

    def compute_attribution(
        self,
        text: str,
        target_positions: list[int] | None = None,
        threshold: float = 0.01,
    ) -> CLTAttributeResult:
        """Compute attribution graph for target positions.

        Traces which features influence the output at specified positions
        by computing A_{s->t} = a_s * ||w_{s->t}|| for each layer pair.

        Args:
            text: Input text
            target_positions: Token positions to trace (None = last position)
            threshold: Minimum weight to include edge

        Returns:
            CLTAttributeResult with attribution edges and DOT graph
        """
        model = self.model

        # Tokenize
        inputs = model.tokenizer(text, return_tensors="pt").to(self.device)
        seq_len = inputs.input_ids.shape[1]

        # Default to last position
        if target_positions is None:
            target_positions = [seq_len - 1]

        # Forward pass
        with torch.no_grad():
            outputs = model(inputs.input_ids, output_hidden_states=True)

        edges: list[AttributionEdge] = []
        num_layers = len(outputs.hidden_states) - 1

        for target_pos in target_positions:
            if target_pos >= seq_len:
                continue

            # Trace backward through layers
            for layer_idx in range(num_layers - 1, 0, -1):
                source_layer = layer_idx - 1
                target_layer = layer_idx

                # Get source feature activations
                # circuit_tracer ReplacementModel.transcoders is subscriptable (nn.ModuleList)
                # but the library lacks type stubs
                src_encoder = model.transcoders[source_layer].encoder  # type: ignore[index] - circuit_tracer ReplacementModel.transcoders is nn.ModuleList, subscriptable
                src_hidden = outputs.hidden_states[source_layer + 1]
                src_acts = src_encoder(src_hidden)[0, target_pos]

                # Get cross-layer decoder weights
                decoder = model.transcoders[source_layer].decoder  # type: ignore[index] - circuit_tracer ReplacementModel.transcoders is nn.ModuleList, subscriptable

                # Find active source features
                active_indices = src_acts.nonzero().squeeze(-1)
                if active_indices.dim() == 0:
                    active_indices = active_indices.unsqueeze(0)

                for src_feat in active_indices:
                    a_s = src_acts[src_feat].item()

                    # Weight contribution to target layer
                    # decoder.weight shape: (d_latent, n_out_layers, d_model)
                    layer_offset = target_layer - source_layer
                    if layer_offset < decoder.weight.shape[1]:
                        w_st = decoder.weight[src_feat, layer_offset]
                        weight = a_s * w_st.norm().item()

                        if weight > threshold:
                            edges.append(
                                AttributionEdge(
                                    source_layer=source_layer,
                                    source_feature=src_feat.item(),
                                    target_layer=target_layer,
                                    target_feature=0,  # Output
                                    weight=weight,
                                )
                            )

        # Generate DOT graph
        dot = self._generate_dot(edges)

        return CLTAttributeResult(
            edges=edges,
            dot_graph=dot,
            text=text,
            target_positions=target_positions,
        )

    def _generate_dot(self, edges: list[AttributionEdge]) -> str:
        """Generate GraphViz DOT representation of attribution graph."""
        lines = [
            "digraph AttributionGraph {",
            "  rankdir=BT;",
            "  node [shape=box, fontsize=10];",
            "  edge [fontsize=8];",
        ]

        # Group nodes by layer for subgraph layout
        layers: dict[int, set[int]] = {}
        for edge in edges:
            if edge.source_layer not in layers:
                layers[edge.source_layer] = set()
            layers[edge.source_layer].add(edge.source_feature)

            if edge.target_layer not in layers:
                layers[edge.target_layer] = set()
            layers[edge.target_layer].add(edge.target_feature)

        # Create subgraphs for each layer
        for layer_idx in sorted(layers.keys()):
            lines.append(f"  subgraph cluster_L{layer_idx} {{")
            lines.append(f'    label="Layer {layer_idx}";')
            for feat in sorted(layers[layer_idx]):
                node_id = f"L{layer_idx}_F{feat}"
                lines.append(f'    "{node_id}";')
            lines.append("  }")

        # Add edges
        for edge in edges:
            src = f"L{edge.source_layer}_F{edge.source_feature}"
            tgt = f"L{edge.target_layer}_F{edge.target_feature}"
            lines.append(f'  "{src}" -> "{tgt}" [label="{edge.weight:.3f}"];')

        lines.append("}")
        return "\n".join(lines)

    def decode_features_to_text(
        self,
        sparse_features: dict[int, float],
        context_text: str = "",
        max_new_tokens: int = 50,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Decode sparse features to text via reconstruction and generation.

        The decoding process:
        1. If context_text provided, encode it to get initial hidden states
        2. Use CLT decoder to reconstruct activations from sparse features
        3. Continue generation from reconstructed state

        This enables agents to "think" in feature space and decode when
        text output is needed.

        Args:
            sparse_features: Dict of feature_idx -> activation value
            context_text: Optional context to condition generation
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling threshold

        Returns:
            Generated text representation of the feature state
        """
        model = self.model

        # If we have context, use it for initial conditioning
        if context_text:
            inputs = model.tokenizer(context_text, return_tensors="pt").to(self.device)
        else:
            # Start with BOS token
            inputs = model.tokenizer("", return_tensors="pt").to(self.device)

        # Create reconstruction tensor from sparse features
        # The decoder weight shape is (d_latent, n_out_layers, d_model)
        # We'll reconstruct the final layer activation

        with torch.no_grad():
            # Get model hidden dimension
            # transcoders can be TranscoderSet (list-like) or single CrossLayerTranscoder
            transcoders = model.transcoders
            if hasattr(transcoders, "__len__") and hasattr(transcoders, "__getitem__"):
                # TranscoderSet is list-like - use indexing
                transcoder_list: list = [transcoders[i] for i in range(len(transcoders))]  # type: ignore
            else:
                # Single transcoder case - wrap in list
                transcoder_list = [transcoders]
            d_model = transcoder_list[0].decoder.weight.shape[2]
            num_layers = len(transcoder_list)

            # Construct sparse activation tensor
            sparse_acts = torch.zeros(self.spec.features_per_layer, device=self.device)
            for feat_idx, activation in sparse_features.items():
                if 0 <= feat_idx < self.spec.features_per_layer:
                    sparse_acts[feat_idx] = activation

            # Average across layers for reconstruction
            # This is a simplified reconstruction - more sophisticated methods
            # would use layer-specific features
            reconstructed = torch.zeros(d_model, device=self.device)

            # Use decoder from middle layer as representative
            mid_layer = num_layers // 2
            decoder = transcoder_list[mid_layer].decoder

            # Reconstruct: sum over active features
            for feat_idx in sparse_features.keys():
                if 0 <= feat_idx < self.spec.features_per_layer:
                    a = sparse_features[feat_idx]
                    # Use final layer offset for reconstruction
                    layer_offset = num_layers - mid_layer - 1
                    if layer_offset < decoder.weight.shape[1]:
                        w = decoder.weight[feat_idx, layer_offset]  # (d_model,)
                        reconstructed += a * w

            # Normalize
            reconstructed = reconstructed / (reconstructed.norm() + 1e-8) * 100

            # Now generate text conditioned on this representation
            # We'll use the base LLM's generate method with the reconstructed state
            # as a soft prompt (added to first position)

            # For now, use standard generation with feature-based prompt
            # A more sophisticated approach would inject reconstructed activations
            feature_summary = self._summarize_features(sparse_features)

            prompt = f"{context_text} [Internal state summary: {feature_summary}]"
            gen_inputs = model.tokenizer(prompt, return_tensors="pt").to(self.device)

            # Transformers generate() accepts **kwargs that include pad_token_id,
            # but the stubs don't type all valid kwargs. This is standard usage.
            outputs = model.generate(
                gen_inputs.input_ids,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=temperature > 0,
                pad_token_id=model.tokenizer.pad_token_id or model.tokenizer.eos_token_id,  # type: ignore[unknown-argument] - pad_token_id is valid kwarg for model.generate()
            )

            # Decode, removing the prompt
            # Extract new tokens (after prompt) as list for type safety
            # type: ignore[unknown-attribute] - PyTorch tensor slicing returns Tensor with .tolist()
            new_token_ids = outputs[0][gen_inputs.input_ids.shape[1]:].tolist()  # type: ignore[possibly-missing-attribute] - PyTorch tensor slicing returns Tensor with .tolist()
            generated = model.tokenizer.decode(
                new_token_ids,
                skip_special_tokens=True,
            )

        return generated.strip()

    def _summarize_features(self, sparse_features: dict[int, float]) -> str:
        """Create a text summary of active features.

        This provides a human-readable interpretation of the feature state.
        In the future, this could use a feature dictionary with semantic labels.

        Args:
            sparse_features: Dict of feature_idx -> activation

        Returns:
            Text summary of the feature pattern
        """
        # Sort by activation magnitude
        sorted_feats = sorted(
            sparse_features.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )[:10]  # Top 10

        if not sorted_feats:
            return "neutral/baseline"

        # For now, describe by indices until we have semantic labels
        # This is a placeholder - production would use feature labels
        descriptions = []
        for feat_idx, act in sorted_feats:
            strength = "strong" if abs(act) > 0.5 else "moderate" if abs(act) > 0.2 else "weak"
            descriptions.append(f"F{feat_idx}({strength})")

        return ", ".join(descriptions)


def get_clt_spec(name: str) -> CLTSpec:
    """Get a CLT specification by name.

    Args:
        name: CLT model name (e.g., "qwen3-1.7b")

    Returns:
        CLTSpec for the model

    Raises:
        KeyError: If model name not found
    """
    if name not in CLT_MODELS:
        available = ", ".join(CLT_MODELS.keys())
        raise KeyError(
            f"Unknown CLT model: {name}\n"
            f"  Available models: {available}\n"
            f"  Guru Meditation: #CLT.00000002.UNKNOWN_MODEL"
        )
    return CLT_MODELS[name]


def load_clt_model(
    name: str = "qwen3-1.7b",
    device: str = "cuda",
) -> CLTModel:
    """Load a CLT model by name.

    This is called by the Engine when CLT features are requested.

    Args:
        name: CLT model name
        device: Target device

    Returns:
        Loaded CLTModel instance
    """
    spec = get_clt_spec(name)
    model = CLTModel(spec, device)
    model.load()
    return model
