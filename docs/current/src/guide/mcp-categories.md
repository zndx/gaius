# Tool Categories

The 163 MCP tools are organized by domain. Each tool maps to an internal service call and accepts JSON arguments.

## Health

Tools for system diagnostics, self-healing, and incident management.

| Tool | Purpose |
|------|---------|
| `health_observer_status` | Current observer daemon state |
| `health_observer_check` | Run health diagnostic across all categories |
| `health_observer_start` / `stop` | Control the health observer daemon |
| `health_observer_incidents` | List active and recent incidents |
| `health_observer_incident_detail` | Detailed view of a specific incident |
| `fmea_catalog` | Browse failure modes and their RPN scores |
| `fmea_calculate_rpn` | Calculate Risk Priority Number for a failure mode |
| `fmea_get_controls` | Get remediation controls for a failure mode |

## Agents and Evolution

Tools for managing agent versions, evolution cycles, and cognition.

| Tool | Purpose |
|------|---------|
| `list_agent_versions` | All agent versions with metadata |
| `get_active_config` | Current active agent configuration |
| `get_best_agent_version` | Highest-performing version for an agent |
| `save_agent_version` / `rollback_agent` | Version management |
| `optimize_agent` | Trigger optimization for an agent |
| `evolution_status` | Current generation, evaluation state |
| `trigger_evolution` | Start a new evolution cycle |
| `trigger_task_ideation` | Generate new training tasks |
| `get_capability_gaps` | Identify areas where agents underperform |

## Inference and Models

Tools for managing LLM endpoints, inference scheduling, and XAI budget.

| Tool | Purpose |
|------|---------|
| `list_models` / `get_model` | Browse available models |
| `gpu_health` | GPU utilization and endpoint status |
| `model_launch_coding` / `model_stop_coding` | Control inference endpoints |
| `model_generate_code` | Generate code using a managed model |
| `model_validate_code` | Validate generated code |
| `get_xai_budget` / `reset_xai_budget` | Manage XAI inference budget |
| `evaluate_with_xai` | Run evaluation using XAI model |

## Knowledge Base

Tools for searching, reading, and managing knowledge base content.

| Tool | Purpose |
|------|---------|
| `search_kb` | Full-text search across KB entries |
| `read_kb` / `create_kb` / `update_kb` / `delete_kb` | CRUD operations |
| `list_kb` | List entries with filters |
| `kb_sync` | Synchronize KB with external sources |
| `semantic_search` | Vector similarity search |
| `embed_text` / `embed_texts` | Generate embeddings |

## Observability

Tools for metrics, monitoring, and system telemetry.

| Tool | Purpose |
|------|---------|
| `observe_status` / `observe_metrics` | Observability pipeline state |
| `prometheus_query` / `prometheus_query_range` | Direct PromQL queries |
| `prometheus_health` | Prometheus server status |
| `metabase_status` | Metabase analytics server status |
| `metabase_list_dashboards` / `metabase_get_dashboard` | Browse dashboards |
| `log_activity` / `get_activity_stats` / `get_daily_summary` | Activity tracking |

## Visualization

Tools for rendering card visualizations and managing collections.

| Tool | Purpose |
|------|---------|
| `collection_status` / `collection_list` / `collection_create` | Manage collections |
| `collection_add_card` / `collection_list_cards` | Card management |
| `collection_publish_cards` / `collection_publish_viz` | Publishing pipeline |
| `collection_generate_summaries` | AI-generated card summaries |
| `article_list` / `article_curate` / `article_new` | Article management |

## Bases (Feature Store)

Tools for querying the Bases feature store.

| Tool | Purpose |
|------|---------|
| `bases_list` | List available bases |
| `bases_query` | Run DQL queries against a base |
| `bases_entity_history` | Entity change history |
| `bases_health` | Feature store health status |

## Cognition and Memory

Tools for agent thinking, memory consolidation, and self-reflection.

| Tool | Purpose |
|------|---------|
| `trigger_cognition` | Trigger a cognition cycle |
| `trigger_self_observation` | Agent self-reflection |
| `get_thought_chain` / `get_recent_thoughts` | View agent reasoning |
| `what_are_you_thinking` | Current agent state of mind |
| `theta_sitrep` / `theta_consolidate` | Theta wave memory consolidation |
| `reflect` / `quick_thought` | Lightweight reflection tools |
