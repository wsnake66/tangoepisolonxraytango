from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from time import sleep
from typing import Callable


_WORKER_EXECUTOR = None
_WORKER_EXECUTOR_LOCK = Lock()


def _worker_executor() -> ThreadPoolExecutor:
    global _WORKER_EXECUTOR
    with _WORKER_EXECUTOR_LOCK:
        if _WORKER_EXECUTOR is None:
            _WORKER_EXECUTOR = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="moldboxer-geometry",
            )
        return _WORKER_EXECUTOR


class BackgroundWorkerTask:
    """Pollable worker future with optional main-thread finalization."""

    def __init__(
        self,
        future: Future,
        *,
        on_complete: Callable | None = None,
    ) -> None:
        self._future = future
        self._on_complete = on_complete
        self._finished = False
        self._result = None

    def done(self) -> bool:
        return self._future.done()

    def then(self, on_complete: Callable):
        """Attach main-thread finalization before the task is finished."""

        if self._finished:
            raise RuntimeError("Cannot attach finalization to a finished task")
        previous = self._on_complete
        if previous is None:
            self._on_complete = on_complete
        else:
            self._on_complete = lambda result: on_complete(previous(result))
        return self

    def finish(self):
        if self._finished:
            return self._result
        result = self._future.result()
        if self._on_complete is not None:
            result = self._on_complete(result)
        self._result = result
        self._finished = True
        return result

    def wait(self):
        """Block until the worker finishes, then finalize on the caller thread."""

        return self.finish()


class BackgroundTaskSequence:
    """Drive a generator of worker tasks while finalizing each on main."""

    def __init__(self, step_generator) -> None:
        self._steps = iter(step_generator)
        self._started = False
        self._pending = None
        self._finished = False
        self._result = None
        self._on_complete = None
        self._finalized = False
        self._redraw_interval = None

    @property
    def redraw_interval(self):
        pending_interval = getattr(self._pending, "redraw_interval", None)
        if pending_interval is not None:
            return pending_interval
        return self._redraw_interval

    @redraw_interval.setter
    def redraw_interval(self, value) -> None:
        self._redraw_interval = value

    def then(self, on_complete: Callable):
        if self._finalized:
            raise RuntimeError("Cannot attach finalization to a finished sequence")
        previous = self._on_complete
        if previous is None:
            self._on_complete = on_complete
        else:
            self._on_complete = lambda result: on_complete(previous(result))
        return self

    def _advance(self, *, wait: bool) -> bool:
        if self._finished:
            return True
        value = None
        pending_error = None
        if self._pending is not None:
            if not wait and not self._pending.done():
                return False
            try:
                pending_wait = getattr(self._pending, "wait", None)
                if wait and callable(pending_wait):
                    value = pending_wait()
                elif wait:
                    while not self._pending.done():
                        sleep(0.001)
                    value = self._pending.finish()
                else:
                    value = self._pending.finish()
            except BaseException as error:
                pending_error = error
            self._pending = None

        try:
            if pending_error is not None:
                pending = self._steps.throw(pending_error)
            elif not self._started:
                self._started = True
                pending = next(self._steps)
            else:
                pending = self._steps.send(value)
        except StopIteration as stop:
            self._result = stop.value
            self._finished = True
            return True
        except BaseException:
            self._finished = True
            raise

        if not (
            callable(getattr(pending, "done", None))
            and callable(getattr(pending, "finish", None))
        ):
            raise TypeError("Background task sequences must yield pollable tasks")
        self._pending = pending
        return False

    def done(self) -> bool:
        return self._advance(wait=False)

    def wait(self):
        """Drive the sequence synchronously without spinning between stages."""

        while not self._finished:
            self._advance(wait=True)
        return self.finish()

    def finish(self):
        if not self._finished:
            raise RuntimeError("Background task sequence has not completed")
        if not self._finalized:
            if self._on_complete is not None:
                self._result = self._on_complete(self._result)
            self._finalized = True
        return self._result


def submit_worker_task(callable_, /, *args, on_complete=None, **kwargs):
    """Run a Blender-free worker call in the shared background queue."""

    future = _worker_executor().submit(callable_, *args, **kwargs)
    return BackgroundWorkerTask(future, on_complete=on_complete)


def shutdown_background_worker_tasks() -> None:
    """Dispose the queue on add-on unload; it is recreated on next use."""

    global _WORKER_EXECUTOR
    with _WORKER_EXECUTOR_LOCK:
        executor = _WORKER_EXECUTOR
        _WORKER_EXECUTOR = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def finish_task_sync(value):
    """Finish a returned task for legacy synchronous workflow entrypoints."""

    wait = getattr(value, "wait", None)
    if callable(wait):
        return wait()
    if callable(getattr(value, "finish", None)):
        return value.finish()
    return value
