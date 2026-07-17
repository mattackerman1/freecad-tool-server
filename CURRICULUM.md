# FreeCAD Tool Server — Agent Tutorial Curriculum

A progressive curriculum of modeling tasks, ordered from absolute beginner to expert.
Each tutorial is a self-contained task the Sub-Agent must complete using only the
FreeCAD Tool Server tools. Later tutorials depend on capabilities unlocked by earlier
improvement loop iterations.

---

## Level 1 — Beginner
*Requires: Phase 0 tools only (create_document, add_box, add_cylinder, get_bounding_box, export_step)*

---

### Tutorial 1.1 — Hello Cube
**Goal:** Confirm the server is alive and the agent can create and export a single primitive.

- Create document "hello_cube"
- Add a 20×20×20mm cube named "cube"
- Query the bounding box and confirm it is 20×20×20
- Export as `hello_cube.step`

**Success criteria:** STEP file exists. Bounding box exactly 20×20×20mm.

---

### Tutorial 1.2 — Stacked Blocks
**Goal:** Place multiple primitives in specific spatial relationships.

- Create document "stacked_blocks"
- Add a base block: 60×40×10mm at origin
- Add a middle block: 40×30×10mm centered on top of the base (x=10, y=5, z=10)
- Add a top block: 20×20×10mm centered on top of the middle (x=20, y=10, z=20)
- Verify total bounding box is 60×40×30mm
- Export as `stacked_blocks.step`

**Success criteria:** Three shapes. Bounding box 60×40×30mm. STEP contains 3 bodies.

---

### Tutorial 1.3 — Cylinder Tower
**Goal:** Combine boxes and cylinders in a simple assembly.

- Create document "cylinder_tower"
- Add a square base plate: 50×50×5mm at origin
- Add a cylinder shaft: radius=8mm, height=40mm centered on the plate (x=25, y=25, z=5)
- Add a cylinder cap: radius=15mm, height=5mm at the top of the shaft (x=25, y=25, z=45)
- Verify shape count = 3, total height = 50mm
- Export as `cylinder_tower.step`

**Success criteria:** Three shapes. Z-max = 50mm. STEP file valid.

---

### Tutorial 1.4 — Bounding Box Reasoning
**Goal:** Use bounding box output to verify geometric reasoning before export.

- Create document "bbox_check"
- Add box A: 100×10×10mm at origin
- Add box B: 10×100×10mm at origin
- Query the bounding box — agent must predict and confirm it is 100×100×10mm before proceeding
- If bounding box does not match prediction, do not export and report the discrepancy
- If it matches, export as `bbox_check.step`

**Success criteria:** Agent correctly predicts the bounding box AND exports only when confirmed.

---

## Level 2 — Intermediate
*Requires: Phase 1 tools (make_hole, boolean_cut, fillet_edges)*

---

### Tutorial 2.1 — Simple Mounting Plate ✅ COMPLETE
**Goal:** First real mechanical part with holes and fillets.

- Create document "mounting_plate_v1"
- Base plate: 80×50×6mm
- Four M4 holes (dia=8mm) at 10mm from each corner
- One central cable hole: dia=20mm at center (40, 25)
- Fillet all four vertical edges: r=3mm
- Export as `mounting_plate_v1.step`

**Success criteria:** Single solid body. Volume ≈ 20,862 mm³. Five holes present. Fillets applied.

---

### Tutorial 2.2 — Standoff Spacer
**Goal:** A hollow cylinder (tube) created via boolean subtraction.

- Create document "standoff_spacer"
- Add outer cylinder: radius=8mm, height=20mm at origin
- Add inner bore cylinder: radius=5mm, height=20mm at origin
- Use boolean_cut to subtract inner from outer → result named "spacer"
- Verify volume ≈ π×(8²−5²)×20 ≈ 2,450 mm³
- Export as `standoff_spacer.step`

**Success criteria:** Single body. Wall thickness = 3mm. Volume within 1% of theoretical.

---

### Tutorial 2.3 — L-Bracket
**Goal:** Build an L-shaped bracket from two boxes and add mounting holes.

- Create document "l_bracket"
- Vertical leg: 6×50×60mm at origin
- Horizontal leg: 6×50×40mm at (6, 0, 0) — butting against the vertical leg
- Add two M5 holes (dia=5.5mm) in the vertical leg at (3, 25, 15) and (3, 25, 45)
- Add two M5 holes in the horizontal leg at (25, 25, 3) and (45, 25, 3)
- Fillet the outer corner edge (the long edge where legs would meet): r=2mm
- Export as `l_bracket.step`

