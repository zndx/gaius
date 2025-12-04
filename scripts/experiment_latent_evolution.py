#!/usr/bin/env python3
"""Experimentation script for LatentMAS + Agent0 features.

This script provides interactive examples for exploring:
1. Latent working memory (Qdrant-backed embeddings)
2. Evolution daemon (background self-improvement)
3. Latent swarm (two-phase execution)
4. Curriculum agent (task generation)

Usage:
    # Run all experiments
    uv run python scripts/experiment_latent_evolution.py

    # Run specific experiment
    uv run python scripts/experiment_latent_evolution.py --experiment latent
    uv run python scripts/experiment_latent_evolution.py --experiment evolution
    uv run python scripts/experiment_latent_evolution.py --experiment curriculum

    # Interactive mode
    uv run python scripts/experiment_latent_evolution.py --interactive
"""

import argparse
import asyncio
import json
import numpy as np
from datetime import datetime


async def experiment_latent_memory():
    """Experiment with latent working memory."""
    print("\n" + "=" * 60)
    print("EXPERIMENT: Latent Working Memory")
    print("=" * 60)

    from gaius.agents.latent import LatentWorkingMemory, LatentThought, get_latent_memory

    memory = get_latent_memory()
    print(f"\nConnected to: {memory.collection_name} @ {memory.host}:{memory.port}")

    # Create some test thoughts with different "meanings"
    print("\n--- Storing thoughts from different agents ---")

    # Simulate embeddings (in real use, these come from Nomic)
    # We'll create embeddings that are similar within topics
    def make_embedding(base_vector, noise=0.1):
        vec = base_vector + np.random.randn(768) * noise
        return (vec / np.linalg.norm(vec)).astype(np.float32)

    # Base vectors for different "topics"
    risk_base = np.random.randn(768)
    opportunity_base = np.random.randn(768)

    thoughts = [
        LatentThought.create(
            agent_role="risk",
            content="Market volatility poses significant downside risk to retirement portfolios",
            embedding=make_embedding(risk_base),
            domain="pension",
            metadata={"confidence": 0.85}
        ),
        LatentThought.create(
            agent_role="risk",
            content="Sequence of returns risk is critical in the decumulation phase",
            embedding=make_embedding(risk_base),
            domain="pension",
            metadata={"confidence": 0.9}
        ),
        LatentThought.create(
            agent_role="optimizer",
            content="Dynamic asset allocation can capture upside while limiting drawdowns",
            embedding=make_embedding(opportunity_base),
            domain="pension",
            metadata={"confidence": 0.75}
        ),
        LatentThought.create(
            agent_role="leader",
            content="A balanced approach combining risk management with growth opportunities",
            embedding=make_embedding((risk_base + opportunity_base) / 2),
            domain="pension",
            metadata={"confidence": 0.8}
        ),
    ]

    for thought in thoughts:
        await memory.store(thought)
        print(f"  Stored: [{thought.agent_role}] {thought.content_summary[:50]}...")

    # Retrieve similar thoughts
    print("\n--- Retrieving similar thoughts ---")
    query = make_embedding(risk_base, noise=0.05)  # Query similar to risk
    similar = await memory.retrieve_similar(
        query_embedding=query,
        limit=3,
        domain="pension"
    )
    print(f"Query: risk-like embedding")
    for i, t in enumerate(similar):
        print(f"  {i+1}. [{t.agent_role}] {t.content_summary[:60]}...")

    # Compute consensus
    print("\n--- Computing consensus embedding ---")
    consensus = await memory.get_consensus("pension")
    print(f"Consensus shape: {consensus.shape}, norm: {np.linalg.norm(consensus):.3f}")

    # Get stats
    stats = await memory.get_stats()
    print(f"\nCollection stats: {json.dumps(stats, indent=2)}")

    # Cleanup
    print("\n--- Cleaning up test domain ---")
    cleared = await memory.clear_domain("pension")
    print(f"Cleared {cleared} thoughts")

    return True


