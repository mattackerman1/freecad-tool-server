# FW-1000 Fixed Wing Drone — Design Specification

## Coordinate System
- **X axis**: nose (−) to tail (+), nose tip at x=−80
- **Y axis**: right wing tip (starboard), fuselage centerline at y=0
- **Z axis**: up, fuselage centerline at z=0

## Overall Dimensions
| Param | Value |
|---|---|
| Total length (nose tip → tail) | 800mm (x=−80 to x=720) |
| Wingspan | 1000mm (±500mm each side) |
| Max fuselage diameter | 65mm (r=32.5) |
| Configuration | Pusher motor (rear) |

---

## Component 1 — Fuselage
**File:** `output/drone_fuselage.step`
**Agent:** Fuselage Agent

| Feature | Value |
|---|---|
| Main body | Hollow cylinder r=32.5, wall=3mm, x=0 → x=580 |
| Nose cone | Solid, r1=4 → r2=32.5, 80mm, x=−80 |
| Tail cone | Solid, r1=32.5 → r2=12, 80mm, x=580 |
| Tail boom | Solid cylinder r=12, 60mm, x=660 |
| Electronics hatch | Box cutout top: 120×60×4mm at x=60, z=29 |
| Fillet nose/body join | r=3mm |

---

## Component 2 — Wings (both)
**File:** `output/drone_wings.step`
**Agent:** Wing Agent

| Feature | Value |
|---|---|
| Root leading edge position | x=220, y=±32.5 (fuselage surface) |
| Root chord | 150mm |
| Tip chord | 100mm |
| Half span | 500mm per side |
| Airfoil | NACA 2412 (12% thickness, 2% camber at 40%) |
| Thickness at root | ~18mm (12% of 150) |
| Thickness at tip | ~12mm (12% of 100) |
| Sweep (leading edge) | 5° aft |
| Dihedral | 3° |
| Span direction | Right: +Y from y=32.5; Left: mirror across XZ |
| Aileron span | Outer 35% of span (y=357 to y=532) |
| Aileron chord | 25% of local chord |

---

## Component 3 — Tail Assembly
**File:** `output/drone_tail.step`
**Agent:** Tail Agent

### Horizontal Stabilizer
| Feature | Value |
|---|---|
| Root LE position | x=600, y=±12 |
| Root chord | 100mm |
| Tip chord | 70mm |
| Half span | 220mm per side |
| Airfoil | NACA 0009 (symmetric, 9% thickness) |
| Elevator cutout | Rear 35% of chord, full span |

### Vertical Stabilizer
| Feature | Value |
|---|---|
| Root LE position | x=585, z=32.5 |
| Chord | 100mm |
| Height | 100mm |
| Airfoil | NACA 0009 (symmetric, 9% thickness) |
| Rudder cutout | Rear 35% of chord, full height |

---

## Component 4 — Propulsion
**File:** `output/drone_propulsion.step`
**Agent:** Propulsion Agent

| Feature | Value |
|---|---|
| Motor housing | Cylinder r=20, 32mm long at x=660 |
| Motor collar/flange | Cylinder r=28, 6mm thick at x=660 |
| Tail boom interface | Hollow cylinder r=12, wall=2mm (fits over boom) |
| Propeller disk | Cylinder r=100 (8" = 203mm dia), 4mm thick at x=692 |
| Spinner cone | Cone r1=0→r2=12, 20mm at x=672 |

---

## Assembly
**File:** `output/drone_assembly.step`

All components combine into one multi-body STEP file via `export_assembly`.
Parts must not intersect unexpectedly. Wing roots overlap fuselage by 4mm for watertight union.

---

## Manufacturing Readiness Criteria
- [ ] Each component STEP: `is_clean=True`, `solid_count=1` (or expected count for assembly)
- [ ] Minimum wall thickness ≥ 3mm everywhere
- [ ] No zero-thickness faces
- [ ] All fillets applied at joints
- [ ] Assembly: all parts positionally consistent (no floating parts)
