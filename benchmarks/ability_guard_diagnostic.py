"""Per-seed diagnostics for the ability-guard probe.

Run from the repository root:

    python -m benchmarks.ability_guard_diagnostic 0 3 5
    python -m benchmarks.ability_guard_diagnostic -120 0   # cap decisions at 120
"""
from __future__ import annotations

import sys
import time

from benchmarks import ability_guard_probe as probe
from tragedy_sim.scenario_library import ScenarioLibrary


def main():
    scenario = ScenarioLibrary().get("official-btx-01-machina-solar-cogwheel")
    values = [int(value) for value in sys.argv[1:]]
    cap = 1500
    if values and values[0] < 0:
        cap = abs(values[0])
        values = values[1:]
    seeds = values or [0]
    for defense in (False, True):
        for seed in seeds:
            started = time.perf_counter()
            result = probe.play_one(scenario, seed, defense=defense,
                                    max_decisions=cap)
            elapsed = time.perf_counter() - started
            print("defense", defense, "seed", seed, "elapsed", round(elapsed, 2),
                  "cap", cap, "result", result, flush=True)


if __name__ == "__main__":
    main()
