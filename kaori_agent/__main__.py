"""Entry point: python -m kaori_agent"""

import asyncio

from kaori_agent.cli import main

if __name__ == "__main__":
    asyncio.run(main())