async def experiment_evolution_daemon():
    """Experiment with evolution daemon."""
    print("\n" + "=" * 60)
    print("EXPERIMENT: Evolution Daemon")
    print("=" * 60)

    from gaius.agents.evolution import (
        EvolutionDaemon,
        EvolutionConfig,
        get_evolution_daemon,
    )

    daemon = get_evolution_daemon()

    # Show current status
    print("\n--- Daemon Status ---")
    status = daemon.get_status()
    print(json.dumps(status, indent=2, default=str))

    # Show configuration
    print("\n--- Configuration ---")
    config = daemon.config
    print(f"  Enabled: {config.enabled}")
    print(f"  Idle threshold: {config.idle_threshold}%")
    print(f"  Poll interval: {config.poll_interval}s")
    print(f"  Strategy: {config.strategy}")
    print(f"  Agents: {config.agents}")
    print(f"  Min improvement: {config.min_improvement}%")

    # Test GPU idle detection
    print("\n--- GPU Idle Detection ---")
    is_idle = await daemon._gpus_are_idle()
    print(f"  GPUs idle: {is_idle}")

    # Test rate limiting
    print("\n--- Rate Limiting ---")
    is_limited = daemon._is_rate_limited()
    print(f"  Rate limited: {is_limited}")

    # Start daemon briefly
    print("\n--- Starting daemon (5 seconds) ---")
    await daemon.start()
    print(f"  Running: {daemon.running}")

    await asyncio.sleep(5)

    await daemon.stop()
    print(f"  Stopped: {not daemon.running}")

    # Show final status
    print("\n--- Final Status ---")
    status = daemon.get_status()
    print(f"  Cycles completed: {status['cycles_completed']}")
    print(f"  Next agent: {status['next_agent']}")

    return True


async def experiment_curriculum_agent():
    """Experiment with curriculum agent."""
    print("\n" + "=" * 60)
    print("EXPERIMENT: Curriculum Agent")
    print("=" * 60)

    from gaius.agents.evolution.curriculum import (
        CurriculumAgent,
        TaskCategory,
        TaskResult,
        get_curriculum_agent,
    )

    agent = get_curriculum_agent()

    # Show categories
    print("\n--- Task Categories ---")
    for cat in TaskCategory:
        print(f"  {cat.name}: {cat.value}")

    # Test difficulty computation
    print("\n--- Difficulty Computation ---")

    # Simulate different performance levels
    scenarios = [
        ("No history", []),
        ("High success (90%)", [
            TaskResult(task_id=str(i), success=i < 9, score=0.8 if i < 9 else 0.3, output="")
            for i in range(10)
        ]),
        ("Low success (40%)", [
            TaskResult(task_id=str(i), success=i < 4, score=0.8 if i < 4 else 0.3, output="")
            for i in range(10)
        ]),
        ("Target zone (70%)", [
            TaskResult(task_id=str(i), success=i < 7, score=0.8 if i < 7 else 0.3, output="")
            for i in range(10)
        ]),
    ]

    for name, results in scenarios:
        diff = agent._compute_target_difficulty(results)
        print(f"  {name}: difficulty = {diff:.2f}")

    # Generate default tasks
    print("\n--- Default Tasks (no LLM) ---")
    for cat in TaskCategory:
        task = agent._create_default_task(cat, 0.5)
        print(f"\n  [{cat.value}]")
        print(f"    Description: {task.description}")
        print(f"    Prompt: {task.input_prompt[:60]}...")

    # Try LLM-generated task (may fail without inference)
    print("\n--- LLM Task Generation (may skip if no LLM) ---")
    try:
        task = await agent.propose_task(
            executor_id="leader",
            recent_results=[],
            focus_category=TaskCategory.REASONING,
        )
        print(f"  Generated: {task.description}")
        print(f"  Difficulty: {task.difficulty}")
        print(f"  Prompt: {task.input_prompt[:100]}...")
    except Exception as e:
        print(f"  Skipped (no LLM available): {e}")

    return True


