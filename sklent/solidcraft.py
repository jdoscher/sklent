"""A small stdio MCP client for `solidcraft-cli mcp --headless`.

One process per design: the design loads once, then every frame is a `screenshot`
call with its own camera, drawn on the GPU (or Mesa's software Vulkan).
"""

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from .config import get_settings


class SolidCraftError(RuntimeError):
    pass


class SolidCraft:
    def __init__(self, design: Path, out_dir: Path, timeout: float = 600):
        self.timeout = timeout
        self._stderr: list[str] = []
        self.proc = subprocess.Popen(
            [get_settings().solidcraft_cli, "mcp", "--headless", "--in", str(design),
             "--allow-path", str(out_dir), "--allow-path", str(design.parent)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        self._n = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "sklent", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _drain_stderr(self) -> None:
        assert self.proc.stderr
        for line in self.proc.stderr:
            self._stderr = (self._stderr + [line.rstrip()])[-40:]

    def _send(self, msg: dict) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self._n += 1
        self._send({"jsonrpc": "2.0", "id": self._n, "method": method, "params": params})
        assert self.proc.stdout
        while True:
            line = self.proc.stdout.readline()
            if not line:
                tail = "\n".join(self._stderr[-10:])
                raise SolidCraftError(f"solidcraft-cli exited during {method}: {tail}")
            msg = json.loads(line)
            if msg.get("id") == self._n:
                if "error" in msg:
                    raise SolidCraftError(f"{method}: {msg['error'].get('message', msg['error'])}")
                return msg["result"]

    def tool(self, name: str, **args: Any) -> Any:
        """Call a tool; returns its first text block parsed as JSON when it is JSON."""
        result = self._rpc("tools/call", {"name": name, "arguments": args})
        texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
        if result.get("isError"):
            raise SolidCraftError(f"{name}: {' '.join(texts)[:500]}")
        if not texts:
            return None
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]

    def execute(self, command: str, **params: Any) -> Any:
        return self.tool("execute", command=command, params=params)

    def bodies(self) -> list[dict]:
        """Every body with its `name`, `visible` flag and `bbox` ({min, max} in mm)."""
        return (self.tool("inspect_design") or {}).get("bodies", [])

    @staticmethod
    def bounds(bodies: list[dict]) -> tuple[list[float], list[float]] | None:
        """The union of the visible bodies' bounding boxes, in mm. Hidden bodies (a test
        track, construction geometry) aren't drawn, so they mustn't shrink the framing."""
        lo = hi = None
        for b in bodies:
            if b.get("visible") is False:
                continue
            box = b.get("bbox") or {}
            if box.get("min") and box.get("max"):
                lo = box["min"] if lo is None else [min(a, c) for a, c in zip(lo, box["min"], strict=True)]
                hi = box["max"] if hi is None else [max(a, c) for a, c in zip(hi, box["max"], strict=True)]
        return (lo, hi) if lo is not None and hi is not None else None

    def paint(self, bodies: list[str], color: str, opacity: float) -> None:
        """Give every body one look. A body's own appearance beats its component's and
        material's, so this covers everything but per-face paint (see palette.clamp)."""
        step = {"command": "appearance.assign",
                "params": {"bodies": bodies, "color": color, "opacity": opacity}}
        self.tool("batch", commands=[step], verbose=False)

    def screenshot(self, path: Path, camera: dict, width: int, height: int) -> None:
        self.tool("screenshot", camera=camera, path=str(path), width=width, height=height,
                  grid=False, axes=False)

    def kill(self) -> None:
        """Stop the process now (another worker failed); a call blocked on it then fails."""
        try:
            self.proc.kill()
        except OSError:
            pass

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()

    def __enter__(self) -> "SolidCraft":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
