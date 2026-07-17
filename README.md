# FreeCAD Tool Server

An HTTP + [MCP](https://modelcontextprotocol.io) tool server that lets an AI agent of your
choice drive [FreeCAD](https://www.freecad.org) programmatically — building, analyzing, and
exporting real 3D CAD geometry through typed tool calls.

Agents call REST endpoints (or MCP tools) to create primitives, run boolean operations, loft
airfoils, drill holes, fillet edges, check clearances, run finite-element analysis via
[Elmer](https://www.elmerfem.org), and export validated STEP files — receiving structured
feedback at every step.

```
Your agent (Claude Code, Claude Desktop, any MCP/HTTP client)
      │  MCP tools  or  JSON over HTTP
      ▼
FreeCAD Tool Server  (main.py, typed models in models.py)
      │  in-process import
      ▼
FreeCAD 1.1 bundled Python  ──►  OpenCASCADE geometry kernel
```

The server runs **inside FreeCAD's bundled Python interpreter** — FreeCAD is imported as a
module, not shelled out as a subprocess. That's why you launch it with FreeCAD's `python.exe`,
not your system Python.

---

## Prerequisites

- **[FreeCAD 1.1+](https://www.freecad.org/downloads.php)** installed (ships its own Python 3.11).
- *(Optional, for FEM)* **[Elmer](https://www.elmerfem.org/blog/binaries/)** and
  **[Gmsh](https://gmsh.info)** on your `PATH` for the `/fem/*` endpoints and `elmer_*.py` runners.

No system Python is required to run the server — FreeCAD's interpreter provides everything.

---

## Setup

### 1. Install the Python dependencies into FreeCAD's interpreter

**Windows**
```bat
"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install -r requirements.txt
```

**Linux / macOS** (adjust to your FreeCAD install)
```bash
/path/to/FreeCAD/bin/python -m pip install -r requirements.txt
```

### 2. Start the server

**Windows** — edit the FreeCAD path in `start.bat` if needed, then:
```bat
start.bat
```

**Linux / macOS** — set `FREECAD_PYTHON` to your FreeCAD interpreter, then:
```bash
FREECAD_PYTHON=/path/to/FreeCAD/bin/python ./start.sh
```

The server listens on **http://localhost:8000**. Interactive API docs (Swagger UI) are at
**http://localhost:8000/docs**.

### 3. Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","freecad_available":true,"freecad_version":"1.1.1",...}
```

---

## Connect your agent

### Option A — MCP (Claude Code, Claude Desktop, any MCP client)

`mcp_server.py` exposes the tool server over the Model Context Protocol. Point your MCP client
at it. For **Claude Code**, add it to your MCP config:

```bash
claude mcp add freecad -- "C:\Program Files\FreeCAD 1.1\bin\python.exe" /path/to/mcp_server.py
```

or add an entry to your client's MCP settings JSON:

```json
{
  "mcpServers": {
    "freecad": {
      "command": "C:\\Program Files\\FreeCAD 1.1\\bin\\python.exe",
      "args": ["/absolute/path/to/mcp_server.py"]
    }
  }
}
```

The agent then gets every FreeCAD tool as a native MCP tool.

### Option B — Claude Code reading `AGENTS.md` / `CLAUDE.md` directly

Clone this repo and open it in Claude Code (or any agent that reads `AGENTS.md`). The bundled
[`AGENTS.md`](AGENTS.md) is a complete operating manual — the modeling loop, every endpoint, the
common pitfalls, and the required integration checks. Start the server, tell your agent what to
build, and it drives the HTTP API using that guide. A copy is provided as `CLAUDE.md` so Claude
Code loads it automatically.

### Option C — Raw HTTP from any language

Every tool is a plain REST endpoint. Minimal stdlib Python client (no extra deps) in
[`tools/freecad_client.py`](tools/freecad_client.py):

```python
from tools.freecad_client import FreeCADClient

fc = FreeCADClient()   # defaults to http://127.0.0.1:8000
fc.tool("POST", "/document/create", name="demo")
fc.tool("POST", "/shapes/add_box", name="b", length=50, width=30, height=10)
info = fc.tool("POST", "/model/get_shape_info", shape_name="b")
print(info["volume_mm3"])   # 15000.0
```

---

## The core modeling loop

```
create_document
  → add primitives (add_box / add_cylinder / add_cone / add_wing)
  → boolean ops (boolean_union / boolean_cut / make_hole)
  → inspect (get_shape_info / bounding_box / check_interference)
  → finish (fillet_edges / chamfer_edges)
  → export (export_step)
  → validate (validate_step)   ← aim for is_clean == true, solid_count == 1
```

See [`AGENTS.md`](AGENTS.md) for the full endpoint reference, edge-selector rules, the in-place
boolean-update pattern, and the mechanical integration checks (interference / clearance) that
catch spatial errors before export.

---

## Finite-element analysis (optional)

With Elmer and Gmsh installed, the `/fem/*` endpoints and the `elmer_*.py` runners cover a broad
tutorial set — elasticity, heat, electrostatics, magnetostatics, fluid flow, eigenmodes, and
more. These are heavier and require the external Elmer/Gmsh toolchain; the CAD tools work without
them.

---

## Repository layout

| Path | What it is |
|---|---|
| `main.py` | FastAPI tool server — all HTTP endpoints |
| `session.py` | FreeCAD session logic (geometry, booleans, export, FEM) |
| `models.py` | Typed Pydantic request/response models |
| `mcp_server.py` | MCP bridge — exposes the tools to MCP clients |
| `freecad_bridge.py` | Headless FreeCAD discovery/import helper |
| `AGENTS.md` / `CLAUDE.md` | Agent operating manual (identical content) |
| `elmer_*.py` | Standalone Elmer FEM tutorial runners |
| `tools/` | Client helper, test suite, integration-check hook, example scripts |
| `start.bat` / `start.sh` | Launchers (use FreeCAD's bundled Python) |

---

## License

[MIT](LICENSE).
