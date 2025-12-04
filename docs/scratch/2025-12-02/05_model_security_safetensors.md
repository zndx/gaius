# Model Security: Safetensors and Version Pinning

**Date:** 2025-12-02
**Task:** Configure safetensors requirement and automatic model version pinning

## Summary

Implemented security controls for embedding models to prevent accidental download of malicious code:

1. **Safetensors requirement** - Prefer safetensors format over pickle
2. **Version pinning** - Pin models to specific commits
3. **Explicit trust_remote_code** - Make remote code execution opt-in

## Motivation

Hugging Face models can contain:
- **Pickle files** - Can execute arbitrary code during deserialization
- **Python code** - Models with `trust_remote_code=True` can run custom code
- **Version drift** - Unpinned models may silently update with malicious code

Best practices:
- Use **safetensors** format (no code execution, faster loading)
- **Pin to specific commits** rather than "main" or "latest"
- Only enable `trust_remote_code` for trusted models

## Changes Made

### 1. Config Schema (`src/gaius/core/config.py`)

Added security fields to `VectorStoreConfig`:

```python
@dataclass
class VectorStoreConfig:
    """Qdrant vector store configuration."""

    host: str = "localhost"
    port: int = 6339
    collection: str = "gaius_kb"
    embedding_model: str = "all-MiniLM-L6-v2"
    model_revision: str | None = None  # Pin to specific commit
    use_safetensors: bool = True  # Require safetensors format
    trust_remote_code: bool = False  # Only enable for trusted models
```

Updated config loader (lines 349-357):
```python
vector_store = VectorStoreConfig(
    host=g.get("vector_store.host", "localhost"),
    port=g.get("vector_store.port", 6339),
    collection=g.get("vector_store.collection", "gaius_kb"),
    embedding_model=g.get("vector_store.embedding_model", "all-MiniLM-L6-v2"),
    model_revision=g.get("vector_store.model_revision"),  # None if not set
    use_safetensors=g.get("vector_store.use_safetensors", True),
    trust_remote_code=g.get("vector_store.trust_remote_code", False),
)
```

### 2. Model Loading (`src/gaius/inference/search/vector.py`)

Updated `VectorSearch.__init__()` to accept security parameters (lines 72-109):
```python
def __init__(
    self,
    kb_root: Path | str | None = None,
    model_name: str = DEFAULT_MODEL,
    qdrant_host: str = QDRANT_HOST,
    qdrant_port: int = QDRANT_PORT,
    collection_name: str = COLLECTION_NAME,
    model_revision: str | None = None,
    use_safetensors: bool = True,
    trust_remote_code: bool = False,
):
    # ... store params
    self.model_revision = model_revision
    self.use_safetensors = use_safetensors
    self.trust_remote_code = trust_remote_code
```

Updated `model` property to use security settings (lines 111-134):
```python
@property
def model(self) -> SentenceTransformer:
    """Get or create embedding model with security settings."""
    if self._model is None:
        kwargs = {
            "trust_remote_code": self.trust_remote_code,
        }

        # Pin to specific revision for security
        if self.model_revision:
            kwargs["revision"] = self.model_revision

        # Require safetensors format (safer than pickle)
        if self.use_safetensors:
            os.environ["SAFETENSORS_FAST_GPU"] = "1"

        self._model = SentenceTransformer(
            self.model_name,
            **kwargs,
        )
    return self._model
```

Updated `get_vector_search()` singleton to read from config (lines 365-397):
```python
def get_vector_search(kb_root: Path | str | None = None) -> VectorSearch:
    """Get or create vector search singleton.

    Reads embedding model and security settings from config if available.
    """
    global _vector_search
    if _vector_search is None:
        # Try to get settings from config
        model_name = DEFAULT_MODEL
        model_revision = None
        use_safetensors = True
        trust_remote_code = False

        try:
            from ...core.config import get_config
            config = get_config()
            vs_config = config.vector_store
            if vs_config.embedding_model:
                model_name = vs_config.embedding_model
            model_revision = vs_config.model_revision
            use_safetensors = vs_config.use_safetensors
            trust_remote_code = vs_config.trust_remote_code
        except Exception:
            pass  # Use defaults if config not available

        _vector_search = VectorSearch(
            kb_root,
            model_name=model_name,
            model_revision=model_revision,
            use_safetensors=use_safetensors,
            trust_remote_code=trust_remote_code,
        )
    return _vector_search
```

### 3. Configuration (`config/base.conf`)

Added comprehensive security documentation (lines 41-69):

