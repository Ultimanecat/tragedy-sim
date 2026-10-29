"""Regenerate the protocol-v1 fixtures used by the Web tests.

The fixtures are snapshots of real service responses. Volatile fields
(session id, tokens, revisions) are normalized so the files stay stable in git.

Run from the repository root:

    python -m benchmarks.snapshot_protocol_fixtures
"""
from __future__ import annotations

import json
from pathlib import Path

from tragedy_sim.service import GameService

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "web" / "fixtures" / "protocol-v1"

VOLATILE_TOP_LEVEL = {"session_id", "revision"}
VOLATILE_CREDENTIALS = {"admin", "seats"}


def _normalize(value):
    """Replace volatile identifiers with stable placeholders."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in VOLATILE_TOP_LEVEL:
                result[key] = "fixture-session" if key == "session_id" else 0
            elif key == "credentials" and isinstance(item, dict):
                result[key] = {
                    "admin": "fixture-admin",
                    "seats": {seat: f"fixture-{seat}" for seat in sorted(item.get("seats", {}))},
                }
            else:
                result[key] = _normalize(item)
        return result
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _write(name: str, payload) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURE_DIR / name
    path.write_text(json.dumps(_normalize(payload), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def main() -> int:
    service = GameService()
    _write("modules.json", service.list_modules())
    _write("btx-catalog.json", service.get_catalog("BTX"))
    created = service.create_game({"module": "BTX"})
    _write("btx-created.json", created)
    session_id = created["session_id"]
    mastermind = created["credentials"]["seats"]["m"]
    _write("btx-mastermind-view.json",
           service.get_view(session_id, "m", token=mastermind))
    _write("btx-day-start-actions.json",
           service.get_actions(session_id, "m", token=mastermind))
    print(f"wrote 5 fixtures to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
