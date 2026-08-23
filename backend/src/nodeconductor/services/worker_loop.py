import asyncio
from contextlib import suppress

from nodeconductor.services.jobs_worker import claim_next_job, run_claimed_job
from nodeconductor.services.worker_executors import WorkerExecutor


class WorkerLoopController:
    """Remplit les places disponibles et attend proprement les jobs lances."""

    def __init__(
        self,
        interval_seconds: float,
        max_concurrency: int = 4,
        max_concurrency_per_connection: int = 2,
        executor: WorkerExecutor | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.max_concurrency = max_concurrency
        self.max_concurrency_per_connection = max_concurrency_per_connection
        self.executor = executor
        self._task: asyncio.Task | None = None
        self._active_tasks: set[asyncio.Task] = set()
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def active_job_count(self) -> int:
        return sum(not task.done() for task in self._active_tasks)

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        await self._task
        self._task = None

    def _job_done(self, task: asyncio.Task) -> None:
        with suppress(Exception):
            task.result()

    def _discard_finished_tasks(self) -> None:
        self._active_tasks = {
            task for task in self._active_tasks if not task.done()
        }

    async def _fill_available_slots(self) -> None:
        self._discard_finished_tasks()
        while (
            not self._stop_event.is_set()
            and len(self._active_tasks) < self.max_concurrency
        ):
            job = await asyncio.to_thread(
                claim_next_job,
                self.max_concurrency,
                self.max_concurrency_per_connection,
            )
            if job is None:
                return
            task = asyncio.create_task(
                asyncio.to_thread(
                    run_claimed_job,
                    job,
                    executor=self.executor,
                )
            )
            self._active_tasks.add(task)
            task.add_done_callback(self._job_done)

    async def _wait_for_change(self) -> None:
        stop_waiter = asyncio.create_task(self._stop_event.wait())
        waiters = {*self._active_tasks, stop_waiter}
        await asyncio.wait(
            waiters,
            timeout=self.interval_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not stop_waiter.done():
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter

    async def _loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self._fill_available_slots()
                if not self._stop_event.is_set():
                    await self._wait_for_change()
        finally:
            if self._active_tasks:
                await asyncio.gather(*self._active_tasks, return_exceptions=True)