async def experiment_latent_swarm():
    """Experiment with latent swarm execution."""
    print("\n" + "=" * 60)
    print("EXPERIMENT: Latent Swarm Manager")
    print("=" * 60)

    from gaius.agents.swarm import (
        LatentSwarmManager,
        get_latent_swarm_manager,
        AgentRole,
    )
    from gaius.agents.latent import get_latent_memory

    manager = get_latent_swarm_manager()
    memory = get_latent_memory()

    # Show batch configuration
    print("\n--- Batch Configuration ---")
    print(f"  First batch (generate): {[r.value for r in manager.FIRST_BATCH_ROLES]}")
    all_roles = set(AgentRole)
    second_batch = all_roles - manager.FIRST_BATCH_ROLES
    print(f"  Second batch (retrieve): {[r.value for r in second_batch]}")

    # Show how two-phase execution works
    print("\n--- Two-Phase Execution Flow ---")
    print("""
    Phase 1: First batch agents run
             └─> Store thoughts as embeddings in Qdrant

    Phase 2: Build latent context from stored embeddings
             └─> Second batch agents run with context
             └─> Store their thoughts too

    Result: All agents have collaborated via latent space
            (70-90% fewer tokens than full text exchange)
    """)

    # Check latent memory stats
    print("\n--- Latent Memory Status ---")
    stats = await memory.get_stats()
    print(f"  Collection: {stats.get('collection', 'N/A')}")
    print(f"  Points: {stats.get('points_count', 0)}")
    print(f"  Status: {stats.get('status', 'unknown')}")

    # Note about running actual swarm
    print("\n--- Running Latent Swarm ---")
    print("  To run a full latent swarm (requires inference):")
    print("  ")
    print("    from gaius.agents import run_latent_swarm_round")
    print("    result = await run_latent_swarm_round(")
    print("        domain='pension analysis',")
    print("        context='Analyzing retirement portfolio strategies'")
    print("    )")
    print("  ")
    print("  Or via MCP tool:")
    print("    run_latent_swarm(query='...', domain='pension')")

    return True


async def interactive_mode():
    """Interactive REPL for experimentation."""
    print("\n" + "=" * 60)
    print("INTERACTIVE MODE")
    print("=" * 60)
    print("""
Available objects (already imported):
  - memory: LatentWorkingMemory instance
  - daemon: EvolutionDaemon instance
  - curriculum: CurriculumAgent instance
  - manager: LatentSwarmManager instance

Example commands:
  >>> await memory.get_stats()
  >>> daemon.get_status()
  >>> await daemon._gpus_are_idle()
  >>> curriculum._compute_target_difficulty([])

Type 'exit' or Ctrl+D to quit.
    """)

    from gaius.agents.latent import get_latent_memory
    from gaius.agents.evolution import get_evolution_daemon
    from gaius.agents.evolution.curriculum import get_curriculum_agent
    from gaius.agents.swarm import get_latent_swarm_manager

    memory = get_latent_memory()
    daemon = get_evolution_daemon()
    curriculum = get_curriculum_agent()
    manager = get_latent_swarm_manager()

    # Simple REPL
    import code
    local_vars = {
        'memory': memory,
        'daemon': daemon,
        'curriculum': curriculum,
        'manager': manager,
        'asyncio': asyncio,
        'np': np,
        'json': json,
    }

    # Use asyncio-aware REPL if available
    try:
        import aioconsole
        await aioconsole.aexec("pass", local=local_vars)
        print("Using aioconsole for async REPL")
    except ImportError:
        print("Note: Install aioconsole for async REPL support")
        print("      uv add aioconsole")
        code.interact(local=local_vars)


async def main():
    parser = argparse.ArgumentParser(
        description="Experiment with LatentMAS + Agent0 features"
    )
    parser.add_argument(
        "--experiment",
        choices=["latent", "evolution", "curriculum", "swarm", "all"],
        default="all",
        help="Which experiment to run"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enter interactive mode"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("LatentMAS + Agent0 Experimentation")
    print("=" * 60)
    print(f"Time: {datetime.now().isoformat()}")

    if args.interactive:
        await interactive_mode()
        return

    experiments = {
        "latent": experiment_latent_memory,
        "evolution": experiment_evolution_daemon,
        "curriculum": experiment_curriculum_agent,
        "swarm": experiment_latent_swarm,
    }

    if args.experiment == "all":
        for name, func in experiments.items():
            try:
                await func()
            except Exception as e:
                print(f"\nExperiment {name} failed: {e}")
    else:
        await experiments[args.experiment]()

    print("\n" + "=" * 60)
    print("Experimentation complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
