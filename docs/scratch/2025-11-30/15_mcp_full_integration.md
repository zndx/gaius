# MCP Full Integration

Extended the Gaius MCP server to expose all major functionality, enabling Claude Code to fully drive Gaius.

## MCP Tools Summary (27 total)

### KB Operations (6 tools)
| Tool | Description |
|------|-------------|
| `search_kb` | Search KB by filename/content |
| `read_kb` | Read KB entry |
| `create_kb` | Create new KB entry |
| `update_kb` | Update existing entry |
| `delete_kb` | Delete KB entry |
| `list_kb` | List KB entries |

### Inference (3 tools)
| Tool | Description |
|------|-------------|
| `ask_local` | Query local LLM via optillm |
| `ask_reasoning` | Query QwQ-32B for complex analysis |
| `web_search` | Brave API web search |

### Research (2 tools)
| Tool | Description |
|------|-------------|
| `research_topic` | Search + synthesize to KB |
| `semantic_search` | Vector similarity search |

### Model Library (2 tools)
| Tool | Description |
|------|-------------|
| `list_models` | List available models (filter by capability) |
| `get_model` | Get best model for task type |

### Embeddings (2 tools)
| Tool | Description |
|------|-------------|
| `embed_text` | Generate text embedding (768-dim) |
| `embed_texts` | Batch text embeddings |

### Evaluation (1 tool)
| Tool | Description |
|------|-------------|
| `evaluate_output` | Frontier model (xAI Grok) evaluation |

### Agent Versioning (5 tools)
| Tool | Description |
|------|-------------|
| `list_agent_versions` | Version history for agent |
| `get_active_config` | Current agent configuration |
| `get_best_agent_version` | Best performing version |
| `rollback_agent` | Rollback to previous version |
| `save_agent_version` | Save new agent version |

### Optimization (1 tool)
| Tool | Description |
|------|-------------|
| `optimize_agent` | Run APO/GEPA optimization |

### Activity & Summary (3 tools)
| Tool | Description |
|------|-------------|
| `log_activity` | Record activity event |
| `get_activity_stats` | Activity statistics |
| `get_daily_summary` | Generate/retrieve daily summary |

### Swarm (1 tool)
| Tool | Description |
|------|-------------|
| `run_swarm` | Execute swarm analysis |

### TDA (1 tool)
| Tool | Description |
|------|-------------|
| `compute_tda` | Topological data analysis on embeddings |

## Claude Code Configuration

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "gaius": {
      "command": "uv",
      "args": ["run", "gaius-mcp"],
      "cwd": "/path/to/gaius",
      "env": {
        "BRAVE_API_KEY": "...",
        "XAI_API_KEY": "...",
        "OPENAI_API_KEY": "...",
        "GAIUS_KB_ROOT": "build/dev"
      }
    }
  }
}
```

## Example Usage from Claude Code

```
# Research a topic and save to KB
mcp__gaius__research_topic(topic="pension glide paths", domain="pension")

# Run swarm analysis
mcp__gaius__run_swarm(query="optimal asset allocation strategy", domain="pension")

# Get reasoning from QwQ-32B
mcp__gaius__ask_reasoning(question="Analyze the implications of increasing equity allocation for young participants")

# Evaluate output
mcp__gaius__evaluate_output(
    output="...",
    task_prompt="...",
    dimensions="accuracy,coherence,relevance"
)

# Optimize an agent
mcp__gaius__optimize_agent(
    agent_id="leader",
    examples='[{"input_prompt": "...", "expected_output": "..."}]',
    strategy="gepa"
)

# Version control
mcp__gaius__list_agent_versions(agent_id="leader")
mcp__gaius__rollback_agent(agent_id="leader", version_id="leader-abc123")
```

## Capabilities Enabled

From Claude Code, you can now:

1. **Research & Learn** - Search web, synthesize to KB, semantic search
2. **Analyze** - Run swarm with multiple perspectives, use reasoning model
3. **Evaluate** - Get frontier model feedback on outputs
4. **Optimize** - Run APO/GEPA to improve agent prompts
5. **Version Control** - Save/rollback agent configurations
6. **Track Activity** - Log events, generate summaries
7. **Compute** - TDA on embeddings, generate vectors

This enables a complete "outer loop" workflow where Claude Code orchestrates Gaius agents, evaluates results, and iteratively improves the system.
