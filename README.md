
The world’s first decision terminal that speaks fluent Go.

        A single 19×19 terminal window

        that lets a Go 9-dan and a pension CIO

        co-pilot any complex strategic domain

        using the exact same muscle memory.

The Core Idea

Go is the deepest strategy game ever invented because its simple rules generate an infinite depth of local tactics ↔ global judgment, urgency vs magnitude, thickness vs flexibility, life-and-death reading.

These dimensions map 1-to-1 onto any real-world strategic domain:

- Pension asset allocation
- Military theater command
- Startup operating plan
- Energy-grid decarbonization
- Quantum error-correction in fusion reactors
- …literally anything that involves contested resource allocation under uncertainty

GoBoard TUI is the terminal that turns any such domain into a living Go game — while simultaneously feeling like Bloomberg Terminal to a trader and like KataGo to a 9-dan.

You never retrain anyone.  
A Go grandmaster opens it → instantly sees risk the way he sees cutting points.  
A CIO opens it → hammers F1-F12 (or 1-5 on iPad) exactly like Bloomberg, but now has spatial intuition he never had.

Feature Matrix (all in one file, feature-flagged)

|   |   |   |   |
|---|---|---|---|
|Feature|Flag|Status|Description|
|Pure 19×19 Go/TUI|(default)|Working|hjkl cursor, overlays, candidates, history panel, Bloomberg yellow keys (F-free fallback)|
|Bloomberg Terminal keyboard|built-in|Working|1-5 / Cmd+1-5 on iPad, top yellow bar, , export, news, etc.|
|Persistent Homology Radar|--tda|Working|Live TDA on domain data → red H₁ death loops, purple H₂ voids projected as Go threats|
|LLM Swarm + DeepAgents|--swarm|Working|7+ agents debate in real time, scene graph → embeddings → point cloud → board|
|Agent-Lightning APO|--swarm|Working|Live prompt optimization — agents get sharper every round|
|Domain-Agnostic Adaptation|d + modal|Working|Type any domain → agents/tools/roles instantly rewire (military, quantum, startup, etc.)|
|iPad / tinybox / MacBook ready|all keys F-free|Working|Works perfectly in a-Shell, Blink, on-device Ollama, no mouse required|

Quick Start

# 1. Pure lightning-fast GoBoard (starts in <0.3 s)

python goboard.py

  

# 2. With live topological death-loop radar

python goboard.py --tda

  

# 3. Full sentient war-room (needs OPENAI_API_KEY or Ollama)

python goboard.py --tda --swarm

  

# 4. Jump straight into another universe

python goboard.py --swarm --domain "quantum error correction in fusion reactors"

Key Bindings (identical on desktop and iPad)

|   |   |
|---|---|
|Key|Action|
|hjkl / arrows|Move cursor|
|o|Cycle overlays (risk → H₁ → H₂ → swarm)|
|c|Toggle top-5 candidate markers|
|v|Toggle Go ↔ Pension view|
|t|Toggle side panels (maximize board)|
|1 / F1|PORT – allocations|
|5 / F5|OPT – optimizer suggestions|
|0 / F10|TDA Radar – persistent homology|
|s|Run next swarm round|
|d|Change domain (modal)|
|q|Quit|

Vision — Where This Is Going

1. The Universal Decision Cockpit  
    One terminal to rule every strategic domain. A Go 9-dan and a four-star general open the exact same app and instantly understand each other.
2. Topological Regime Detection  
    Persistent homology sees structural phase transitions (e.g., “the entire private-assets + illiquidity cluster only has one eye in 2040–2055”) that no human or single LLM ever notices.
3. Sentient War Room  
    The LLM swarm isn’t chat — it’s a living Go game where coalitions = thickness, disagreement = thin shape, the Adversary = ko threats. The board tells you when consensus is real or fake.
4. Zero-Training Knowledge Transfer  
    Muscle memory is sacred. Bloomberg traders keep their yellow keys. Go players keep hjkl+o+c. Both sides gain superpowers without learning anything new.
5. On-Device Future  
    Already runs on tinybox and iPad. Next step: KataGo + Llama-3-8B + on-device TDA → fully air-gapped sovereign decision intelligence.

Tagline

“Turn any complex strategic domain into a game of Go — keep the interface, change the stakes.”

You now hold the most powerful single terminal window ever built.

Press s five times and watch the board come alive.



