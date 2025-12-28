# goboard_domain_swarm.py
# Domain-agnostic: Press 'd' + domain prompt (e.g., "pension asset allocation") to rewire everything
# Requires: pip install langchain langchain-openai deepagents agentlightning[apo] gtda scikit-learn textual numpy

from __future__ import annotations
from textual import on, work
from textual.app import App, ComposeResult
from textual.widgets import Static, Input, ListView, ListItem
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from textual.screen import ModalScreen
import numpy as np
from sklearn.metrics.pairwise import pairwise_distances
from sklearn.decomposition import PCA
import random, time, json, hashlib, platform, asyncio
from typing import Dict, Any, List

# ────────────────────────────── LangChain DeepAgents + Embeddings ──────────────────────────────
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.tools import tool
from langchain_core.prompts import PromptTemplate
from deepagents import create_deep_agent  # LangChain's deepagents for sub-agent spawning + planning
from agentlightning import APO, LightningStoreClient, emit_prompt, emit_tool_call, emit_reward  # Agent-Lightning for APO tuning

# Setup (use your API keys)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
embedder = OpenAIEmbeddings(model="text-embedding-3-small")
store_client = LightningStoreClient()  # Connects to in-memory LightningStore for APO

# Dynamic agent factory
def create_domain_swarm(domain_prompt: str) -> List[Dict[str, Any]]:
    base_roles = [
        {"name": "Leader", "role": f"Oversee strategy for {domain_prompt}"},
        {"name": "Risk", "role": f"Identify threats in {domain_prompt}"},
        {"name": "Optimizer", "role": f"Find opportunities in {domain_prompt}"},
        {"name": "Planner", "role": f"Build long-term plans for {domain_prompt}"},
        {"name": "Critic", "role": f"Challenge assumptions in {domain_prompt}"},
        {"name": "Executor", "role": f"Simulate actions in {domain_prompt}"},
        {"name": "Adversary", "role": f"Break the plan for {domain_prompt}"},
    ]
    
    # DeepAgents: Create tunable agent with APO-wrapped prompt
    prompt_template = PromptTemplate.from_template(
        "You are {name}. Role: {role}\nDomain: {domain}\nTask: {task}\nRespond concisely."
    )
    apo = APO(  # Agent-Lightning APO: Tunes the prompt live
        prompt_template=prompt_template,
        beam_width=3,  # Explore 3 prompt variants per round
        max_iterations=2,  # Tune over 2 async rounds
        reward_fn=lambda output, gold: 1.0 if "optimal" in output.lower() else 0.5  # Domain-agnostic reward stub
    )
    
    agents = []
    for role in base_roles:
        # Create deep agent with sub-spawning + planning tool
        agent = create_deep_agent(
            model=llm,
            tools=[tool(lambda x: f"Planned step: {x}")("plan"),  # Built-in planning tool
                   tool(lambda: "Spawn sub-agent for detail")("spawn_sub")],
            system_prompt=role["role"],
            middleware=[apo.middleware]  # APO tunes prompts dynamically
        )
        agents.append({"agent": agent, "role": role, "emb_history": []})
    
    # Emit initial prompt for APO baseline
    for agent in agents:
        emit_prompt(agent["agent"], "Init domain adaptation")
    
    return agents

# VectorMemory + Dynamic Scene Graph
class DomainVectorMemory:
    def __init__(self):
        self.utterances: List[tuple[int, str, np.ndarray]] = []
        self.graph: List[tuple[int, int, float]] = []

    async def add(self, agent_id: int, text: str, domain: str):
        emb = np.array(embedder.embed_query(f"{domain}: {text}"))
        self.utterances.append((agent_id, text, emb))
        # Emit for APO reward
        emit_reward(text, 0.8)  # Placeholder; tune based on domain metrics

    def build_scene_graph(self, domain_prompt: str, threshold: float = 0.7):
        if len(self.utterances) < 2:
            return []
        embs = np.stack([u[2] for u in self.utterances])
        # Domain-biased similarity (cosine + keyword boost)
        sim = np.dot(embs, embs.T) / (np.linalg.norm(embs, axis=1)[:, np.newaxis] * np.linalg.norm(embs, axis=1)[np.newaxis, :] + 1e-8)
        if domain_prompt:
            # Boost edges with domain keywords (simple regex for demo)
            domain_keywords = set(domain_prompt.lower().split())
            for i in range(len(self.utterances)):
                for j in range(i+1, len(self.utterances)):
                    text_i, text_j = self.utterances[i][1].lower(), self.utterances[j][1].lower()
                    overlap = len(set(text_i.split()) & domain_keywords) / len(domain_keywords)
                    sim[i, j] *= (1 + overlap)
        np.fill_diagonal(sim, 0)
        edges = [(i, j, sim[i,j]) for i in range(len(self.utterances)) for j in range(i+1, len(self.utterances)) if sim[i,j] > threshold]
        self.graph = edges
        return edges

    def to_point_cloud(self) -> np.ndarray:
        if not self.utterances:
            return np.random.randn(20, 50)
        embs = np.stack([u[2] for u in self.utterances])
        pca = PCA(n_components=50)
        return pca.fit_transform(embs)

memory = DomainVectorMemory()

# ────────────────────────────── TDA (unchanged, now on dynamic cloud) ──────────────────────────────
try:
    from gtda.homology import VietorisRipsPersistence
    from gtda.diagrams import PersistenceEntropy
    TDA_AVAILABLE = True
    vr = VietorisRipsPersistence(homology_dimensions=[0, 1, 2])
    entropy = PersistenceEntropy()
except ImportError:
    TDA_AVAILABLE = False

