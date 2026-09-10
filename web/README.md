# Web client

This directory owns the browser client. Its only rules boundary is JSON protocol v1;
it must not import Python sources or inspect localized messages to decide game flow.

- `src/api/types.ts` is the frozen TypeScript contract.
- `fixtures/protocol-v1/` contains deterministic responses for offline UI development.
- The authoritative protocol narrative remains `docs/json-api.md`.

The React/Vite application is added in phase 1. Contract fixtures can already be
used by component prototypes and future Vitest tests without running Python.