**Notes for agent:** Vertical and horizontal legs are separate bodies — no boolean union yet.
The four holes must be drilled into the correct leg body.

**Success criteria:** Two bodies (or one if union available). Four holes total. STEP valid.

---

### Tutorial 2.4 — Pocketed Block
**Goal:** Create a shallow rectangular pocket in a solid block using boolean_cut.

- Create document "pocketed_block"
- Base block: 80×60×20mm
- Create a pocket tool box: 60×40×12mm positioned at (10, 10, 8) — this leaves 8mm floor
- Use boolean_cut to subtract the pocket from the base
- Verify volume = (80×60×20) − (60×40×12) = 96,000 − 28,800 = 67,200 mm³
- Fillet the four vertical edges of the outer block: r=3mm
- Export as `pocketed_block.step`

**Success criteria:** Single body with interior pocket. Volume within 1% of 67,200 mm³.

---

### Tutorial 2.5 — Hex Nut Approximation
**Goal:** Multi-step boolean to approximate a hex nut shape (tests iterative subtraction).

- Create document "hex_nut"
- Start with a cylinder: radius=12mm, height=8mm (the hex blank)
- Cut a through-hole bore: dia=10mm at center (0, 0, 0)
- Cut six flat sides by subtracting thin rectangular slabs around the perimeter
  (each slab 4×30×8mm, rotated 0°/60°/120° — use boolean_cut with box tools)
- Export as `hex_nut.step`

**Notes for agent:** This tutorial tests whether the agent can decompose a geometry into
a sequence of boolean operations. Rotation support may not be available — the agent
should note any limitations and approximate as best it can.

**Success criteria:** Through-hole present. Some material removed from sides. STEP valid.
Partial credit if rotation not available.

---

## Level 3 — Advanced
*Requires: Phase 2 tools (boolean_union, chamfer, linear_pattern, shell, or equivalent)*

---

### Tutorial 3.1 — Flanged Pipe Connector
**Goal:** Build a pipe connector with a flange using union + holes.

- Create document "pipe_connector"
- Flange disk: outer radius=30mm, height=8mm, centered at origin — then bore out center dia=20mm
- Pipe tube: outer radius=12mm, height=50mm at center — bore out center dia=20mm
- Union the flange and pipe into one body
- Add four M4 bolt holes (dia=4.5mm) through the flange at radius=22mm from center,
  at 0°, 90°, 180°, 270° positions
- Export as `pipe_connector.step`

**Rigorous success criteria:**
- `shape_count == 1` — union must produce a single body, not two touching bodies
- `BBox == 60×60×50mm ±0.1mm` — flange diameter 2×30=60mm dominates XY; pipe height=50mm in Z
- `volume ∈ [25,149 – 25,657 mm³] (±1% of 25,403mm³)` — computed as:
  - Flange ring: π×(30²−10²)×8 = 20,106mm³
  - Pipe ring: π×(12²−10²)×50 = 6,912mm³
  - Union overlap (pipe annulus in flange zone): π×(12²−10²)×8 = 1,106mm³
  - Subtotal after union: 25,912mm³
  - 4 bolt holes dia=4.5mm through h=8mm: 4×π×2.25²×8 = 509mm³
  - **Expected: 25,403mm³**
- `z_max == 50mm ±0.1mm` — pipe height determines total Z
- `z_min == 0mm ±0.1mm` — flange base at origin
- Bore continuity: volume must be < 26,000mm³ confirming bore was subtracted

---

### Tutorial 3.2 — Gearbox Cover Plate
**Goal:** Complex plate with a pattern of holes and a raised boss.

- Create document "gearbox_cover"
- Base plate: 120×100×5mm
- Central boss (raised cylinder): radius=20mm, height=8mm centered at (60, 50, 5)
- Central bore through boss and plate: dia=30mm at (60, 50, 0)
- Eight M3 bolt holes (dia=3.5mm) in a bolt circle: radius=40mm from center (60,50), evenly spaced at 45° intervals
- Four corner mounting holes: dia=5mm at (10,10), (110,10), (10,90), (110,90), depth through plate (z=0)
- Fillet all outer vertical plate edges: r=4mm
- Export as `gearbox_cover.step`

