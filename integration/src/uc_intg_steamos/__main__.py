"""Allow running as python -m uc_intg_steamos."""

import asyncio

from uc_intg_steamos import main

if __name__ == "__main__":
    asyncio.run(main())
