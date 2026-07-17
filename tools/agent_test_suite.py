"""
Agent test suite — cadAI
========================
Runs graded build tasks through the agent runner and scores the results.

Usage:
    python tools/agent_test_suite.py            # run all tests
    python tools/agent_test_suite.py 3          # run test #3 only

Requires both servers running (tool server :8000, agent runner :8080).
Uses the free-tier server key unless CADAI_TEST_API_KEY is set.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

RUNNER = "http://localhost:8080"
API_KEY = os.environ.get("CADAI_TEST_API_KEY", "")

TESTS = [
    {
        "name": "simple box",
        "description": "Create a rectangular box 40 x 20 x 10 mm and export it.",
        "min_volume": 7500, "max_volume": 8500,   # 8000 nominal
    },
    {
        "name": "concave cube",
        "description": "Create a cube with 30 mm sides where every face is concave (dished inward).",
        "min_volume": 8000, "max_volume": 26500,  # must be < 27000 (material removed) but > cube shell
    },
    {
        "name": "plate with bolt holes",
        "description": (
            "Create a mounting plate 60 x 40 x 5 mm with four M4 clearance holes "
            "(4.5 mm diameter), one 8 mm from each corner."
        ),
        "min_volume": 10500, "max_volume": 12000,  # 12000 minus 4 holes (~318)
    },
    {
        "name": "filleted cylinder boss",
        "description": (
            "Create a cylindrical boss: 30 mm diameter, 15 mm tall, on a 50 x 50 x 5 mm "
            "base plate, with the top edge of the boss filleted 2 mm. One unified solid."
        ),
        "min_volume": 20000, "max_volume": 24000,
    },
    {
        "name": "L-bracket with pocket",
        "description": (
            "Create an L-bracket: vertical wall 50 x 50 x 6 mm joined to a horizontal "
            "base 50 x 50 x 6 mm, with a 20 x 20 x 3 mm pocket cut into the center of "
            "the base's top surface. Verify the pocket with an interference check."
        ),
        "min_volume": 20000, "max_volume": 30000,
    },
    {
        "name": "follow-up modification",
        "description": "Add a 10 mm diameter hole through the center of the part.",
        "context": (
            "Previously built: a rectangular plate 60 x 40 x 5 mm, exported as plate.step. "
            "Volume 12000 mm3, validated clean."
        ),
        "min_volume": 10000, "max_volume": 12000,
    },
]


def run_test(idx: int, test: dict) -> dict:
    body = {
        "description": test["description"],
        "api_key": API_KEY,
        "context": test.get("context", ""),
    }
    req = urllib.request.Request(
        RUNNER + "/run", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        result = json.loads(r.read())
    elapsed = time.time() - t0

    checks = {}
    checks["build_succeeded"] = bool(result.get("success"))
    checks["step_exported"] = bool(result.get("step_file"))
    v = (result.get("validation") or {})
    vc = v.get("checks", v)
    checks["is_clean"] = v.get("is_clean") is True
    checks["one_solid"] = vc.get("solid_count") == 1
    vol = vc.get("volume_mm3")
    checks["volume_in_range"] = (
        vol is not None and test["min_volume"] <= vol <= test["max_volume"]
    )
    # No raw errors may reach the user
    err = result.get("error") or ""
    checks["no_raw_traceback"] = "Traceback" not in err and len(err) < 250

    passed = all(checks.values())
    out = {
        "test": test["name"], "passed": passed, "elapsed_s": round(elapsed, 1),
        "volume_mm3": vol, "checks": checks, "error": err or None,
        "rounds": sum(1 for l in result.get("log", []) if l.startswith("[round")),
    }
    if not passed:
        out["log"] = result.get("log", [])   # keep full log for diagnosis
    return out


def main() -> int:
    only = int(sys.argv[1]) - 1 if len(sys.argv) > 1 else None
    results = []
    for i, test in enumerate(TESTS):
        if only is not None and i != only:
            continue
        print(f"[{i+1}/{len(TESTS)}] {test['name']} ... ", end="", flush=True)
        try:
            r = run_test(i, test)
        except Exception as exc:
            r = {"test": test["name"], "passed": False, "error": str(exc), "checks": {}}
        print("PASS" if r["passed"] else "FAIL",
              f"({r.get('elapsed_s', '?')}s, {r.get('rounds', '?')} rounds, vol={r.get('volume_mm3')})")
        if not r["passed"]:
            for k, ok in r.get("checks", {}).items():
                if not ok:
                    print(f"      ✗ {k}")
            if r.get("error"):
                print(f"      error: {r['error'][:200]}")
        results.append(r)

    n_pass = sum(1 for r in results if r["passed"])
    print(f"\n{n_pass}/{len(results)} passed")
    with open("output/test_suite_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("full results: output/test_suite_results.json")
    return 0 if n_pass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
