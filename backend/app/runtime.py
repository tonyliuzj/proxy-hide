from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from dataclasses import dataclass


logger = logging.getLogger("proxyhide.runtime")


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    name: str
    command: tuple[str, ...]


MIGRATION = ProcessSpec(
    name="migrations",
    command=(sys.executable, "-m", "alembic", "upgrade", "head"),
)

SERVICES = (
    ProcessSpec(
        name="api",
        command=(
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ),
    ),
    ProcessSpec(
        name="scheduler",
        command=(sys.executable, "-m", "app.workers.scheduler"),
    ),
    ProcessSpec(
        name="worker",
        command=(sys.executable, "-m", "app.workers.consumer"),
    ),
    ProcessSpec(
        name="gateway",
        command=(sys.executable, "-m", "app.gateway"),
    ),
)

SHUTDOWN_TIMEOUT_SECONDS = 8.0


async def _start(spec: ProcessSpec) -> asyncio.subprocess.Process:
    logger.info("Starting %s", spec.name)
    return await asyncio.create_subprocess_exec(*spec.command)


async def _stop_processes(processes: dict[str, asyncio.subprocess.Process]) -> None:
    running = {name: process for name, process in processes.items() if process.returncode is None}
    if not running:
        return

    logger.info("Stopping %s", ", ".join(running))
    for process in running.values():
        with contextlib.suppress(ProcessLookupError):
            process.terminate()

    try:
        async with asyncio.timeout(SHUTDOWN_TIMEOUT_SECONDS):
            await asyncio.gather(*(process.wait() for process in running.values()))
        return
    except TimeoutError:
        logger.warning("Graceful shutdown timed out; killing remaining processes")

    remaining = [process for process in running.values() if process.returncode is None]
    for process in remaining:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await asyncio.gather(*(process.wait() for process in remaining))


async def _wait_for_migration(
    process: asyncio.subprocess.Process,
    stopped: asyncio.Event,
) -> int | None:
    migration_waiter = asyncio.create_task(process.wait(), name="migrations-exit")
    stop_waiter = asyncio.create_task(stopped.wait(), name="runtime-stop-during-migrations")
    try:
        done, _pending = await asyncio.wait(
            (migration_waiter, stop_waiter),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_waiter in done:
            return None
        return migration_waiter.result()
    finally:
        for task in (migration_waiter, stop_waiter):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def _wait_for_service(
    processes: dict[str, asyncio.subprocess.Process],
    stopped: asyncio.Event,
) -> tuple[str, int] | None:
    waiters = {
        name: asyncio.create_task(process.wait(), name=f"{name}-exit")
        for name, process in processes.items()
    }
    stop_waiter = asyncio.create_task(stopped.wait(), name="runtime-stop")
    try:
        done, _pending = await asyncio.wait(
            (*waiters.values(), stop_waiter),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_waiter in done:
            return None
        for name, waiter in waiters.items():
            if waiter in done:
                return name, waiter.result()
        raise RuntimeError("service wait completed without a result")
    finally:
        for task in (*waiters.values(), stop_waiter):
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


async def run_runtime() -> int:
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stopped.set)
            installed_signals.append(signum)

    migration: asyncio.subprocess.Process | None = None
    processes: dict[str, asyncio.subprocess.Process] = {}
    try:
        migration = await _start(MIGRATION)
        migration_code = await _wait_for_migration(migration, stopped)
        if migration_code is None:
            logger.info("Shutdown requested during migrations")
            return 0
        if migration_code != 0:
            logger.error("Migrations exited with status %d", migration_code)
            return migration_code
        logger.info("Migrations are current")

        for spec in SERVICES:
            if stopped.is_set():
                return 0
            processes[spec.name] = await _start(spec)

        result = await _wait_for_service(processes, stopped)
        if result is None:
            logger.info("Shutdown requested")
            return 0

        name, return_code = result
        logger.error("%s exited unexpectedly with status %d", name, return_code)
        return return_code if return_code != 0 else 1
    except OSError:
        logger.exception("Unable to start a required process")
        return 1
    finally:
        if migration is not None and migration.returncode is None:
            await _stop_processes({MIGRATION.name: migration})
        await _stop_processes(processes)
        for signum in installed_signals:
            loop.remove_signal_handler(signum)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(run_runtime()))


if __name__ == "__main__":
    main()