**Rigorous success criteria:**
- `shape_count == 1` — boss must be unioned into plate, not a separate body
- `BBox == 120×100×13mm ±0.1mm` — plate 5mm + boss 8mm = 13mm total height
- `volume ∈ [59,452 – 60,722mm³] (±1% of 60,087mm³)` — computed as:
  - Plate: 120×100×5 = 60,000mm³
  - Boss: π×20²×8 = 10,053mm³; total before bore: 70,053mm³
  - Central bore dia=30 through full 13mm: π×15²×13 = 9,189mm³
  - 8 bolt holes dia=3.5mm, depth=5mm (plate only, radius=40 > boss radius=20): 8×π×1.75²×5 = 385mm³
  - 4 corner holes dia=5mm, depth=5mm: 4×π×2.5²×5 = 393mm³
  - **Expected before fillets: 60,086mm³** (fillets remove ≈70mm³ → ~60,017mm³; use ±1% band)
- `z_max == 13mm ±0.1mm` — confirms boss height (5+8)
- Volume drop from unfilleted estimate must be < 500mm³ — confirms fillets are edge-only, not excessive

---

### Tutorial 3.3 — Enclosure Shell
**Goal:** Create a hollow box (enclosure) using boolean subtraction.

- Create document "enclosure"
- Outer box: 100×80×50mm
- Inner void tool: 94×74×46mm at (3, 3, 4) — 3mm side walls, 4mm floor, open top
- Boolean_cut inner from outer → open-top shell
- Union four interior corner bosses (cylinders radius=4mm, height=42mm) at (8,8,4), (8,66,4), (88,8,4), (88,66,4)
- Bore M3 tapped holes (dia=2.5mm) through each boss axis (z-direction, depth=42mm)
- Fillet outer top rim edges (selector: `top`): r=2mm
- Export as `enclosure.step`

**Rigorous success criteria:**
- `shape_count == 1` — shell + all bosses merged into one body
- `BBox == 100×80×50mm ±0.1mm` — outer dimensions unchanged
- `volume ∈ [86,979 – 88,535mm³] (±1% of 87,757mm³)` — computed as:
  - Outer box: 100×80×50 = 400,000mm³
  - Inner void: 94×74×46 = 319,864mm³; shell after cut: 80,136mm³
  - 4 bosses: 4×π×4²×42 = 8,444mm³; total after union: 88,580mm³
  - 4 boss bores dia=2.5mm, depth=42mm: 4×π×1.25²×42 = 824mm³
  - **Expected before rim fillet: 87,756mm³** (rim fillet removes small amount ≈ -?)
- `x_min==0, y_min==0, z_min==0, x_max==100, y_max==80, z_max==50` all ±0.1mm
- Boss bores confirmed by volume < 88,580mm³ (volume after adding bosses)
- Wall thickness implied: if BBox==100 and inner void starts at x=3, wall=3mm ✓ (enforced by volume check)

---

### Tutorial 3.4 — Parametric Bracket Family
**Goal:** Produce three variants of a bracket using a repeatable workflow.

Create three separate STEP files. Each bracket: rectangular plate with 4 through-holes (2 per long edge).

| Variant | Base (L×W×H) | Hole dia | Hole offset from short edge | Hole offset from long edge | Fillet r |
|---|---|---|---|---|---|
| Small  | 40×30×4mm  | 4mm | 10mm | 10mm | 2mm |
| Medium | 80×50×6mm  | 6mm | 12mm | 12mm | 3mm |
| Large  | 120×80×8mm | 8mm | 15mm | 15mm | 4mm |

Hole positions (each bracket, holes in all 4 corners at the specified offsets):
- Small: (10,10), (30,10), (10,20), (30,20) — x offset 10mm from short ends, y offset 10mm from long edges
- Medium: (12,12), (68,12), (12,38), (68,38)
- Large: (15,15), (105,15), (15,65), (105,65)

**Rigorous success criteria (all three files must pass):**

| Check | Small | Medium | Large |
|---|---|---|---|
| `shape_count` | 1 | 1 | 1 |
| `BBox x_size` | 40mm ±0.1 | 80mm ±0.1 | 120mm ±0.1 |
| `BBox y_size` | 30mm ±0.1 | 50mm ±0.1 | 80mm ±0.1 |
| `BBox z_size` | 4mm ±0.1 | 6mm ±0.1 | 8mm ±0.1 |
| `volume` | 4,599 ±46mm³ | 23,321 ±233mm³ | 75,192 ±752mm³ |
| STEP file exists | ✓ | ✓ | ✓ |

