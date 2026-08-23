# Security Policy

## Supported versions

This project is pre-release. Only the current `v0.0.x` line receives security
attention; there are no stable releases yet.

## Reporting a vulnerability

Please report security issues **privately** via
[GitHub security advisories](https://github.com/advisories) (Security tab →
"Report a vulnerability") rather than opening a public issue. Include a
description of the problem, the affected component or script, and reproduction
steps. You will receive a response once a maintainer has triaged the report.

## Scope notes

The attack surface is deliberately small: the project runs **fully local by
design** — no telemetry, no API keys, no cloud services. The inference server is
expected to bind to localhost only, so most vulnerability classes of hosted
applications do not apply.

Two things remain third-party trust decisions:

- Model weights are downloaded by each user from Hugging Face under their own
  community license. They are not distributed with this repository; verify what
  you download.
- Upstream repositories are fetched locally at runtime by `fetch_upstream.sh`
  against pinned commits and digests recorded in `docs/upstream.md`. Report any
  discrepancy between the pin record and what the script produces.
