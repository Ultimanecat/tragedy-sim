"""Bounded whole-job process concurrency; only the parent writes reports."""

from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from multiprocessing import get_context
import os


DEFAULT_WORKERS = min(4, os.cpu_count() or 1)


def job_id(job):
    import json
    return json.dumps(list(job), ensure_ascii=True, separators=(",", ":"))


def run_jobs(jobs, worker, *, workers=DEFAULT_WORKERS, validate=None):
    """Yield (job, result, error) for all launched jobs, including on failure.

    Keep at most ``workers`` jobs in flight. After a failure, stop launching
    new work and drain already running jobs, preserving successful checkpoints.
    ``validate`` runs only in the parent, before a result is accepted. One
    worker is the serial control path and supports normal debugger/mocks.
    """
    if type(workers) is not int or workers < 1:
        raise ValueError("workers must be a positive integer")
    jobs = tuple(jobs)

    def collect(job, result):
        if validate is not None:
            validate(job, result)
        return job, result, None

    if workers == 1 or len(jobs) <= 1:
        for job in jobs:
            try:
                outcome = collect(job, worker(job))
            except Exception as error:
                yield job, None, error
                break
            yield outcome
        return
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)),
                             mp_context=get_context("spawn")) as executor:
        pending = {}
        next_job = 0
        failed = False

        def fill():
            nonlocal next_job
            while not failed and next_job < len(jobs) and len(pending) < workers:
                future = executor.submit(worker, jobs[next_job])
                pending[future] = next_job
                next_job += 1

        fill()
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            # Canonical ordering only when multiple futures finish together.
            for future in sorted(ready, key=pending.__getitem__):
                index = pending.pop(future)
                job = jobs[index]
                try:
                    outcome = collect(job, future.result())
                except Exception as error:
                    failed = True
                    outcome = job, None, error
                yield outcome
            fill()


def peak_memory_mib():
    """Best-effort process peak RSS, scoped to its worker lifetime."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD),
                            *((name, ctypes.c_size_t) for name in (
                                "peak_working_set", "working_set", "peak_paged_pool", "paged_pool",
                                "peak_nonpaged_pool", "nonpaged_pool", "pagefile", "peak_pagefile"))]
            data = Counters()
            data.cb = ctypes.sizeof(data)
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            api = ctypes.WinDLL("psapi", use_last_error=True)
            api.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD)
            if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb):
                return None
            return data.peak_working_set / (1024 * 1024)
        import resource
        import sys
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return value / (1024 * 1024 if sys.platform == "darwin" else 1024)
    except (ImportError, AttributeError, OSError):
        return None
