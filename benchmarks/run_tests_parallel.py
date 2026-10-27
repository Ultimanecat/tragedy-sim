"""Run Python test modules in parallel processes.

unittest has no built-in parallel runner in this environment. Each test module
runs in its own ``python -m unittest`` subprocess, so module-level state and
servers are isolated. The queue is dynamic, so slow modules do not block a
worker for the whole run.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import os
import subprocess
import sys
import time


def test_modules(root: Path) -> list[str]:
    return [f"tests.{path.stem}" for path in sorted(root.glob("test_*.py"))]


def run_module(module: str, root: Path, timeout: float | None) -> tuple[str, int, float, str]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", module],
        cwd=root, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(root)},
    )
    elapsed = time.perf_counter() - started
    output = (completed.stdout or "") + (completed.stderr or "")
    return module, completed.returncode, elapsed, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=None)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    root = Path(__file__).resolve().parents[1]
    modules = test_modules(root / "tests")
    if not modules:
        print("no test modules found")
        return 1
    print(f"running {len(modules)} modules with {args.workers} workers", flush=True)
    started = time.perf_counter()
    failures = []
    completed_count = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(run_module, module, root, args.timeout): module
            for module in modules
        }
        for future in as_completed(futures):
            module = futures[future]
            try:
                _, code, elapsed, output = future.result()
            except subprocess.TimeoutExpired:
                failures.append((module, "timeout", "", 0.0))
                print(f"TIMEOUT {module}", flush=True)
                continue
            completed_count += 1
            print(f"{completed_count:3d}/{len(modules)} {elapsed:7.2f}s "
                  f"code={code} {module}", flush=True)
            if code != 0:
                failures.append((module, code, output, elapsed))
    total = time.perf_counter() - started
    print(f"\nparallel total {total:.2f}s, modules={len(modules)}, "
          f"workers={args.workers}, failures={len(failures)}")
    for module, code, output, elapsed in failures:
        print(f"\nFAILED {module} code={code} elapsed={elapsed:.2f}s")
        tail = "\n".join(output.strip().splitlines()[-30:])
        print(tail)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