Volume formulas:
- Small: 40×30×4 − 4×π×2²×4 = 4,800 − 201 = **4,599mm³**
- Medium: 80×50×6 − 4×π×3²×6 = 24,000 − 679 = **23,321mm³**
- Large: 120×80×8 − 4×π×4²×8 = 76,800 − 1,608 = **75,192mm³**
(Fillet volumes are small and included in ±1% tolerance)

---

## Level 4 — Expert
*Requires: Phase 3+ tools (sketch-based extrusion, loft, sweep, constraints, or equivalent)*

---

### Tutorial 4.1 — Routed Cable Channel
**Goal:** Create a body with a continuous internal channel along its full length.

- Create document "cable_channel"
- Outer body: 200×30×20mm box
- Route a cylindrical cable channel: diameter=16mm (radius=8mm), along the full X-axis length
- Channel center at (0, 15, 10) — horizontally and vertically centered in the cross-section
- The channel must enter and exit both end faces (x=0 and x=200)
- Export as `cable_channel.step`

**Rigorous success criteria:**
- `shape_count == 1`
- `BBox == 200×30×20mm ±0.1mm` — outer body dimensions unchanged
- `volume ∈ [79,388 – 80,188mm³] (±0.5% of 79,788mm³)` — computed as:
  - Outer body: 200×30×20 = 120,000mm³
  - Cylindrical bore dia=16mm, length=200mm: π×8²×200 = 40,212mm³
  - **Expected: 79,788mm³**
- Channel axis confirmed: if volume ≠ 120,000mm³, some material was removed → channel exists
- Channel continuity confirmed: BBox x_size still = 200mm (body not split)
- Channel centering: bore at (y=15, z=10) must be fully inside the body — radius=8mm < min(15,10) ✓

---

### Tutorial 4.2 — Swept Handle Grip
**Goal:** Create an ergonomic grip shape along a curved path with solid mounting flanges.

- Create document "grip"
- Define an arc spine: start=(0,0,0), mid=(50,30,0), end=(100,0,0) — 122.5mm arc length
- Sweep a 20×10mm rectangular cross-section along the spine → grip body
- Union two mounting flanges (40×40×20mm boxes):
  - Flange A: length=20 in X, x from −20 to 0, face centered at (0,0) in YZ → fully encloses arc start
  - Flange B: length=20 in X, x from 100 to 120, face centered at (100,0) in YZ → fully encloses arc end
  - **Critical:** Flanges must be ≥15mm thick in X — the arc tangent at each endpoint is ~(0.882, ±0.471, 0), so the 20mm-wide cross-section projects ~8.8mm onto the X axis. Flanges thinner than this create a visible notch where the grip exits the flange face.
- Export as `grip.step`

**Rigorous success criteria:**
- `shape_count == 1` — flanges must be unioned into grip body
- `BBox x_size ∈ [115–145mm]` — 100mm arc + 20mm each flange
- `BBox y_size ≥ 40mm` — flanges are 40mm wide in Y
- `BBox z_size ≥ 40mm` — flanges are 40mm tall in Z
- `volume > 10,000mm³` — grip ~11,500mm³ + two 40×40×20mm flanges (minus overlap)
- **Flange solidity check (structural):** Drill 8mm-diameter bore through center of each flange (depth=20mm, axis=X). Volume removed must equal π×4²×20 = 1,005.3mm³ ±5% (50mm³). If the flange is notched at the grip exit, the bore removes less material than expected.
- `STEP file exists and is_valid`

---

### Tutorial 4.3 — Lattice Infill Panel
**Goal:** Subtract a precise 5×4 grid of holes from a panel.

- Create document "lattice_panel"
- Base plate: 150×100×6mm
- Create a 5×4 grid of 8mm-diameter through-holes on a 25mm pitch:
  - Row 1–4 centers at y = 12.5, 37.5, 62.5, 87.5
  - Column 1–5 centers at x = 12.5, 37.5, 62.5, 87.5, 112.5
  - All at z=0 (through-holes in Z)
- Fillet all four outer vertical edges: r=4mm
- Export as `lattice_panel.step`

**Rigorous success criteria:**
- `shape_count == 1`
- `BBox == 150×100×6mm ±0.1mm`
- `volume ∈ [83,046 – 84,724mm³] (±1% of 83,885mm³)` — computed as:
  - Base plate: 150×100×6 = 90,000mm³
  - 20 holes dia=8mm, depth=6mm: 20×π×4²×6 = 6,032mm³; after holes: 83,968mm³
  - 4 corner fillets r=4mm, height=6mm: 4×(4²−π×4²/4)×6 = 4×3.43×6 = 82mm³
  - **Expected: 83,886mm³**
