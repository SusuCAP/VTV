from collections.abc import Callable

from vtv_schemas.jobs import StageJob, StageResult

from .scheduler import Scheduler


class OrchestratorLoop:
    def __init__(
        self,
        scheduler: Scheduler,
        executor: Callable[[StageJob], StageResult],
        worker_id: str = "local-mock-worker",
    ) -> None:
        self._scheduler = scheduler
        self._executor = executor
        self._worker_id = worker_id

    async def run_once(self) -> bool:
        claim = await self._scheduler.claim_one(self._worker_id)
        if claim is None:
            return False
        job = await self._scheduler.build_job(claim)
        result = self._executor(job)
        committed = await self._scheduler.commit_result(claim, result)
        if committed:
            await self._scheduler.finalize_stage(claim)
        return True

    async def run_until_idle(self, max_stages: int = 1000) -> int:
        processed = 0
        while processed < max_stages and await self.run_once():
            processed += 1
        if processed == max_stages:
            raise RuntimeError("orchestrator stage limit reached before queue became idle")
        return processed
