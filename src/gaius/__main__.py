"""Entry point for running gaius as a module.

Usage:
    uv run python -m gaius        # Run TUI (with splash)
    uv run python -m gaius.cli    # Run CLI
"""

from .launcher import main

if __name__ == "__main__":
    main()