- Spot-check hole positions: volume difference between base and result must equal 20×π×16×6 = 6,032mm³ ±60mm³ (1% tolerance on hole volume)
- Confirm 5×4 = 20 holes: any fewer means pattern failed; any more means geometry error

---

### Tutorial 4.4 — Multi-Body Assembly Export
**Goal:** Produce a two-body STEP file: a clevis bracket and a pin.

- Create document "pin_joint"
- **Body 1 — clevis:**
  - Ear 1: 10×6×30mm box at (0, 0, 0)
  - Ear 2: 10×6×30mm box at (0, 22, 0) — 16mm gap between ears
  - Bridge: 10×16×10mm box at (0, 6, 20) — connects ears at top
  - Union all three into one clevis body
  - Bore 10mm holes through both ears in Y direction, centered at (5, 0, 15)
- **Body 2 — pin:**
  - Cylinder radius=4.9mm, height=28mm, axis=Y, at (5, 0, 15) — sitting in the ear holes
  - Chamfer both circular ends: 0.5mm
- Export as `pin_joint.step`

**Rigorous success criteria:**
- `shape_count == 2` — exactly two bodies, confirmed by status endpoint
- **Clevis checks:**
  - `clevis BBox ≈ 10×28×30mm ±0.5mm` (X: ear width=10, Y: 6+16+6=28, Z: ear height=30)
  - `clevis volume ∈ [4,015 – 4,500mm³]` — computed as:
    - 3 boxes unioned: ear1(1,800) + ear2(1,800) + bridge(1,600) = 5,200mm³
    - 2 ear bores dia=10mm, depth=6mm each: 2×π×5²×6 = 942mm³
    - **Expected: 4,258mm³**
- **Pin checks:**
  - `pin volume ∈ [2,050 – 2,150mm³]` — computed as:
    - Cylinder: π×4.9²×28 = 2,114mm³ minus chamfer material ≈ 14mm³ → ~2,100mm³
  - `pin BBox y_size == 28mm ±0.1mm` — confirms correct axis orientation
  - `pin BBox x_size ∈ [9.7–9.9mm]` — confirms radius ≈ 4.9mm (diameter ≈ 9.8mm)
- Pin diameter (9.8mm) < hole diameter (10mm) — pin fits through ears ✓ (clearance = 0.2mm)

---

### Tutorial 4.5 — Reverse Engineering Replication
**Goal:** Replicate an M6 hex socket cap screw head to DIN 912 spec using only tool server primitives.

Spec:
- Head outer diameter: 10mm (radius=5mm)
- Head height: 6mm
- Hex socket: 5mm across-flats (AF), 4mm deep — use 6 rotated slab cuts as in Tutorial 2.5
- Chamfer on outer top edge: 0.6mm × 45°

**Build sequence:**
1. Cylinder r=5mm, h=6mm → head blank
2. Hex socket: circumradius = AF/(√3) = 5/1.732 = 2.887mm; inradius = AF/2 = 2.5mm
   - Cut 6 slabs (30×30×4mm) at angles 0°,60°,120°,180°,240°,300° into the top 4mm
   - Entry point z=2 (socket is top 4mm of 6mm head); slabs cut from above into z=2..6
3. Chamfer top outer edge: r=5mm circle, 0.6mm chamfer
4. Export as `m6_cap_head.step`

**Rigorous success criteria:**
- `shape_count == 1`
- `BBox x_size ≤ 10.1mm AND y_size ≤ 10.1mm` — head diameter must not exceed spec
- `BBox z_size == 6mm ±0.1mm` — head height exactly 6mm
- `volume ∈ [363 – 404mm³] (±5% of 384mm³)` — computed as:
  - Head cylinder: π×5²×6 = 471mm³
  - Hex socket (AF=5mm, depth=4mm): hexagon area × depth = (√3/2×AF²)×4 = (√3/2×25)×4 = 86.6mm³
  - Top chamfer 0.6mm: ≈ π×(5²−4.4²)×0.6÷2 ≈ 5mm³
  - **Expected: 471 − 87 − 5 = 379mm³**; use ±5% band = [360–398mm³]
