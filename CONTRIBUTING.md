# Contributing

Thanks for your interest in improving the FreeCAD Tool Server. This guide covers how the
project is structured, how to add a tool, and how to get a change merged.

## Scope

This repo is the **tool server** — the typed HTTP + MCP surface that lets an AI agent drive
FreeCAD. Good contributions include: new geometry or FEM tools, better validation and error
messages, broader OS/FreeCAD-version support, docs, and bug fixes. Things that belong elsewhere:
web UIs, agent orchestration loops, and provider-specific agent glue — those sit on top of this
server, not inside it.

## Dev setup

The server runs **inside FreeCAD's bundled Python**, not your system Python — FreeCAD's compiled
bindings are built against its own interpreter.

```bash
# Windows
"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install -r requirements.txt
start.bat

# Linux / macOS
FREECAD_PYTHON=/path/to/FreeCAD/bin/python ./start.sh
```

Confirm it's healthy and browse the live API:

```bash
curl http://localhost:8000/health          # {"status":"ok","freecad_available":true,...}
# open http://localhost:8000/docs           # interactive Swagger UI for every endpoint
```

## Project layout

| File | Responsibility |
|---|---|
| `main.py` | FastAPI endpoints — thin HTTP layer, one route per tool |
| `session.py` | The real work — FreeCAD geometry, booleans, export, FEM |
| `models.py` | Typed Pydantic request/response models + validators |
| `mcp_server.py` | Exposes the same tools over MCP |
| `freecad_bridge.py` | Headless FreeCAD discovery/import |
| `AGENTS.md` / `CLAUDE.md` | The agent operating manual (identical content) |

## Adding a new tool

A tool is three small, layered pieces. Follow the shape of an existing endpoint (e.g.
`export_step` or `make_hole`) rather than inventing a new pattern.

1. **Model** (`models.py`) — a `BaseModel` request with typed fields, sensible defaults, and a
   `@field_validator` for anything with rules (name format, allowed enum values, units). Be
   permissive where it's safe (e.g. accept case-insensitive plane names).
2. **Logic** (`session.py`) — a method on the session that does the geometry and returns a plain
   `dict` of results (never raises for expected failure — return a clear message the endpoint can
   surface).
3. **Endpoint** (`main.py`) — a thin route: call `_freecad_guard()`, `get_session()`, run the
   logic, and wrap the outcome in the standard envelope with `_ok(...)` / `_err(...)`.

Every response uses the same envelope, so callers can rely on it:

```json
{ "success": true, "message": "...", "data": { }, "warnings": [], "errors": [] }
```

If your tool places a mating feature (a hole, bore, boss, or pocket), it should support the
**mechanical integration checks** described in `AGENTS.md` — agents are expected to verify
engagement and clearance with `check_interference` / `check_min_distance` before export. Keep
that workflow possible.

## Testing your change

There's no network mocking — you test against a running FreeCAD server.

1. Start the server (above).
2. Drive your tool with the bundled stdlib client and assert the result:

```python
from tools.freecad_client import FreeCADClient
fc = FreeCADClient()

fc.tool("POST", "/document/create", name="t")
fc.tool("POST", "/shapes/add_box", name="b", length=40, width=20, height=10)
# ... exercise your new endpoint ...
info = fc.tool("POST", "/model/get_shape_info", shape_name="b")
assert 7900 < info["volume_mm3"] < 8100        # a real, physics-based check
```

3. For anything that exports geometry, finish with `validate_step` and confirm
   `is_clean == true` and `solid_count == 1`. A tool that produces geometry which won't validate
   isn't done.

`tools/agent_test_suite.py` is an **end-to-end** reference: it asks an agent to build graded
parts and scores volume/validation. It drives an agent runner (an MCP/HTTP agent client on top
of this server), so it needs that driver running — it is not a unit-test harness for the server
alone.

## Code style

- Match the surrounding code — naming, comment density, and structure. New code should read like
  it was always there.
- Keep endpoints thin; put logic in `session.py`.
- Prefer clear, actionable error messages over stack traces reaching the caller.
- Round and sanity-check numeric output.

## Submitting a change

1. Fork and branch from `main` (`git checkout -b fix/short-description`).
2. Keep the change focused — one logical change per PR.
3. In the PR description, say what you changed, how you tested it (include the client snippet or
   `validate_step` result), and note any new FreeCAD/Elmer/Gmsh requirement.
4. Make sure no build artifacts, output files, or secrets are committed (`.gitignore` covers the
   common ones).

## Reporting issues

Open an issue with your OS, FreeCAD version (`curl /health` reports it), the exact tool call, and
the response you got versus what you expected. A minimal `freecad_client` snippet that reproduces
it is the fastest path to a fix.
