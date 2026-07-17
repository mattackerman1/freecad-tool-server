"""
Lightweight FreeCAD Tool Server client using only stdlib.
No httpx or requests required — works inside FreeCAD's bundled Python.

Usage:
    from tools.freecad_client import FreeCADClient
    c = FreeCADClient()
    c.health()
    c.create_document("test")
    c.tool("POST", "/shapes/add_box", name="b", length=50, width=30, height=10)
    info = c.get_shape_info("b")
    c.export_and_validate("output/test.step")
"""

import json
import urllib.error
import urllib.request
from pathlib import Path


BASE_DEFAULT = "http://127.0.0.1:8000"


class FreeCADClient:
    def __init__(self, base: str = BASE_DEFAULT):
        self.base = base.rstrip("/")

    def tool(self, method: str, path: str, **body) -> dict:
        """Call any endpoint. Raises RuntimeError on success=False."""
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} from {path}: {body_text}") from exc
        if not result.get("success"):
            errors = result.get("errors", [result.get("message", "unknown error")])
            raise RuntimeError(f"{path} failed: {errors}")
        if result.get("warnings"):
            for w in result["warnings"]:
                print(f"[WARNING] {w}")
        return result.get("data") or {}

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    def health(self) -> dict:
        return self.tool("GET", "/health")

    def create_document(self, name: str = "Model") -> dict:
        return self.tool("POST", "/document/create", name=name)

    def get_shape_info(self, shape_name: str) -> dict:
        return self.tool("POST", "/model/get_shape_info", shape_name=shape_name)

    def export_step(self, shape_name: str, output_path: str) -> dict:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        return self.tool("POST", "/model/export_step",
                         shape_name=shape_name, output_path=str(output_path))

    def validate_step(self, file_path: str, expected_solids: int = 1) -> dict:
        result = self.tool("POST", "/model/validate_step", file_path=str(file_path))
        if not result.get("is_clean"):
            raise RuntimeError(f"validate_step: not clean — {result}")
        actual = result.get("solid_count", 0)
        if actual != expected_solids:
            raise RuntimeError(
                f"validate_step: expected {expected_solids} solid(s), got {actual}"
            )
        return result

    def export_and_validate(self, output_path: str, shape_name: str = "",
                            expected_solids: int = 1) -> dict:
        """Export the named shape (or active document) and validate the STEP file."""
        out = str(output_path)
        if shape_name:
            self.export_step(shape_name, out)
        else:
            self.tool("POST", "/model/export_step", output_path=out)
        return self.validate_step(out, expected_solids=expected_solids)
