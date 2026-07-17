"""
Post-tool hook: prints an integration check reminder when the agent calls
geometry-modifying endpoints that typically create mating features.

Claude Code invokes this after Bash/PowerShell tool uses and passes the
tool input as JSON on stdin. The script prints to stdout; Claude sees the
output as feedback from the hook environment.
"""
import json
import sys

TRIGGER_ENDPOINTS = (
    "/operations/make_hole",
    "/operations/boolean_cut",
    "/shapes/add_cylinder",
    "/shapes/add_box",
    "/operations/boolean_union",
)

REMINDER = """
⚠️  INTEGRATION CHECK REMINDER

You just modified geometry. Before continuing, verify assembly fit:

1. Add witness geometry for any mating part (screw, shaft, tube, housing)
   at its nominal installed position.

2. Parts that MUST ENGAGE — check overlap:
   POST /model/check_interference
   {{"shape_a": "<feature>", "shape_b": "<witness>"}}
   PASS: interference_fraction_of_b > 0.8
   FAIL: interference_volume_mm3 < 0.1  → part misses the feature entirely

3. Parts that MUST NOT COLLIDE — check clearance:
   POST /model/check_interference
   {{"shape_a": "<body>", "shape_b": "<witness>"}}
   PASS: has_interference = false

4. Tight clearances — check gap:
   POST /model/check_min_distance
   {{"shape_a": "<a>", "shape_b": "<b>", "required_clearance_mm": 1.0}}

Remove witness solids before export. Do not skip this step.
""".strip()


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return

    # Hook payload from Claude Code has a "tool_input" key containing the
    # Bash/PowerShell command string.
    tool_input = payload.get("tool_input", {})
    command = ""
    if isinstance(tool_input, dict):
        command = tool_input.get("command", "") or tool_input.get("input", "")
    elif isinstance(tool_input, str):
        command = tool_input

    if any(ep in command for ep in TRIGGER_ENDPOINTS):
        print(REMINDER, flush=True)


if __name__ == "__main__":
    main()
