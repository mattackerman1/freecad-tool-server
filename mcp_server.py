#!/usr/bin/env python3
"""
MCP server for the FreeCAD + Elmer Tool Server.

Dynamically generates MCP tools from the FastAPI OpenAPI spec at startup,
so every endpoint (geometry, FEM, Elmer) is automatically available to any
MCP-compatible agent (Codex CLI, Claude Code, etc.) without manual maintenance.

When a new endpoint is added to the FastAPI server, it appears here automatically
on the next MCP server restart — no edits needed to this file.

Transport: stdio (default for Codex CLI / Claude Code MCP)
Env var:   FREECAD_TOOL_SERVER_URL  (default: http://localhost:8000)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

BASE_URL = os.environ.get("FREECAD_TOOL_SERVER_URL", "http://localhost:8000").rstrip("/")

server = Server("freecad-tool-server")


# ---------------------------------------------------------------------------
# OpenAPI → MCP tool registry
# ---------------------------------------------------------------------------

def _http(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Make a synchronous HTTP call to the tool server."""
    url = BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"success": False, "errors": [f"HTTP {e.code}: {e.reason}"]}
    except Exception as exc:
        return {"success": False, "errors": [str(exc)]}


def _resolve_ref(spec: dict, ref: str) -> dict:
    """Dereference a $ref pointer within the spec."""
    parts = ref.lstrip("#/").split("/")
    node: Any = spec
    for p in parts:
        node = node[p]
    return node  # type: ignore[return-value]


def _flatten_schema(spec: dict, schema: dict, depth: int = 0) -> dict:
    """
    Recursively resolve $refs and return a plain JSON Schema dict suitable
    for MCP inputSchema. Stops recursing at depth 3 to avoid blowup on
    deeply nested models.
    """
    if "$ref" in schema:
        schema = _resolve_ref(spec, schema["$ref"])

    schema_type = schema.get("type", "object")

    if schema_type == "object" or "properties" in schema:
        props: dict[str, Any] = {}
        for name, sub in schema.get("properties", {}).items():
            props[name] = _flatten_schema(spec, sub, depth + 1) if depth < 3 else {"type": "string"}
        return {
            "type": "object",
            "properties": props,
            "required": schema.get("required", []),
            **({"description": schema["description"]} if "description" in schema else {}),
        }

    if schema_type == "array":
        items = schema.get("items", {})
        return {
            "type": "array",
            "items": _flatten_schema(spec, items, depth + 1) if depth < 3 else {"type": "string"},
            **({"description": schema["description"]} if "description" in schema else {}),
        }

    # Scalar
    result: dict[str, Any] = {"type": schema_type}
    for key in ("description", "default", "enum", "minimum", "maximum", "minLength", "maxLength"):
        if key in schema:
            result[key] = schema[key]
    return result


def _tool_name(path: str, method: str) -> str:
    """
    Convert a path + method to a valid MCP tool name.
    /model/check_interference POST  →  model__check_interference
    /health                   GET   →  health
    """
    name = path.strip("/").replace("/", "__").replace("-", "_")
    return name or method.lower()


def _first_paragraph(text: str) -> str:
    """Return only the first paragraph of a multi-paragraph docstring."""
    text = text.strip()
    # Strip leading "**Tool: …**" header line that appears in our docstrings
    lines = text.splitlines()
    if lines and lines[0].startswith("**Tool:"):
        lines = lines[1:]
    text = "\n".join(lines).strip()
    return text.split("\n\n")[0].replace("**", "").strip()


def _build_registry(spec: dict) -> list[dict]:
    """Return a list of tool-definition dicts, one per API operation."""
    tools = []
    for path, path_item in sorted(spec.get("paths", {}).items()):
        for method, operation in path_item.items():
            if method not in ("get", "post"):
                continue

            name = _tool_name(path, method)
            raw_desc = (
                operation.get("description")
                or operation.get("summary")
                or path
            )
            description = _first_paragraph(raw_desc)

            # Input schema: POST bodies only (GET endpoints take no body)
            if method == "post":
                body_schema = (
                    operation
                    .get("requestBody", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                input_schema = _flatten_schema(spec, body_schema) if body_schema else {
                    "type": "object", "properties": {}, "required": [],
                }
            else:
                input_schema = {"type": "object", "properties": {}, "required": []}

            tools.append({
                "name": name,
                "description": description,
                "method": method.upper(),
                "path": path,
                "input_schema": input_schema,
            })

    return tools


def _load_registry() -> tuple[list[dict], dict[str, dict]]:
    spec = _http("GET", "/openapi.json")
    if not spec.get("paths"):
        print(
            "[freecad-mcp] WARNING: Could not fetch OpenAPI spec from "
            f"{BASE_URL}/openapi.json — is the tool server running?",
            file=sys.stderr,
        )
        return [], {}
    tools = _build_registry(spec)
    tool_map = {t["name"]: t for t in tools}
    print(
        f"[freecad-mcp] Loaded {len(tools)} tools from {BASE_URL}",
        file=sys.stderr,
    )
    return tools, tool_map


_TOOLS, _TOOL_MAP = _load_registry()


# ---------------------------------------------------------------------------
# MCP handlers
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=t["name"],
            description=t["description"],
            inputSchema=t["input_schema"],
        )
        for t in _TOOLS
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    tool = _TOOL_MAP.get(name)
    if tool is None:
        return [types.TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "errors": [f"Unknown tool '{name}'. Available: {sorted(_TOOL_MAP.keys())}"],
            }),
        )]

    # Long-running tools (FEM solve, Elmer run) get a generous timeout
    timeout = 600 if any(k in tool["path"] for k in ("/fem/", "/elmer/run", "/elmer/setup")) else 30

    # Execute in a thread so we don't block the async event loop
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _http(tool["method"], tool["path"], arguments or None, timeout),
    )

    return [types.TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