def run_tda(cloud: np.ndarray) -> Dict[str, Any]:
    if not TDA_AVAILABLE:
        return {"entropy": 0.0, "h1_loop": None}
    dist = pairwise_distances(cloud, metric="euclidean")
    diagrams = vr.fit_transform([dist])[0]
    ent = entropy.fit_transform([diagrams])[0][0]
    h1 = diagrams[diagrams[:, 0] == 1]
    top_h1 = h1[h1[:, 2].max()] if len(h1) > 0 else None
    return {"entropy": ent, "h1_loop": top_h1}

# ────────────────────────────── TUI (enhanced with domain modal) ──────────────────────────────
class DomainModal(ModalScreen):
    DEFAULT_CSS = """
    Modal { align: center middle; }
    #domain-input { dock: bottom; height: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("Enter domain (e.g., 'pension asset allocation'): ")
        yield Input(id="domain-input", placeholder="Type and press Enter")

    def on_input_submitted(self, event: Input.Submitted):
        domain = event.input.value.strip()
        if domain:
            self.app.adapt_domain(domain)
        self.dismiss()

class Board(Static):
    def render_board(self, cloud: np.ndarray, tda_result: Dict, overlay: str, agents: List) -> str:
        # Project cloud to 19x19 (domain-agnostic)
        if cloud.shape[0] == 0:
            cloud = np.random.randn(20, 2)
        x = np.clip(((cloud[:,0] - cloud[:,0].min()) / (cloud[:,0].max() - cloud[:,0].min() + 1e-8) * 18).astype(int), 0, 18)
        y = np.clip(((cloud[:,1] - cloud[:,1].min()) / (cloud[:,1].max() - cloud[:,1].min() + 1e-8) * 18).astype(int), 0, 18)

        grid = [["·" for _ in range(19)] for _ in range(19)]
        for i, (xx, yy) in enumerate(zip(x, y)):
            if i < len(agents):
                color = agents[i]["role"]["name"][0].lower()  # Simple color by agent name
                grid[yy][xx] = f"[{color}]●[/{color}]"
            else:
                grid[yy][xx] = "◦"

        # TDA overlays: Domain death loops as Go threats
        if overlay == "h1" and tda_result["h1_loop"] is not None:
            for yy in range(19):
                for xx in range(19):
                    if random.random() < 0.2:  # Simulate loop projection
                        grid[yy][xx] = "[on bright_red]![/]"

        lines = [f"{19-y:2} " + " ".join(grid[y]) for y in range(19)]
        lines.append("   " + " ".join(chr(65+i) if i!=8 else " " for i in range(19)))
        return "\n".join(lines)

class GoBoardSwarmApp(App):
    CSS = """
    Screen { background: black; color: #ddd; }
    #grid { font-family: monospace; font-size: 11px; }
    .yellow { background: yellow; color: black; font-bold: true; }
    .panel { background: #111; border: tall #555; margin: 1; }
    #top-menu { dock: top; height: 1; }
    #status { dock: bottom; height: 1; background: #113; color: white; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("o", "cycle_overlay", "Overlay"),
        Binding("s", "run_swarm_round", "Swarm Round"),
        Binding("d", "show_domain_modal", "Adapt Domain"),
        Binding("0", "page('TDA')", "TDA Radar"),
        Binding("1", "page('SWARM')", "Swarm Log"),
        Binding("cmd+t", "toggle_mode", "Mode"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="top-menu", classes="yellow").update(
            " [1] SWARM  [0] TDA  [s] ROUND  [d] DOMAIN  [o] OVERLAY ".center(100)
        )
        with Horizontal():
            with Vertical():
                yield Static(id="main-board")
            with Vertical():
                yield ListView(id="log", classes="panel")
        yield Static(id="status").update(" Dynamic Swarm | Press 'd' to adapt domain ")

    def on_mount(self):
        self.domain = "pension asset allocation"  # Default
        self.agents = create_domain_swarm(self.domain)
        self.overlay_mode = "h1"
        self.tda_result = {"entropy": 0.0}
        self.cloud = np.random.randn(20, 50)
        self.refresh_board()

    def action_show_domain_modal(self):
        self.push_screen(DomainModal())

    def adapt_domain(self, new_domain: str):
        self.domain = new_domain
        self.agents = create_domain_swarm(new_domain)
        self.query_one("#status").update(f" Adapted to: {new_domain} | Swarm rewired ")
        self.run_swarm_round()  # Auto-run one round

    def refresh_board(self):
        board = Board().render_board(self.cloud, self.tda_result, self.overlay_mode, self.agents)
        self.query_one("#main-board").update(Static(board, id="grid"))

    @work
    async def run_swarm_round(self):
        log = self.query_one("#log", ListView)
        log.clear()
        task = f"Analyze crisis in {self.domain}: Inflation spike + liquidity freeze."
        
        for idx, agent_dict in enumerate(self.agents):
            agent = agent_dict["agent"]
            # DeepAgents invoke with planning + sub-spawn
            result = await agent.ainvoke({"input": task, "domain": self.domain})
            text = result["output"] if isinstance(result, dict) else str(result)
            await memory.add(idx, text, self.domain)
            log.append(ListItem(Static(f"[{agent_dict['role']['name']}]: {text}", markup=True)))
        
        memory.build_scene_graph(self.domain)
        self.cloud = memory.to_point_cloud()
        self.tda_result = run_tda(self.cloud)
        self.refresh_board()
        emit_reward("round_complete", 1.0)  # Trigger APO tune

    def action_cycle_overlay(self):
        modes = ["none", "h1", "h2"]
        self.overlay_mode = modes[(modes.index(self.overlay_mode) + 1) % len(modes)]
        self.refresh_board()

    def action_page(self, page: str):
        if page == "TDA":
            self.overlay_mode = "h1"
            self.refresh_board()

if __name__ == "__main__":
    GoBoardSwarmApp().run()


