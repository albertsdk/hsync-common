<p align="center">
  <img src="docs/assets/hsync-logo-horizontal.svg" alt="HSYNC logo" width="300">
</p>

# HSYNC Common Library

**hsync-common** is the shared foundation that all other HSYNC projects build
upon — data formats, compression, file exclusion rules, and security utilities.
You don't install or run it directly; it's a library used by the client, server and
desktop application.

> New to HSYNC? Start with the [HSYNC Ecosystem](https://github.com/albertsdk/hsync/blob/main/README.md) for an overview of the platform before using the library.

It is also the **single source of truth for the open, versioned wire protocol**:
the shared models, JSON-Schema builders and committed fixtures live here
(`hsync_common.protocol`, `docs/protocol.md`, `docs/p2p-protocol.md`), so every
implementation speaks the same contract. The library sends no telemetry or
analytics anywhere.

> 👉 **Operational Advisory:** As with any data-management software, integrators are strongly advised to validate the library's behavior against their own data and to maintain validated, independent backups in the applications built on top of it.

---

[![License: BSD 3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-brightgreen.svg)](LICENSE)
[![CI](https://github.com/albertsdk/hsync-common/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/albertsdk/hsync-common/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/albertsdk/hsync-common)](https://github.com/albertsdk/hsync-common/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/hsync-common)](https://pypi.org/project/hsync-common/)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)

**Quick navigation:**
- **Want to contribute?** See [Contributing](CONTRIBUTING.md)
- **Looking for detailed documentation?** Navigate to [docs/README.md](docs/README.md)

---

## Key modules

| Module | Purpose |
|--------|---------|
| `hsync_common.models` | Unified `File`, `Dir`, `Symlink`, `Event`, `SyncAction`, `TombstoneStore`, delta transfer models |
| `hsync_common.protocol` | Versioned wire protocol: versions, capabilities, WS auth, LAN election, pairing, JSON-Schema builders, fixtures |
| `hsync_common.delta` | Rsync-style delta transfer algorithm: rolling checksum, block matching, decision heuristics |
| `hsync_common.hashing` | SHA-256 computation, adaptive chunk sizing, hex digest validation |
| `hsync_common.compression` | Zstandard helpers, `PRECOMPRESSED_EXTENSIONS`, `should_compress` |
| `hsync_common.permissions` | Octal permission SSOT, remote permission sanitization |
| `hsync_common.ignore` | `.hsyncignore` gitignore-style matcher (`IgnoreMatcher`) |
| `hsync_common.path_validation` | Path safety helpers, remote-path validators |
| `hsync_common.constants` | Shared constants (`HSYNCKEEP_FILENAME`, `HSYNCIGNORE_FILENAME`, `HSYNCFOLDER_FILENAME`, …) |
| `hsync_common.ssl_utils` | Shared SSL primitives, cert fingerprinting |
| `hsync_common.logger` | `BaseInterceptHandler`, log rotation helpers |
| `hsync_common.clock` | NTP-style clock offset computation |
| `hsync_common.format` | Human-readable bytes/duration formatting |
| `hsync_common.env` | Environment-variable parsing helpers |
| `hsync_common.text` | Text utilities (e.g. `escape_loguru_markup`) |
| `hsync_common.labels` | `ActionLabel` enum, log-label colorization, two-level origin rule (`[LOCAL …]` / `[REMOTE …]`) |
| `hsync_common.runtime` | Container runtime detection (Docker, Podman, Kubernetes), TTY detection, cgroup resource limits |
| `hsync_common.exceptions` | `HSyncError` base class |
| `hsync_common.time_utils` | Timestamp formatting/parsing SSOT |

## Benchmarks

Hot-path micro-benchmarks live in [`bench/`](bench/) — L1 only (pure in-process
measurement), because the library has no process or transport of its own. Five
scripts cover hashing, compression, delta transfer, `.hsyncignore` matching and
model serialization; each accepts `--count N` and `--json-out FILE`.

```bash
cd hsync-common && .venv/bin/python bench/bench_hashing.py --count 2000
```

See [`bench/README.md`](bench/README.md) for the scope of each script, the
shared helpers and the measurement methodology.

## Documentation

| Document | What it covers |
| -------- | -------------- |
| [Usage](docs/usage.md) | How to integrate hsync-common as a dependency |
| [Models](docs/models.md) | Shared data models reference |
| [Utilities](docs/utilities.md) | Cross-cutting utilities guide |
| [Protocol](docs/protocol.md) | Versioned wire protocol reference |
| [Ignore file](docs/ignore-file.md) | `.hsyncignore` syntax, `IgnoreMatcher` layers, and API |
| [Android Mirroring](docs/android-mirroring.md) | How Python models are mirrored in Kotlin |
| [Internal Architecture](docs/internal/architecture.md) | Shared models, utilities, and how they fit the HSYNC ecosystem |
| [Architecture Decision Records](docs/internal/adr/README.md) | Why the stable, cross-project decisions were made |
| [Contributing](CONTRIBUTING.md) | Development setup and contribution guidelines |
| [Report an issue](https://github.com/albertsdk/hsync-common/issues) | Open development and bug tracking |
| [Security Policy](SECURITY.md) | Supported versions and how to report vulnerabilities |

## Associated Ecosystem Components

The other components of the HSYNC ecosystem:

- [HSYNC Main](https://github.com/albertsdk/hsync/blob/main/README.md) — Umbrella repository and project overview.
- [HSYNC Server](https://github.com/albertsdk/hsync-server/blob/main/README.md) — Central sync hub: REST API, WebSocket relay, file storage.
- [HSYNC Client](https://github.com/albertsdk/hsync-client/blob/main/README.md) — CLI client: Server Mode and p2p Mode.
- [HSYNC Desktop](https://github.com/albertsdk/hsync-desktop/blob/main/README.md) — Desktop GUI front-end. *(in development)*
- [HSYNC Android](https://github.com/albertsdk/hsync-android/blob/main/README.md) — Android client app. *(in development)*
- [HSYNC Bootnode](https://github.com/albertsdk/hsync-bootnode/blob/main/README.md) — Optional Internet discovery node for P2P (`boot/1`, no-log, RAM-only).

## Security & Vulnerability Reporting

To report a vulnerability, please use GitHub's **Private Vulnerability Reporting**:

👉 **[Report a vulnerability](https://github.com/albertsdk/hsync-common/security/advisories/new)**

See our [Security Policy](SECURITY.md) for supported versions and hardening
recommendations.

## 🙋‍♂️ A note from the maintainer

This project was born out of the need for a system capable of replicating the contents of a folder from a PC or Android device to a NAS, primarily for backup purposes. Several solutions were already available, but I couldn't find one that met all my requirements. This led to the somewhat questionable decision to develop one from scratch, while also providing an opportunity to gain a deeper understanding of programming languages, algorithms, frameworks, and related technologies.

Originally conceived as a hobby project, HSYNC has been under continuous development ever since. I believe it has now evolved to the point where its capabilities are comparable to those of commercial solutions, while also offering some distinctive features. As a result, it may also be suitable for deployment in certain production environments.

HSYNC is a passion project that I primarily develop and maintain in my spare time. Please keep this in mind when interacting with the project: we're all doing our best to build something great together, but this is not a paid, full-time job for any of us.

## Disclaimer

> [!WARNING]
> **HSYNC manipulates files and directories** — it creates, overwrites, moves, and deletes data.
> Misconfiguration, software defects, or other unforeseen conditions may lead to **data loss or
> corruption**. **Use at your own risk and always keep verified, independent backups.**

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. Although the author has implemented reasonable safety measures, IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY — including, without limitation, any direct, indirect, incidental, special, exemplary, or consequential damages, loss of data, or business interruption — WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

This disclaimer supplements, and does not replace, the warranty disclaimer and limitation of liability provisions of the [BSD 3-Clause License](LICENSE), which govern this software.

## License

Distributed under the [BSD 3-Clause License](LICENSE).
