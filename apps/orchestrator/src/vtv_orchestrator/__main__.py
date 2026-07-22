import argparse
import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from .config import get_settings
from .mock_worker import execute as execute_mock
from .modal_executor import ModalStageExecutor
from .runner import OrchestratorLoop
from .scheduler import Scheduler
from .stage_router import StageRouter
from .storage import create_worker_object_store


async def run(database_url: str, max_stages: int, worker_mode: str, work_root: Path) -> None:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        object_store = create_worker_object_store(get_settings())
        local_router = StageRouter(work_root, object_store=object_store)
        if worker_mode == "mock":
            executor = execute_mock
        elif worker_mode == "modal":
            modal_executor = ModalStageExecutor().execute

            def executor(job):
                if job.stage_type in {"ASR_ALIGN", "VISION_ANALYSIS", "PROJECT_SYNTHESIS"}:
                    return modal_executor(job)
                return local_router.execute(job)

        else:
            executor = local_router.execute
        processed = await OrchestratorLoop(Scheduler(sessions), executor).run_until_idle(max_stages)
        print(f"processed {processed} stages")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the VTV local orchestrator")
    parser.add_argument("database_url")
    parser.add_argument("--max-stages", type=int, default=1000)
    parser.add_argument("--worker-mode", choices=("local", "modal", "mock"), default="local")
    parser.add_argument("--work-root", type=Path, default=Path(".vtv-work"))
    args = parser.parse_args()
    asyncio.run(run(args.database_url, args.max_stages, args.worker_mode, args.work_root))


if __name__ == "__main__":
    main()
