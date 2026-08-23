#!/usr/bin/env python3
"""Read-only artifact server for generated music sessions (Phase 1 web access).

Usage:
    python scripts/serve_artifacts.py [--root sessions] [--host 127.0.0.1]
        [--port 8787] [--token SECRET]

Runs in the foreground (wrap in a persistent background job). Designed to sit
behind `tailscale serve` so other devices on the tailnet can play and download
generated takes from a browser:

    tailscale serve --bg --https=8443 http://127.0.0.1:8787

Endpoints:
    /healthz                 liveness probe (always open)
    /                        HTML index: sessions -> takes with inline players
    /index.json              machine-readable session/take inventory
    /files/<session>/<...>   streamed artifacts (Range supported, audio MIME)

Security model: binds loopback only; every resolved path must stay inside the
served root; optional shared token via `?token=` or `Authorization: Bearer`.
Access control for remote devices is delegated to the tailnet (Tailscale
identity + ACLs) — do NOT expose this to the public internet as-is.

JSON contract: none at runtime; logs one startup line to stdout.
Exit codes: 2 bad args/root; 0 clean shutdown.
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

MIME = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

CHUNK = 1 << 20  # 1 MiB stream chunks


def build_index(root: Path) -> dict:
    """Inventory sessions/<id>/takes/*.{wav,mp3} + metadata presence."""
    sessions = []
    if root.is_dir():
        for session_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            takes_dir = session_dir / "takes"
            takes = []
            if takes_dir.is_dir():
                for f in sorted(takes_dir.iterdir()):
                    if f.suffix.lower() in (".wav", ".mp3"):
                        entry = {
                            "file": f.name,
                            "bytes": f.stat().st_size,
                            "url": f"/files/{session_dir.name}/takes/{f.name}",
                        }
                        meta = f.with_name(f.stem + ".metadata.json")
                        if meta.is_file():
                            try:
                                m = json.loads(meta.read_text(encoding="utf-8"))
                                entry["seed"] = m.get("seed")
                                entry["provider"] = m.get("provider", "local")
                            except Exception:  # noqa: BLE001 - metadata is advisory
                                pass
                        takes.append(entry)
            caption = session_dir / "caption.md"
            sessions.append(
                {
                    "session": session_dir.name,
                    "has_caption": caption.is_file(),
                    "takes": takes,
                }
            )
    return {"schema": "artifacts-index/v1", "sessions": sessions}


def render_html(index: dict) -> str:
    rows = []
    for s in index["sessions"]:
        if not s["takes"]:
            continue
        items = []
        for t in s["takes"]:
            items.append(
                f"<li><code>{t['file']}</code> "
                f"({t['bytes'] // 1024} KiB, seed {t.get('seed', '?')}, {t.get('provider')}) "
                f"<a href='{t['url']}'>download</a></li>"
                "<audio controls preload='none' src='" + t["url"] + "'></audio>"
            )
        rows.append(f"<h2>{s['session']}</h2><ul>{''.join(items)}</ul>")
    body = "".join(rows) or "<p>No sessions with takes yet.</p>"
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>agentic-music artifacts</title>"
        "<style>body{font-family:system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem}"
        "audio{display:block;margin:.25rem 0 .75rem}</style>"
        "<h1>🎵 agentic-music artifacts</h1>" + body
    )


class Handler(BaseHTTPRequestHandler):
    root: Path = None  # type: ignore[assignment]
    token: str | None = None

    def log_message(self, fmt: str, *args) -> None:  # quiet-ish logging
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")

    # -- helpers -----------------------------------------------------------
    def _authorized(self) -> bool:
        if self.token is None:
            return True
        qs = parse_qs(urlparse(self.path).query)
        if qs.get("token", [None])[0] == self.token:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _resolve(self, rel: str) -> Path | None:
        candidate = (self.root / unquote(rel)).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError:
            return None
        return candidate

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/healthz":
            return self._send(200, b"ok\n", "text/plain")

        if not self._authorized():
            return self._send(401, b"unauthorized\n", "text/plain",
                              {"WWW-Authenticate": "Bearer"})

        if route in ("/", "/index.html"):
            return self._send(200, render_html(build_index(self.root)).encode("utf-8"),
                              "text/html; charset=utf-8")

        if route == "/index.json":
            body = json.dumps(build_index(self.root), indent=2).encode("utf-8")
            return self._send(200, body, MIME[".json"])

        if route.startswith("/files/"):
            target = self._resolve(route[len("/files/"):])
            if target is None or not target.is_file():
                return self._send(404, b"not found\n", "text/plain")
            ctype = MIME.get(target.suffix.lower(), "application/octet-stream")
            size = target.stat().st_size
            rng = self.headers.get("Range")
            if rng:
                start, end = self._parse_range(rng, size)
                if start is None:
                    return self._send(416, b"invalid range\n", "text/plain")
                length = end - start + 1
                with target.open("rb") as fh:
                    fh.seek(start)
                    remaining = length
                    self.send_response(206)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(length))
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    while remaining > 0:
                        chunk = fh.read(min(CHUNK, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with target.open("rb") as fh:
                while chunk := fh.read(CHUNK):
                    self.wfile.write(chunk)
            return

        self._send(404, b"not found\n", "text/plain")

    @staticmethod
    def _parse_range(value: str, size: int) -> tuple[int | None, int | None]:
        try:
            unit, spec = value.split("=", 1)
            if unit.strip() != "bytes":
                return None, None
            start_s, _, end_s = spec.partition("-")
            if start_s == "":
                suffix = int(end_s)
                start = max(0, size - suffix)
                end = size - 1
            else:
                start = int(start_s)
                end = min(int(end_s), size - 1) if end_s else size - 1
            if start < 0 or start > end or start >= size:
                return None, None
            return start, end
        except ValueError:
            return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT / "sessions")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--token", default=None, help="Shared secret for non-healthz routes")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        print(json.dumps({"ok": False, "error": f"root missing: {root}"}))
        return 2

    # Bind configuration onto the handler CLASS (instances resolve these as
    # class attributes; assigning them on an instance factory would not reach
    # the instantiated handlers).
    Handler.root = root
    Handler.token = args.token

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(
        json.dumps({
            "ok": True,
            "root": str(root),
            "url": f"http://{args.host}:{args.port}",
            "tailscale_hint": (
                f"tailscale serve --bg --https=8443 http://127.0.0.1:{args.port}"
            ),
            "token_protected": args.token is not None,
        })
    )
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