- `volume < 471mm³` — confirms socket was subtracted (blank would be 471mm³)
- `volume < 385mm³` — confirms socket volume removed is at least 50mm³ (meaningful socket depth)
- Hex socket presence: volume must be at least 50mm³ less than the blank cylinder (471mm³)

---

## Curriculum Progress Tracker

| Tutorial | Status | Score | Notes |
|---|---|---|---|
| 1.1 Hello Cube | ✅ PASSED | 10/10 | Phase 0 tools. Required creating output/ dir. |
| 1.2 Stacked Blocks | ✅ PASSED | 10/10 | 3 shapes, bbox 60×40×30mm ✓ |
| 1.3 Cylinder Tower | ✅ PASSED | 10/10 | Mixed box+cylinder, z_max=50 ✓ |
| 1.4 Bounding Box Reasoning | ✅ PASSED | 10/10 | Agent predicted 100×100×10, confirmed before export |
| 2.1 Simple Mounting Plate | ✅ PASSED | 10/10 | First passing tutorial (Improvement Loop Iter 2) |
| 2.2 Standoff Spacer | ✅ PASSED | 10/10 | Vol=2450.4mm³ (theory=2450.4) — 0.00% error |
| 2.3 L-Bracket | ✅ PASSED | 10/10 | Added make_hole axis param; X+Z holes, dual-body STEP |
| 2.4 Pocketed Block | ✅ PASSED | 10/10 | Vol=67200mm³ exact ✓ |
| 2.5 Hex Nut Approximation | ✅ PASSED | 10/10 | Added rotation_z to add_box; 6 hex flats, vol=2364.48mm³ |
| 3.1 Flanged Pipe Connector | ✅ PASSED | 10/10 | vol=25,402.9mm³ (0.001% err); BBox 60×60×50 ✓ |
| 3.2 Gearbox Cover Plate | ✅ PASSED | 10/10 | vol=60,017.7mm³ (0.12% err); BBox 120×100×13 ✓; 12 holes confirmed |
| 3.3 Enclosure Shell | ✅ PASSED | 10/10 | vol=87,494.6mm³ (0.30% err); BBox 100×80×50 ✓; fillet per-edge fallback fixed |
| 3.4 Parametric Bracket Family | ✅ PASSED | 10/10 | All 3 variants within 0.30% vol; exact BBox; 4 holes each ✓ |
| 4.1 Routed Cable Channel | ✅ PASSED | 10/10 | vol=79,787.6mm³ (0.00% err); BBox 200×30×20 ✓ |
| 4.2 Swept Handle Grip | ✅ PASSED | 10/10 | True arc sweep 122.5mm; 40×40×20mm flanges fully solid (bore check 0% err); vol=73,029mm³ BBox 140×55×40 ✓ |
| 4.3 Lattice Infill Panel | ✅ PASSED | 10/10 | vol=83,885.7mm³ (0.00% err); 20×π×16×6=6031.9mm³ removed confirmed |
| 4.4 Multi-Body Assembly | ✅ PASSED | 10/10 | Clevis 4,257.5mm³ (0.01% err); Pin 2,104.6mm³; pin-fits-ears clearance ✓ |
| 4.5 Reverse Engineering | ✅ PASSED | 10/10 | vol=375.8mm³ (0.83% err); fixed geometry via 2-step hex prism tool |

**18 / 18 tutorials fully passed.**

---

## Tools Added During Curriculum

| Tool | Endpoint | Added For |
|---|---|---|
| `boolean_cut` | `POST /operations/boolean_cut` | Tutorial 2.1 (holes) |
| `make_hole` | `POST /operations/make_hole` | Tutorial 2.1 |
| `fillet_edges` | `POST /operations/fillet_edges` | Tutorial 2.1 |
| `make_hole axis param` | (improvement to make_hole) | Tutorial 2.3 (X-direction holes) |
| `add_box rotation_z` | (improvement to add_box) | Tutorial 2.5 (hex flats) |
| `boolean_union` | `POST /operations/boolean_union` | Tutorial 3.1 (pipe+flange) |
| `linear_pattern` | `POST /operations/linear_pattern` | Tutorial 4.3 (hole grid) |
| `add_cylinder axis param` | (improvement to add_cylinder) | Tutorial 4.4 (X-axis pin) |
| `chamfer_edges` | `POST /operations/chamfer_edges` | Tutorial 4.5 (fastener dome) |

---

*All 18 tutorials complete. Sweep/loft implemented via `POST /paths/create_arc`, `POST /profiles/rect`, `POST /operations/sweep`.*