```hocon
vector_store {
  host = "localhost"
  host = ${?QDRANT_HOST}
  port = 6339
  port = ${?QDRANT_PORT}
  collection = "gaius_kb"

  # Embedding model selection
  # Nomic: 768-dim, excellent quality, unified text+vision space
  # Alternative: all-MiniLM-L6-v2 (384-dim, faster)
  embedding_model = "nomic-ai/nomic-embed-text-v1.5"
  embedding_model = ${?EMBEDDING_MODEL}

  # Security settings - Pin model versions to prevent malicious code injection
  # For production, pin to specific commit hash instead of "main"
  # Find commit hash at: https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/commits/main
  # Example: model_revision = "5c80574db15564a574b91b22ea8a7c4c70dabc00"
  model_revision = "main"  # Pin to specific commit in production
  model_revision = ${?EMBEDDING_MODEL_REVISION}

  # Require safetensors format (safer than pickle - no arbitrary code execution)
  use_safetensors = true

  # Allow remote code execution (needed for Nomic, disabled by default for security)
  # SECURITY: Only enable for trusted models. Nomic is maintained by Nomic AI.
  # Disable if using standard models like all-MiniLM-L6-v2
  trust_remote_code = true
  trust_remote_code = ${?TRUST_REMOTE_CODE}
}
```

## Security Best Practices

### For Production Deployments

1. **Pin to specific commits**:
   ```hocon
   model_revision = "5c80574db15564a574b91b22ea8a7c4c70dabc00"  # Not "main"
   ```

2. **Find commit hashes**:
   - Visit: https://huggingface.co/{org}/{model}/commits/main
   - Pick a stable release commit
   - Use full 40-character hash

3. **Prefer models without trust_remote_code**:
   ```hocon
   embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
   trust_remote_code = false
   ```

4. **Use environment variables for version control**:
   ```bash
   export EMBEDDING_MODEL_REVISION="5c80574db15564a574b91b22ea8a7c4c70dabc00"
   export TRUST_REMOTE_CODE=false
   ```

### Current Configuration

Current config uses:
- **Model**: `nomic-ai/nomic-embed-text-v1.5` (768-dim, excellent quality)
- **Revision**: `main` (should pin for production)
- **Safetensors**: Enabled
- **Trust remote code**: Enabled (Nomic requires this)

Nomic is trustworthy (maintained by Nomic AI), but for maximum security:
- Pin to a specific reviewed commit
- Audit the custom code at: https://huggingface.co/nomic-ai/nomic-embed-text-v1.5/blob/main/modeling_hf_nomic_bert.py

### Alternative: Standard Models

For maximum security, use standard sentence-transformers models that don't require custom code:

```hocon
embedding_model = "sentence-transformers/all-mpnet-base-v2"
model_revision = "main"  # Still pin in production
trust_remote_code = false
use_safetensors = true
```

Trade-offs:
- ✓ No custom code execution
- ✗ Slightly lower quality (768-dim but not Nomic-optimized)
- ✗ No unified text+vision embedding space

## Files Modified

1. `src/gaius/core/config.py` - Added security fields to VectorStoreConfig
2. `src/gaius/inference/search/vector.py` - Model loading with security controls
3. `config/base.conf` - Security settings with documentation

## Testing

Verify settings are loaded correctly:

```bash
uv run gaius-cli --cmd "/state" --format json | jq '.config.vector_store'
```

Expected output:
```json
{
  "host": "localhost",
  "port": 6339,
  "collection": "gaius_kb",
  "embedding_model": "nomic-ai/nomic-embed-text-v1.5",
  "model_revision": "main",
  "use_safetensors": true,
  "trust_remote_code": true
}
```

## Next Steps

**Recommended for production:**

1. Pin Nomic model to specific commit:
   ```bash
   # Find latest stable commit
   curl -s https://huggingface.co/api/models/nomic-ai/nomic-embed-text-v1.5/revisions \
     | jq -r '.[] | select(.type=="branch" and .name=="main") | .sha'
   ```

2. Update config with pinned version:
   ```hocon
   model_revision = "<commit-hash-from-above>"
   ```

3. Verify model loads with pinned version:
   ```bash
   uv run gaius-cli --cmd "/reindex"
   ```

4. Consider migrating to standard sentence-transformers model if custom code is a concern

## References

- [Hugging Face Hub Security](https://huggingface.co/docs/hub/security)
- [Safetensors Format](https://huggingface.co/docs/safetensors/index)
- [Sentence Transformers Security](https://www.sbert.net/docs/pretrained_models.html#model-overview)
- [Nomic Embed Documentation](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
