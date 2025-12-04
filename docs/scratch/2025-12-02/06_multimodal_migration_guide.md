# Multimodal Embeddings Migration Guide

**Date:** 2025-12-02
**Task:** Migrate from single-vector (sentence-transformers) to multi-vector (ColQwen2.5) embeddings

## Summary

Gaius now supports multimodal embeddings using ColQwen2.5 (7B params), enabling unified text+image search across the knowledge base. This guide walks through migrating from the legacy single-vector system to the new multimodal system.

**Key benefits:**
- ✅ Unified text+image embedding space
- ✅ Better search quality (62.7 NDCG@5 on Vidore-v2)
- ✅ Safetensors only (no `trust_remote_code` needed)
- ✅ Cross-modal search (text query → find images)

**Trade-offs:**
- 10x slower embedding (5-30 min for 1K-5K docs)
- 2-5x slower search latency
- 30x larger storage (~250-500MB for 5K docs)
- Requires 7GB VRAM (with fp16)

---

## Prerequisites

### 1. Check VRAM Availability

ColQwen2.5 requires ~7GB VRAM with fp16 precision:

```bash
nvidia-smi
```

Look for "Memory-Usage" - you need at least 7GB free on one GPU.

### 2. Install Multimodal Dependencies

```bash
# Install multimodal extra dependencies
uv sync --extra multimodal

# This installs:
# - colpali-engine >= 0.3.0  (ColQwen2.5 model)
# - Pillow >= 10.0.0          (image loading)
# - pypdf >= 3.0.0            (PDF extraction - optional)
# - torch >= 2.0.0            (PyTorch for ColQwen)
# - transformers >= 4.40.0    (HuggingFace models)
```

Verify installation:

```bash
uv run python -c "from colpali_engine.models import ColQwen2_5; print('ColQwen OK')"
```

### 3. Backup Current State (Optional)

```bash
# Backup existing cache
cp -r build/dev/.cache build/dev/.cache.backup

# Backup Qdrant data (if running locally)
# docker exec qdrant tar -czf /qdrant/backups/pre-migration.tar.gz /qdrant/storage
```

---

## Migration Steps

### Step 1: Update Configuration

Edit `config/base.conf`:

```hocon
vector_store {
  # ... existing settings ...

  # CHANGE THIS: Switch to multimodal embeddings
  embedding_type = "multi"  # Was "single"

  # Multimodal settings automatically used when embedding_type = "multi"
  multimodal {
    model = "nomic-ai/colnomic-embed-multimodal-7b"
    model_revision = "main"  # Pin to commit hash in production
    aggregation = "mean"  # For grid projection (UMAP/TDA)
    batch_size = 4  # Small batch for 7B model (adjust for VRAM)
    use_fp16 = true  # Reduce VRAM: 14GB → 7GB
  }
}
```

**Production recommendation:** Pin `model_revision` to a specific commit:

```bash
# Find latest commit hash
curl -s https://huggingface.co/api/models/nomic-ai/colnomic-embed-multimodal-7b | \
  jq -r '.siblings[] | select(.rfilename == "model.safetensors") | .oid'

# Example:
# model_revision = "a1b2c3d4e5f6..."
```

### Step 2: Clear Cache

The cache is automatically invalidated when `embedding_type` changes, but you can manually clear it:

```bash
rm -rf build/dev/.cache
```

### Step 3: Run Reindex

The existing `/reindex` command automatically detects the new config and uses ColQwen:

```bash
# In the TUI:
# Press `/` then type `reindex` and press Enter

# Or via CLI:
uv run gaius-cli --cmd "/reindex"
```

**Progress tracking:**
- The TUI shows live progress in ThinkPanel (press `g` to toggle)
- 4 steps: Load embeddings → Project to grid → Compute TDA → Save cache
- **Estimated time:** 5-30 minutes for 1K-5K documents

### Step 4: Verify Migration

After `/reindex` completes:

1. **Check collection info:**
   ```bash
   uv run gaius-cli --cmd "/state" --format json | jq '.vector_store'
   ```

   Expected output:
   ```json
   {
     "name": "gaius_kb_multi",
     "points_count": <number of chunks>,
     "embedding_type": "multi"
   }
   ```

2. **Test cross-modal search:**
   - In TUI: press `/` then `search cute animals` → should find both text and images
   - Look for `content_type: "image"` in results

3. **Check grid projection:**
   - Grid should show real data (not static fallback)
   - Press `v` to cycle view modes, `o` to cycle overlays

4. **Verify TDA features:**
   - Press `/` then `state` to see TDA stats (H0/H1/H2 counts)

---

## Rollback Procedure

If you need to rollback to single-vector embeddings:

### Option 1: Quick Rollback (5 minutes)

```bash
# 1. Update config
# Edit config/base.conf:
# embedding_type = "single"

# 2. Clear cache
rm -rf build/dev/.cache

# 3. Reindex with single-vector
uv run gaius-cli --cmd "/reindex"
```

The router automatically switches back to sentence-transformers based on config.

### Option 2: Swap Qdrant Collections (instant)

If you kept the old collection (`gaius_kb`):

```bash
# 1. Update config to "single"
# 2. Manually rename collections in Qdrant
# (requires Qdrant API calls or web UI)
# 3. Delete cache
rm -rf build/dev/.cache
# 4. Restart app
```

---

## Testing Recommendations

### 1. Smoke Test

```bash
# Test text search
uv run gaius-cli --cmd "/search query text" --format json

# Test grid projection
uv run gaius-cli --cmd "/state" --format json | jq '.grid'
```

### 2. Performance Benchmarks

```bash
# Measure search latency
time uv run gaius-cli --cmd "/search test query"

# Check VRAM usage during embedding
nvidia-smi dmon -s u -d 1
```

