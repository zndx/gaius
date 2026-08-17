#!/usr/bin/env python3
"""One-shot: back+forward fill Agenda from scheduled surfaces."""

from __future__ import annotations

from gaius.engine.services.agenda_emit import backfill_surfaces
from gaius.engine.services.agenda_notes import kb_root_from_env


def main() -> int:
    root = kb_root_from_env()
    made = backfill_surfaces(root)
    print(f"kb={root} created={len(made)}")
    for item in made:
        print(f"  {item.kind:5} {item.path}  {item.title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
