# AGENTS.md — FreeCAD Tool Server: Agent Quickstart

> This file is the operating manual for any AI agent driving the FreeCAD tool server.
> It is intentionally named `AGENTS.md` (agent-agnostic). A copy is provided as
> `CLAUDE.md` so Claude Code picks it up automatically. Replace `<PROJECT_DIR>` with
> the absolute path where you cloned this repo.

This is an HTTP tool server that lets AI agents build 3D CAD geometry by calling REST endpoints. The server runs inside FreeCAD's bundled Python — not system Python.

---

## Setup

### Install dependencies (once)

```bat
"C:\Program Files\FreeCAD 1.1\bin\python.exe" -m pip install fastapi "uvicorn[standard]" "pydantic>=2.7"
```

### Start the server

```bat
cd <PROJECT_DIR>
start.bat
```

Server runs at **http://localhost:8000** · Swagger UI at **http://localhost:8000/docs**

### Health check

```
GET http://localhost:8000/health
```

Returns `{"success": true, "data": {"freecad_available": true, ...}}`.

---

## Every response has this envelope

```json
{
  "success": true,
  "message": "Human-readable summary",
  "data": { ... },
  "warnings": [],
  "errors": []
}
```

Always check `success` before using `data`. On failure, `errors[0]` contains the reason.

---

## Required first call

```
POST /document/create
{"name": "MyModel"}
```

**Every geometry tool requires an active document.** Call this before anything else.

---

## Core modeling loop

```
create_document
  → add primitives (add_box / add_cylinder / add_cone / add_wing)
  → boolean ops (boolean_union / boolean_cut / make_hole)
  → inspect (get_shape_info / bounding_box)
  → finish (fillet_edges / chamfer_edges)
  → export (export_step)
  → validate (validate_step)
```

---

## Most important endpoints

| Path | What it does |
|---|---|
| `POST /document/create` | Open a document (required first) |
| `POST /shapes/add_box` | Box primitive |
| `POST /shapes/add_cylinder` | Cylinder (`axis`: x/y/z) |
| `POST /shapes/add_wing` | NACA 4-digit airfoil loft |
| `POST /operations/boolean_union` | Fuse two shapes |
| `POST /operations/boolean_cut` | Subtract one shape from another |
| `POST /operations/make_hole` | Drill a cylindrical hole |
| `POST /operations/mirror` | Mirror across xy/xz/yz plane (case-insensitive) |
| `POST /operations/fillet_edges` | Round edges (`all`, `top`, `bottom`, `all_vertical`) |
| `POST /model/get_shape_info` | Volume, faces, edge count for a named shape |
| `POST /model/check_interference` | Intersection volume of two shapes — detects unwanted collisions or missing engagement |
| `POST /model/check_min_distance` | Minimum surface-to-surface gap — verifies clearances |
| `POST /model/screenshot` | PNG render of a shape or the whole document (base64 or file) |
| `GET /model/bounding_box` | Axis-aligned bounding box of all shapes |
| `POST /model/export_step` | Export named shape as STEP file |
| `POST /model/validate_step` | Import STEP, verify solid count + watertight |
| `POST /model/export_assembly` | Combine multiple STEP files into one assembly |
| `GET /document/status` | List all shapes in session |

Full endpoint list: see README.md or `/docs`.

---

## Common pitfalls

**Use FreeCAD's bundled Python, not system Python.**
`start.bat` handles this. If you run `python main.py` directly with system Python, FreeCAD imports will fail.

**Always call `create_document` first.**
All shape tools return 503 or a runtime error if there's no active document.

**Use absolute paths for STEP output, or ensure the output directory exists.**
`export_step` will fail if the parent directory doesn't exist. `C:\Users\...\output\` must be created first.

**Boolean tools must overlap the target by ≥ 1mm.**
Tangent-line contact (tool touching the surface exactly) is not enough — FreeCAD will produce either invalid geometry or zero volume removed. Push the tool 1–12mm inside the target.

**Check `volume_removed_mm3` after `boolean_cut`.**
If it's near zero (< 1% of target volume), a warning is returned. This means the cutter didn't intersect — reposition and retry.