Expected metrics:
- Search latency: 20-50ms (was 5-10ms)
- Embedding throughput: 10-20 docs/sec (was ~100 docs/sec)
- VRAM: ~7GB (fp16)

### 3. Quality Assessment

Compare search results before/after migration:

```bash
# Before (single-vector)
embedding_type = "single"
# Run searches, note top-5 results

# After (multi-vector)
embedding_type = "multi"
# Run same searches, compare relevance
```

---

## Troubleshooting

### Issue: "colpali-engine not installed"

**Solution:**
```bash
uv sync --extra multimodal
# Or install individually:
uv pip install colpali-engine>=0.3.0
```

### Issue: "CUDA out of memory"

**Symptoms:** OOM error during embedding or search

**Solutions:**
1. Reduce batch size in config:
   ```hocon
   multimodal { batch_size = 2 }  # Was 4
   ```

2. Use int8 quantization (trade quality for memory):
   ```python
   # In colqwen.py, modify:
   # dtype = torch.qint8  # Instead of bfloat16
   ```

3. Upgrade GPU or use CPU (slow):
   ```python
   # In colqwen.py:
   # device = "cpu"
   ```

### Issue: Reindex taking too long

**Symptoms:** `/reindex` running >1 hour

**Diagnosis:**
```bash
# Check progress
nvidia-smi  # VRAM usage should be ~7GB
htop        # CPU usage should be low (GPU-bound)
```

**Solutions:**
- Reduce KB size temporarily
- Index in multiple passes (manual batching)
- Consider using faster model (smaller ColQwen variant)

### Issue: Search results worse than before

**Symptoms:** Lower quality results with multi-vector

**Solutions:**
1. Check aggregation method:
   ```hocon
   aggregation = "mean"  # Try "max" if "mean" not working
   ```

2. Enable MaxSim search (should be default):
   ```python
   # In vector_multi.py search():
   use_maxsim = True
   ```

3. Compare with aggregated vector search:
   ```python
   use_maxsim = False  # Fallback to cosine
   ```

### Issue: Grid projection looks strange

**Symptoms:** All points clustered, poor separation

**Solutions:**
1. Verify aggregation is working:
   ```python
   # Check embeddings are 128-dim, not multi-vector
   print(embeddings.shape)  # Should be (n, 128)
   ```

2. Try different aggregation:
   ```hocon
   aggregation = "first"  # Or "max"
   ```

3. Check UMAP parameters (shouldn't need changes):
   ```python
   # projection.py: n_neighbors=15, min_dist=0.1
   ```

---

## Performance Tuning

### Optimize Batch Size for Your GPU

```bash
# Test different batch sizes
for bs in 2 4 8; do
  # Edit config: batch_size = $bs
  echo "Testing batch_size=$bs"
  time uv run gaius-cli --cmd "/reindex"
  nvidia-smi
done
```

Pick the largest batch size that doesn't OOM.

### Reduce Index Time with Subsampling

For development, temporarily reduce KB size:

```bash
# Only index "current" dir (skip archive/scratch)
# Edit vector_multi.py:
# ALLOWED_DIRS = ("current",)
```

### Cache Search Results

For frequently accessed queries, add caching:

```python
# In vector_multi.py:
from functools import lru_cache

@lru_cache(maxsize=128)
def search(self, query: str, ...):
    # ... existing search logic
```

---

## Architecture Notes

### Dual-Vector Storage

Qdrant stores **both** representations per document:

1. **"multi" vectors:** (n_tokens × 128) - stored in payload as base64
   - Used for MaxSim late-interaction search
   - Better relevance than single-vector

2. **"agg" vector:** (128,) - stored as named vector
   - Mean-pooled from multi-vectors
   - Used for UMAP projection and TDA
   - Maintains grid topology quality

### Router Pattern

`src/gaius/inference/search/vector.py` routes based on config:

```python
embedding_type = config.vector_store.embedding_type

if embedding_type == "multi":
    return VectorSearchMulti()  # ColQwen
else:
    return VectorSearch()       # sentence-transformers
```

This allows seamless switching via config.

### Cache Invalidation

Cache metadata tracks `embedding_type`:

```json
{
  "version": "1.0",
  "embedding_model": "nomic-ai/colnomic-embed-multimodal-7b",
  "embedding_type": "multi",
  "projection_method": "umap"
}
```

Changing `embedding_type` automatically invalidates cache.

---

## Next Steps

After successful migration:

1. **Index images:** Add `.png`, `.jpg` files to KB
   ```bash
   cp diagrams/*.png build/dev/current/images/
   uv run gaius-cli --cmd "/reindex"
   ```

2. **Test cross-modal search:**
   ```bash
   /search "diagram showing architecture"
   # Should find both text descriptions AND image files
   ```

3. **Benchmark quality:** Compare search results on your domain-specific queries

4. **Optimize:** Tune `batch_size` and `aggregation` for your use case

5. **Monitor:** Track VRAM usage and search latency in production

---

## References

- [ColQwen2.5 Model Card](https://huggingface.co/nomic-ai/colnomic-embed-multimodal-7b)
- [ColPali Engine Docs](https://github.com/illuin-tech/colpali)
- [Qdrant Named Vectors](https://qdrant.tech/documentation/concepts/vectors/#named-vectors)
- [UMAP Documentation](https://umap-learn.readthedocs.io/)

## Support

Issues? Questions?

- Check troubleshooting section above
- Review `docs/scratch/2025-12-02/05_model_security_safetensors.md` for security notes
- Inspect logs: ThinkPanel shows reasoning traces
- Rollback if needed (see Rollback Procedure above)
