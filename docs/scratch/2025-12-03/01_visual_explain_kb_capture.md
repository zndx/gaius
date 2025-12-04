# Visual-First Explain with KB Capture

## Summary

Enhanced `/explain` command to focus on visual relationships between orthographic views and capture results as zettelkasten KB documents with mini-grid Unicode visuals.

## New Features

### Visual-First Hybrid Explanations

The prompt now prioritizes visual descriptions over raw metrics:

1. **Visual descriptions** of Embed and Iso views (what user SEES)
2. **View relationship analysis** correlating both views at cursor position
3. **Metrics for scientific context** (curvature, TDA entropy, risk scores)

### KB Capture

New `--save` flag persists explanations as experimental records:

```bash
/explain K10 --save       # CLI
/explain --save           # TUI (uses cursor position)
explain_grid_position(x=9, y=9, save=True)  # MCP
```

**Document format:**
- YAML frontmatter with all metadata
- Unicode mini-grid visualizations (Embed + Iso views)
- Geometric and topological feature tables
- LLM interpretation

**File naming:** `scratch/YYYY-MM-DD/NN_explain_POSITION.md`

## Files Created/Modified

| File | Change |
|------|--------|
| `src/gaius/core/kb_capture.py` | NEW: ExplainCapture, serialize_minigrid, get_next_sequence |
| `src/gaius/inference/llm.py` | Visual description helpers, hybrid prompt, embed_grid/iso_grid fields |
| `src/gaius/cli.py` | `--save` flag, KB capture integration |
| `src/gaius/app.py` | `--save` flag, position argument parsing |
| `src/gaius/mcp_server.py` | `save` parameter for explain_grid_position |

## Visual Pattern Reference

| Embed + Iso | Interpretation |
|-------------|----------------|
| Bright + Low | Cluster core - stable territory |
| Bright + High | Bridge point - gateway between topics |
| Dim + Low | Empty field - unexplored space |
| Dim + High | Frontier ridge - major boundary |

## Testing

```bash
# CLI
uv run gaius-cli --cmd "/explain K10 --save" --format json

# MCP (after restart)
explain_grid_position(x=9, y=9, save=True)
```

## Sample Output

The explanation now uses visual language:
> "The territory is a **cluster core**—a dense, stable semantic valley floor (low Iso elevation) surrounded by brightly glowing, semantically similar documents in the Embed view..."