**Edge selectors can fail on complex geometry.**
Valid selectors: `all`, `top`, `bottom`, `all_vertical`. After a fillet, edge topology changes — use `all` or call `get_shape_info` to count edges before selecting.

**Always pass `shape_name` to `export_step`.**
`export_step` without `shape_name` exports EVERY shape in the document — including leftover
cutters and witness solids — which makes `validate_step` report `solid_count > 1`. Pass the
final part's name: `{"output_path": "...", "shape_name": "body"}`.

**Validate exported STEP files.**
Always call `validate_step` after `export_step` and report the results. Aim for `is_clean == true` and `solid_count == 1`. If validation fails, make one attempt to fix it (e.g. `boolean_union` to merge multiple solids), then re-export and re-validate. If it still fails after one fix attempt, deliver the best result you have and note the issue in your final summary — do not loop endlessly trying to achieve perfect geometry.

**Shape names must be valid identifiers.**
Start with a letter or underscore; letters, digits, underscores, hyphens only. Max 64 chars.

---

## Mechanical integration checks (required after placing mating features)

Spatial errors in individual parts — bore holes in wrong positions, features that block mating parts — are invisible until you assemble them. Run integration checks after every `make_hole`, `add_cylinder` for a bore or boss, or `boolean_cut` for a pocket.

**The pattern:**

1. **Add witness geometry** — a temporary solid representing the mating part at its nominal installed position. Name it clearly: `screw_M4_witness`, `handlebar_witness`, `axle_witness`.

2. **Check engagement** (parts that must overlap):
   ```
   POST /model/check_interference
   {"shape_a": "bore_hole_region", "shape_b": "screw_M4_witness"}
   ```
   Pass if `interference_fraction_of_b > 0.8` (screw shank is ≥ 80% inside the bore).
   Fail if `interference_volume_mm3 < 0.1` — the screw misses the hole entirely.

3. **Check clearance** (parts that must not touch):
   ```
   POST /model/check_interference
   {"shape_a": "stem_body", "shape_b": "handlebar_witness"}
   ```
   Pass if `has_interference = false`.
   Also check minimum gap where tight clearance matters:
   ```
   POST /model/check_min_distance
   {"shape_a": "clamp_bolt_head", "shape_b": "handlebar_witness", "required_clearance_mm": 1.0}
   ```
   A `warnings` list is returned if the gap is below `required_clearance_mm`.

4. **Remove witness solids** before export — use `boolean_cut` if the witness was added to the document, or just don't export them (use the shape name in `export_step`, not `export_assembly`).

**When to run checks** (required, not optional):
- After every `make_hole` — verify screw or shaft witness overlaps the hole
- After every pocket (`boolean_cut`) — verify the intended insert fits
- After placing any clamping or retention feature — verify it doesn't block the clamped part
- Before `export_step` on any assembly-facing part

**Iterate on failure:** if a check fails, correct the position or dimension of the feature and re-run. Do not export a part with a failing integration check.

---

## In-place boolean update (key pattern)

You can reuse the same name as `result_name` to update a shape without juggling intermediate names:

```json
POST /operations/boolean_cut
{"target_shape": "body", "tool_shape": "pocket", "result_name": "body"}
```

This works because geometry is computed before the old object is removed. The `_get_obj` Label fallback handles FreeCAD's internal name auto-increment.

---

## Multi-agent builds

The session is a singleton. For multi-part builds, run agents **sequentially** — each agent calls `create_document` first and exports to its own STEP file. Then combine with `export_assembly`.

---

## Python client (stdlib, no extra deps)

See `tools/freecad_client.py` for a ready-to-use helper. Quick version:

```python
import urllib.request, json

BASE = "http://localhost:8000"

def tool(method, path, **body):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, data=data,
          headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    if not result["success"]:
        raise RuntimeError(result["errors"])
    return result["data"]

tool("POST", "/document/create", name="test")
tool("POST", "/shapes/add_box", name="b", length=50, width=30, height=10)
info = tool("POST", "/model/get_shape_info", shape_name="b")
print(info["volume_mm3"])  # 15000.0
```
