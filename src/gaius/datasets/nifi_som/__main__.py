"""Entry point for running as python -m gaius.datasets.nifi_som."""

import asyncio
from .generator import main

if __name__ == "__main__":
    asyncio.run(main())
