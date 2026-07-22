import argparse
import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .mock_worker import execute
from .runner import OrchestratorLoop
from .scheduler import Scheduler


async def run(database_url: str, max_stages: int) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        processed = await OrchestratorLoop(Scheduler(sessions), execute).run_until_idle(max_stages)
        print(f"processed {processed} stages")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VTV local mock orchestrator")
    parser.add_argument("database_url")
    parser.add_argument("--max-stages", type=int, default=1000)
    args = parser.parse_args()
    asyncio.run(run(args.database_url, args.max_stages))


if __name__ == "__main__":
    main()
