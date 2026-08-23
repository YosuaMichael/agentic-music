# Harness Web Integration — Phase 1: Artifact Sidecar

| | |
|---|---|
| **Date** | 2026-08-23 |
| **Status** | active |
| **Index** | [plans/INDEX.md](INDEX.md) |
| **Amends** | [2026-08-23-audiocpp-gguf-provider.md](2026-08-23-audiocpp-gguf-provider.md) |

## Goal

Owner deploys the DeepSeek Harness web GUI (127.0.0.1:3080) and reaches it
from other devices over Tailscale. Those devices must be able to **play and
download generated songs from a browser**, with closer harness integration
over time.

## Findings from DSH reconnaissance (2026-08-23)

Inspected `@deepseek-ai/*` packages in the installed checkout:

- `dsh-attachment`: v1 accepts images only; *"generic files, audio, video …
  require separate lifecycle and provider contracts"* — not usable for WAVs.
- `dsh-client-ui-deliverables`: produced-file chips render after each turn,
  but click-to-open targets the Host desktop via native opener and is
  deliberately omitted for non-loopback browsers — remote devices get no
  download path today.
- `dsh-api-gateway`: Typert RPC on the shared `/api` handler is the real
  extension seam for a future host plugin (unary JSON-safe calls only;
  binary needs its own route style).
- Client plugins are first-class (roster + HMR reload chain).

## Decision (Phase 1): artifact sidecar behind Tailscale Serve

Zero harness modifications; all logic stays in this repo per operating
principle "scripts execute":

1. `scripts/serve_artifacts.py` — read-only HTTP server jailed to
   `<repo>/sessions/`:
   - `/healthz` (open), `/` HTML index with inline `<audio>` players,
     `/index.json` (`artifacts-index/v1` inventory),
     `/play/<session>/takes/<file>` **per-take player page** (owner request:
     links open a browser page with playback controls, metadata — seed,
     provider, render time — and a Download button, plus sibling-take chips),
     `/files/<session>/takes/<file>` streamed with HTTP Range support
     (verified: 206 + Content-Range; full downloads 200).
   - MIME map (`audio/wav`, `audio/mpeg`, …); traversal attempts rejected
     (resolve must stay under root — verified 404 through both /files and
     /play).
   - Binds loopback only; optional shared-token gate (`--token`) on top of
     tailnet identity.
2. Run as a persistent background job:
   `python scripts/serve_artifacts.py --port 8787`
3. Expose to tailnet devices:
   `tailscale serve --bg --https=8443 http://127.0.0.1:8787`
4. Agent pastes `https://<tailnet-host>:8443/play/...` player-page links in
   chat; browsers get the listen-and-download experience natively.

Security posture: loopback bind + Tailscale ACLs = tailnet-only reachability.
Do not port-forward this server to the public internet; if off-tailnet
sharing is ever needed, add expiring links at Phase 2.

## Decision (same day): MP3 companions

Downloads shrink ~7× by keeping the WAV master and adding an MP3 companion:

- `scripts/transcode.py` (`transcode/v1`): ffmpeg + libmp3lame VBR
  (`-qscale:a 2` ≈ 190 kbps). Single-file or whole-session sweep; masters
  untouched. Verified: 34.8 MB WAV → 4.83 MB MP3.
- `generate_audiocpp.py` runs it automatically when `[audiocpp].mp3 = true`
  (default) and reports additive `mp3` / `mp3_bytes` fields; failure is
  non-fatal (WAV remains authoritative).

## Phase 2 sketch (not scheduled)

Native DSH plugin: host half registering `/api/plugins/music/*` routes
(porting `serve_artifacts.py` logic into the trust-fenced gateway), client
half rendering a sessions/takes panel with inline players. Revisit when
Phase 1 usage justifies building against harness internals.

## Phase 1.5 (same day): LAN sharing without Tailscale

Owner wanted flatmate access on the home Wi-Fi without extra app installs.

Findings:

- `dsh web --host 0.0.0.0` is **intentionally blocked** by the CLI ("would
  expose remote code execution to the network") — the low-level webserver
  supports it, the app refuses.
- Workaround stack (all verified working):
  1. Harness keeps its loopback bind; launcher (`dshweb` command +
     `dsh-web-trusted.cmd`) passes `--trusted-host 192.168.1.114:3080`.
  2. Windows portproxy bridges LAN→loopback:
     `netsh interface portproxy add v4tov4 listenaddress=192.168.1.114 listenport=3080 connectaddress=127.0.0.1 connectport=3080`
     (admin once; persists).
  3. Firewall rules allow inbound TCP 3080 + 8787.
  4. Artifact server binds `0.0.0.0:8787` directly.
- **Secure-context caveat:** browsers only expose `crypto.randomUUID` (and
  other privileged APIs) on https/localhost. Non-loopback devices therefore
  hit "crypto.randomUUID is not a function" when creating workspaces.
  `--trusted-host` cannot fix this (browser-side enforcement). Owner chose
  **Option A**: per-device Chrome/Edge flag
  (`chrome://flags/#unsafely-treat-insecure-origin-as-secure` → add
  `http://192.168.1.114:3080`, relaunch). PC itself uses
  `http://localhost:3080` (always a secure context).

Known fragilities of this stack (accepted by owner for now):

- DHCP change of `.114` silently breaks both portproxy and habit URLs →
  set a router reservation when convenient.
- Each new device needs the flag once.
- Tailscale remains installed but unplugged (`tailscale serve` proxies
  removed); re-enabling HTTPS mode later is the clean upgrade path
  (valid certs → no flags needed, works off-home too).

## Open items

- Token auth currently single shared secret; rotate manually if leaked.
