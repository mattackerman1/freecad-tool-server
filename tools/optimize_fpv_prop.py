#!/usr/bin/env python3
"""
Deterministic lightweight optimizer for a 3-inch FPV racing propeller.

The inner loop uses a cheap blade-element-style score plus beam stress
screening.  The optional --build-cad pass calls the local FreeCAD Tool Server
to loft the winning blade, polar-pattern it into a tri-blade prop, add the hub,
drill the bore, export STEP, and request a screenshot.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "fpv_prop_optimization"

RHO_AIR = 1.225
MU_AIR = 1.81e-5
SPEED_OF_SOUND = 343.0
RPM_DESIGN = 40_000
RPM_BURST = 55_000
OMEGA = 2 * math.pi * RPM_DESIGN / 60
OMEGA_BURST = 2 * math.pi * RPM_BURST / 60
VOLTAGE = 22.2

DIAMETER_MM = 76.2
R_TIP_M = DIAMETER_MM / 2000
R_ROOT_M = 0.0048
BLADE_COUNT = 3
HUB_RADIUS_MM = 6.0
HUB_HEIGHT_MM = 6.0
BORE_MM = 5.0

MATERIALS = {
    "gf_nylon": {"density": 1350.0, "uts_mpa": 110.0, "yield_mpa": 80.0},
    "polycarbonate": {"density": 1200.0, "uts_mpa": 65.0, "yield_mpa": 58.0},
}
MATERIAL = MATERIALS["gf_nylon"]


@dataclass
class Candidate:
    generation: int
    variant_id: str
    parent_id: str
    pitch_in: float
    root_chord_mm: float
    mid_chord_mm: float
    tip_chord_mm: float
    root_twist_deg: float
    mid_twist_deg: float
    tip_twist_deg: float
    root_tc_pct: float
    mid_tc_pct: float
    tip_tc_pct: float


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def interp3(x: float, y0: float, y1: float, y2: float) -> float:
    if x <= 0.5:
        return y0 + (y1 - y0) * (x / 0.5)
    return y1 + (y2 - y1) * ((x - 0.5) / 0.5)


def stations(c: Candidate) -> list[dict[str, float | str]]:
    rows = []
    for i in range(8):
        frac = i / 7
        r_m = R_ROOT_M + frac * (R_TIP_M - R_ROOT_M)
        chord = interp3(frac, c.root_chord_mm, c.mid_chord_mm, c.tip_chord_mm)
        twist = interp3(frac, c.root_twist_deg, c.mid_twist_deg, c.tip_twist_deg)
        tc = interp3(frac, c.root_tc_pct, c.mid_tc_pct, c.tip_tc_pct)
        rows.append({
            "r_mm": round(r_m * 1000, 3),
            "chord_mm": round(chord, 3),
            "twist_deg": round(twist, 3),
            "naca": "4408",
            "tc_pct": round(tc, 3),
        })
    return rows


def annulus_widths(r_vals: list[float]) -> list[float]:
    widths = []
    for i, r in enumerate(r_vals):
        if i == 0:
            widths.append((r_vals[1] - r) / 2)
        elif i == len(r_vals) - 1:
            widths.append((r - r_vals[-2]) / 2)
        else:
            widths.append((r_vals[i + 1] - r_vals[i - 1]) / 2)
    return widths


def airfoil(alpha_deg: float, chord_m: float, r_m: float) -> tuple[float, float, float]:
    reynolds = RHO_AIR * max(1.0, OMEGA * r_m) * chord_m / MU_AIR
    alpha_l0 = -3.5
    cl = 5.6 * math.radians(alpha_deg - alpha_l0)
    cl = clamp(cl, -0.4, 1.25)
    if alpha_deg > 15:
        cl *= max(0.35, 1 - (alpha_deg - 15) / 22)
    cd = 0.012 + 0.055 * cl * cl
    if reynolds < 50_000:
        cd *= (50_000 / max(10_000, reynolds)) ** 0.25
    return max(0.0, cl), max(0.008, cd), reynolds


def evaluate(c: Candidate) -> dict[str, Any]:
    st = stations(c)
    r_vals = [float(s["r_mm"]) / 1000 for s in st]
    drs = annulus_widths(r_vals)
    tip_speed = OMEGA * R_TIP_M
    tip_mach = tip_speed / SPEED_OF_SOUND

    thrust = 0.0
    torque = 0.0
    loads = []
    penalties = []

    for s, r_m, dr in zip(st, r_vals, drs):
        chord_m = float(s["chord_mm"]) / 1000
        beta = float(s["twist_deg"])
        vt = OMEGA * r_m
        va = 0.055 * tip_speed + 1.5
        w = math.hypot(vt, va)
        phi = math.degrees(math.atan2(va, vt))
        alpha = beta - phi
        cl, cd, reynolds = airfoil(alpha, chord_m, r_m)
        d_l = 0.5 * RHO_AIR * w * w * chord_m * cl
        d_d = 0.5 * RHO_AIR * w * w * chord_m * cd
        d_t = BLADE_COUNT * (d_l * math.cos(math.radians(phi)) - d_d * math.sin(math.radians(phi))) * dr
        d_q = BLADE_COUNT * r_m * (d_l * math.sin(math.radians(phi)) + d_d * math.cos(math.radians(phi))) * dr
        thrust += max(0.0, d_t)
        torque += max(0.0, d_q)
        loads.append({"r_m": r_m, "dr_m": dr, "dFn_N_per_m": max(0.0, d_l), "alpha_deg": alpha, "re": reynolds})
        if not -1 <= alpha <= 18:
            penalties.append(abs(alpha - clamp(alpha, -1, 18)) / 10)

    power = OMEGA * torque
    current = power / VOLTAGE

    blade_vol_m3 = 0.0
    inertia = 0.0
    min_t_mm = 99.0
    for s, r_m, dr in zip(st, r_vals, drs):
        chord_m = float(s["chord_mm"]) / 1000
        t_m = chord_m * float(s["tc_pct"]) / 100
        area_m2 = 0.68 * chord_m * t_m
        blade_vol_m3 += area_m2 * dr
        inertia += MATERIAL["density"] * area_m2 * dr * r_m * r_m * BLADE_COUNT
        min_t_mm = min(min_t_mm, t_m * 1000)

    hub_vol_mm3 = math.pi * HUB_RADIUS_MM**2 * HUB_HEIGHT_MM - math.pi * (BORE_MM / 2) ** 2 * HUB_HEIGHT_MM
    mass_g = (blade_vol_m3 * BLADE_COUNT * MATERIAL["density"] * 1000) + hub_vol_mm3 * MATERIAL["density"] / 1e6

    stress_rows = []
    min_sf = 999.0
    for i, s in enumerate(st):
        r_i = r_vals[i]
        c_m = float(s["chord_mm"]) / 1000
        t_m = c_m * float(s["tc_pct"]) / 100
        moment = 0.0
        for load in loads[i:]:
            arm = max(0.0, load["r_m"] - r_i)
            moment += load["dFn_N_per_m"] * load["dr_m"] * arm / BLADE_COUNT
        moment *= (RPM_BURST / RPM_DESIGN) ** 2
        z_section = c_m * t_m * t_m / 6
        sigma_bend = moment / max(1e-14, z_section) / 1e6
        area = 0.68 * c_m * t_m
        outboard_mass = 0.0
        for j, sj in enumerate(st[i:]):
            c_j = float(sj["chord_mm"]) / 1000
            t_j = c_j * float(sj["tc_pct"]) / 100
            outboard_mass += MATERIAL["density"] * 0.68 * c_j * t_j * drs[i + j]
        sigma_centrifugal = outboard_mass * OMEGA_BURST**2 * r_i / max(1e-10, area) / 1e6
        kt = 1.25 if i == 0 else 1.0
        sigma_peak = kt * sigma_bend + sigma_centrifugal
        sf = MATERIAL["uts_mpa"] / max(0.1, sigma_peak)
        min_sf = min(min_sf, sf)
        stress_rows.append({"station": i, "sigma_mpa": sigma_peak, "sf": sf})

    if tip_mach > 0.62:
        penalties.append((tip_mach - 0.62) * 20)
    if current > 34:
        penalties.append((current - 34) / 5)
    if min_t_mm < 0.45:
        penalties.append((0.45 - min_t_mm) * 6)
    if mass_g > 2.8:
        penalties.append((mass_g - 2.8) * 1.5)
    if min_sf < 2.0:
        penalties.append((2.0 - min_sf) * 3)

    thrust_per_watt = thrust / max(1.0, power)
    score = (
        12.0 * thrust
        + 850.0 * thrust_per_watt
        - 0.55 * current
        - 2.2 * mass_g
        - 18.0 * sum(penalties)
        - 800.0 * inertia
    )
    return {
        "candidate": asdict(c),
        "stations": st,
        "thrust_N": thrust,
        "torque_Nm": torque,
        "power_W": power,
        "current_A": current,
        "thrust_per_watt": thrust_per_watt,
        "tip_speed_mps": tip_speed,
        "tip_mach": tip_mach,
        "mass_g": mass_g,
        "inertia_kg_m2": inertia,
        "min_thickness_mm": min_t_mm,
        "min_safety_factor": min_sf,
        "stress": stress_rows,
        "constraint_pass": not penalties,
        "penalty": sum(penalties),
        "score": score,
    }


def random_candidate(rng: random.Random, generation: int, idx: int, parent_id: str = "") -> Candidate:
    return Candidate(
        generation=generation,
        variant_id=f"g{generation:02d}_{idx:03d}",
        parent_id=parent_id,
        pitch_in=rng.uniform(2.8, 3.8),
        root_chord_mm=rng.uniform(10.0, 14.0),
        mid_chord_mm=rng.uniform(9.0, 12.5),
        tip_chord_mm=rng.uniform(5.0, 7.8),
        root_twist_deg=rng.uniform(34.0, 46.0),
        mid_twist_deg=rng.uniform(20.0, 29.0),
        tip_twist_deg=rng.uniform(12.0, 18.5),
        root_tc_pct=rng.uniform(11.0, 16.0),
        mid_tc_pct=rng.uniform(8.5, 13.5),
        tip_tc_pct=rng.uniform(8.0, 13.0),
    )


def mutate(parent: Candidate, rng: random.Random, generation: int, idx: int) -> Candidate:
    def m(v: float, spread: float, lo: float, hi: float) -> float:
        return clamp(v + rng.gauss(0, spread), lo, hi)

    return Candidate(
        generation=generation,
        variant_id=f"g{generation:02d}_{idx:03d}",
        parent_id=parent.variant_id,
        pitch_in=m(parent.pitch_in, 0.10, 2.8, 3.8),
        root_chord_mm=m(parent.root_chord_mm, 0.45, 10.0, 14.5),
        mid_chord_mm=m(parent.mid_chord_mm, 0.45, 8.5, 13.0),
        tip_chord_mm=m(parent.tip_chord_mm, 0.35, 4.8, 8.0),
        root_twist_deg=m(parent.root_twist_deg, 1.2, 32.0, 48.0),
        mid_twist_deg=m(parent.mid_twist_deg, 1.0, 18.0, 30.0),
        tip_twist_deg=m(parent.tip_twist_deg, 0.8, 11.0, 19.0),
        root_tc_pct=m(parent.root_tc_pct, 0.7, 10.0, 17.0),
        mid_tc_pct=m(parent.mid_tc_pct, 0.6, 8.0, 14.5),
        tip_tc_pct=m(parent.tip_tc_pct, 0.5, 7.5, 14.0),
    )


def optimize(seed: int, generations: int, batch_size: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    all_results: list[dict[str, Any]] = []
    parents: list[Candidate] = []
    best_by_gen: list[float] = []

    for gen in range(generations):
        batch: list[Candidate] = []
        for idx in range(batch_size):
            if gen == 0 or not parents or idx < batch_size // 4:
                batch.append(random_candidate(rng, gen, idx))
            else:
                batch.append(mutate(rng.choice(parents), rng, gen, idx))
        scored = [evaluate(c) for c in batch]
        scored.sort(key=lambda row: row["score"], reverse=True)
        all_results.extend(scored)
        parents = [Candidate(**row["candidate"]) for row in scored[: max(4, batch_size // 4)]]
        best_by_gen.append(scored[0]["score"])

    all_results.sort(key=lambda row: row["score"], reverse=True)
    best = all_results[0]
    best["convergence"] = {
        "generations": generations,
        "batch_size": batch_size,
        "best_score_by_generation": best_by_gen,
        "last_3_improvement_pct": (
            100 * (max(best_by_gen[-3:]) - min(best_by_gen[-3:])) / max(1e-9, abs(max(best_by_gen[-3:])))
            if len(best_by_gen) >= 3 else None
        ),
    }
    return all_results, best


def post_json(base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def build_cad(best: dict[str, Any], base_url: str) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    step_path = OUT / "fpv_prop_3in_optimized.step"
    png_path = OUT / "fpv_prop_3in_optimized.png"
    log: list[dict[str, Any]] = []

    def call(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        result = post_json(base_url, path, payload)
        log.append({"path": path, "payload": payload, "result": result})
        if not result.get("success", True) and result.get("status") != "ok":
            raise RuntimeError(f"{path} failed: {result}")
        return result

    call("/document/create", {"name": "fpv_prop_3in_opt"})
    call("/shapes/add_propeller_blade", {
        "name": "blade",
        "stations": best["stations"],
        "rotation_axis": "z",
        "hub_offset_mm": 0,
    })
    call("/operations/polar_pattern", {
        "source_shape": "blade",
        "axis": "z",
        "count": BLADE_COUNT,
        "result_name": "blade_set",
    })
    call("/shapes/add_cylinder", {
        "name": "hub",
        "radius": HUB_RADIUS_MM,
        "height": HUB_HEIGHT_MM,
        "x": 0,
        "y": 0,
        "z": -HUB_HEIGHT_MM / 2,
        "axis": "z",
    })
    call("/operations/boolean_union", {
        "shape_a": "blade_set",
        "shape_b": "hub",
        "result_name": "prop_body",
    })
    call("/operations/make_hole", {
        "target_shape": "prop_body",
        "diameter": BORE_MM,
        "x": 0,
        "y": 0,
        "z": -HUB_HEIGHT_MM / 2,
        "axis": "z",
        "result_name": "prop_body",
    })
    call("/model/get_shape_info", {"shape_name": "prop_body"})
    call("/model/export_step", {"output_path": str(step_path)})
    call("/model/validate_step", {"step_path": str(step_path)})
    call("/model/screenshot", {
        "shape_name": "prop_body",
        "output_path": str(png_path),
        "view": "iso",
        "width": 1400,
        "height": 1000,
    })
    return {"step_path": str(step_path), "screenshot_path": str(png_path), "server_log": log}


def write_outputs(results: list[dict[str, Any]], best: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fields = [
        "generation", "variant_id", "parent_id", "score", "constraint_pass", "penalty",
        "thrust_N", "power_W", "current_A", "thrust_per_watt", "tip_mach",
        "mass_g", "inertia_kg_m2", "min_thickness_mm", "min_safety_factor",
        "root_chord_mm", "mid_chord_mm", "tip_chord_mm",
        "root_twist_deg", "mid_twist_deg", "tip_twist_deg",
        "root_tc_pct", "mid_tc_pct", "tip_tc_pct",
    ]
    with (OUT / "iteration_log.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in results:
            flat = {**row["candidate"], **{k: row[k] for k in row if k != "candidate"}}
            writer.writerow({key: flat.get(key) for key in fields})
    with (OUT / "best_design.json").open("w", encoding="utf-8") as fh:
        json.dump(best, fh, indent=2)
    with (OUT / "top_10.json").open("w", encoding="utf-8") as fh:
        json.dump(results[:10], fh, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generations", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=28)
    parser.add_argument("--seed", type=int, default=314159)
    parser.add_argument("--build-cad", action="store_true")
    parser.add_argument("--server", default="http://localhost:8000")
    args = parser.parse_args()

    results, best = optimize(args.seed, args.generations, args.batch_size)
    if args.build_cad:
        best["cad"] = build_cad(best, args.server)
    write_outputs(results, best)
    print(json.dumps({
        "output_dir": str(OUT),
        "best_variant": best["candidate"]["variant_id"],
        "score": round(best["score"], 3),
        "thrust_N": round(best["thrust_N"], 3),
        "power_W": round(best["power_W"], 1),
        "current_A": round(best["current_A"], 1),
        "mass_g": round(best["mass_g"], 3),
        "min_safety_factor": round(best["min_safety_factor"], 2),
        "constraint_pass": best["constraint_pass"],
        "cad": best.get("cad", {}),
    }, indent=2))


if __name__ == "__main__":
    main()
