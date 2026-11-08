import asyncio, logging
from fitcoach.bot import main
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
if __name__ == "__main__":
    asyncio.run(main())
