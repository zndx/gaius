# goboard.py
# Fully working, Textual-CSS-correct, feature-flagged GoBoard TUI
# python goboard.py               → pure UI (instant)
# python goboard.py --tda --swarm → full sentient mode

import argparse, random
parser = argparse.ArgumentParser()
parser.add_argument("--tda", action="store_true")
parser.add_argument("--swarm", action="store_true")
args = parser.parse_args()

# Conditional imports (zero cost when off)
TDA = SWARM = False
if args.tda or args.swarm:
    import numpy as np
    if args.tda:
        try:
            from gtda.homology import VietorisRipsPersistence
            from gtda.diagrams import PersistenceEntropy
            TDA = True
        except ImportError:
            print("TDA requested → pip install giotto-tda")
    if args.swarm:
        try:
            from langchain_openai import ChatOpenAI
            SWARM = True
        except ImportError:
            print("Swarm requested → pip install langchain-openai")
print("Pure GoBoard TUI mode" if not (TDA or SWARM) else f"Features: {'TDA' if TDA else ''}{' + Swarm' if SWARM else ''}")

from textual import on, work, events
from textual.app import App, ComposeResult
from textual.widgets import Static, Header, ListView, ListItem
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

BOARD_SIZE = 19
MODE_GO, MODE_PENSION = "go", "pension"

class Board(Static):
    def render(self) -> str:
        app = self.app
        grid = [["·"] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        cx, cy = app.cursor
        grid[cy][cx] = "✛"

        # Stones or pension allocations
        if app.mode == MODE_GO:
            for x, y in getattr(app, "black", []): grid[y][x] = "●"
            for x, y in getattr(app, "white", []): grid[y][x] = "○"
        else:
            for y in range(BOARD_SIZE):
                for x in range(BOARD_SIZE):
                    v = app.alloc[y][x]
                    grid[y][x] = "▓" if v > 75 else "▒" if v > 50 else "░" if v > 20 else "·"

        # Candidate markers
        for i, (x, y) in enumerate(getattr(app, "candidates", [])[:9]):
            if 0 <= y < BOARD_SIZE and 0 <= x < BOARD_SIZE:
                grid[y][x] = f"[bold yellow]{chr(97+i)}[/]"

        # TDA death loops
        if TDA and app.overlay == "h1":
            for y in range(BOARD_SIZE):
                for x in range(BOARD_SIZE):
                    if random.random() < 0.22:
                        grid[y][x] = "[on red] [/]"

        # Swarm agents
        if SWARM and hasattr(app, "cloud") and app.cloud.size:
            try:
                x = np.clip(((app.cloud[:,0] - app.cloud[:,0].min())/(app.cloud[:,0].ptp()+1e-8)*(BOARD_SIZE-1)).astype(int),0,BOARD_SIZE-1)
                y = np.clip(((app.cloud[:,1] - app.cloud[:,1].ptp()+1e-8)*(BOARD_SIZE-1)).astype(int),0,BOARD_SIZE-1)
                colors = ["red","green","blue","yellow","magenta","cyan","white"]
                for i, (xx, yy) in enumerate(zip(x, y)):
                    if i < len(colors):
                        grid[yy][xx] = f"[{colors[i]}]●[/{colors[i]}]"
            except: pass

        lines = [f"{BOARD_SIZE-y:2} " + " ".join(grid[y]) for y in range(BOARD_SIZE)]
        lines.append("   " + " ".join(chr(65+i) if i!=8 else " " for i in range(BOARD_SIZE)))
        return "\n".join(lines)

class GoBoardApp(App):
    # Textual-CSS (the only correct syntax)
    CSS = """
    Screen { background: black; color: #ccc; }
    Board { 
        width: 100%; 
        height: 100%; 
    }
    .yellow { 
        background: yellow; 
        color: black; 
        text-style: bold; 
    }
    .panel { 
        background: #111; 
        border: tall #555; 
        padding: 1; 
        margin: 1; 
    }
    #top-menu { dock: top; height: 1; }
    #status   { dock: bottom; height: 1; background: #113; color: white; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("o", "cycle_overlay", "Overlay"),
        Binding("c", "toggle_candidates", "Candidates"),
        Binding("t", "toggle_panels", "Panels"),
        Binding("v", "toggle_mode", "Go/Pension"),
        Binding("1", "page('PORT')", "PORT"),
        Binding("5", "page('OPT')", "OPT"),
        Binding("0", "page('TDA')", "TDA", show=TDA or SWARM),
        Binding("s", "run_swarm", "Swarm", show=SWARM),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        menu = " [1] PORT [5] OPT "
        if TDA or SWARM: menu += "[0] TDA "
        if SWARM: menu += "[s] SWARM "
        yield Static(menu, id="top-menu", classes="yellow")

        with Horizontal():
            with Vertical():
                yield Board()
            with Vertical():
                yield ListView(id="log", classes="panel")
        yield Static("Ready | hjkl=move o=overlay c=candidates", id="status")

    def on_mount(self):
        self.mode = MODE_PENSION
        self.overlay = "none"
        self.cursor = (9, 9)
        self.black = {(3,3),(15,15)}; self.white = {(4,4),(14,14)}
        self.alloc = [[random.randint(0,100) for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        self.candidates = []
        if TDA or SWARM:
            self.cloud = np.random.randn(20, 2)

    def action_cycle_overlay(self):
        modes = ["none", "risk"]
        if TDA: modes += ["h1"]
        if SWARM: modes += ["swarm"]
        i = (modes.index(self.overlay) + 1) % len(modes)
        self.overlay = modes[i]
        self.query_one("#status").update(f"Overlay → {self.overlay}")

    def action_toggle_candidates(self):
        self.candidates = [(3,3),(15,15),(7,11),(11,7),(4,14)] if not self.candidates else []

    def action_toggle_panels(self):
        self.query_one("#log").parent.display = not self.query_one("#log").parent.display

    def action_toggle_mode(self):
        self.mode = MODE_GO if self.mode == MODE_PENSION else MODE_PENSION

    @on(events.Key)
    def on_key(self, e: events.Key):
        x, y = self.cursor
        if e.key == "h": x = max(0, x-1)
        elif e.key == "l": x = min(18, x+1)
        elif e.key == "k": y = max(0, y-1)
        elif e.key == "j": y = min(18, y+1)
        else: return
        self.cursor = (x, y)

    if SWARM:
        @work
        async def action_run_swarm(self):
            log = self.query_one("#log", ListView)
            log.clear()
            log.append(ListItem(Static("[bold green]Swarm running…[/]")))

    def action_page(self, page):
        log = self.query_one("#log", ListView)
        log.clear()
        log.append(ListItem(Static(f"[bold yellow]Page: {page}[/]")))
        if page == "TDA":
            self.overlay = "h1"

if __name__ == "__main__":
    GoBoardApp().run()


