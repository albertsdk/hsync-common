<p align="center">
  <img src="docs/assets/hsync-logo-horizontal.svg" alt="HSYNC logo" width="480">
</p>

# HSYNC Common Library

**hsync-common** is the shared foundation that all other HSYNC projects build
upon — data formats, compression, file exclusion rules, and security utilities.
You don't install or run it directly; it's a library used by the client, server and
desktop application.

> 👉 **Operational Advisory:** As with any data-management software, integrators are strongly advised to validate the library's behavior against their own data and to maintain validated, independent backups in the applications built on top of it.

---

[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)
[![CI](https://github.com/albertobasso/hsync-common/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/albertobasso/hsync-common/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/albertobasso/hsync-common)](https://github.com/albertobasso/hsync-common/releases/latest)
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
| [Security Policy](SECURITY.md) | Supported versions and how to report vulnerabilities |

### Associated Ecosystem Components

`hsync-common` is the shared foundation consumed by the other HSYNC projects:

- [HSYNC Client](https://github.com/albertobasso/hsync-client/blob/main/README.md) - Sync client (Server Mode and LAN/P2P Mode)
- [HSYNC Server](https://github.com/albertobasso/hsync-server/blob/main/README.md) - Central synchronization server (Server Mode)
- [HSYNC Desktop](https://github.com/albertobasso/hsync-desktop/blob/main/docs/README.md) — Desktop client GUI front-end *(in development)*.
- [HSYNC Android](https://github.com/albertobasso/hsync-android/blob/main/docs/README.md) — Android client app *(in development)*.

> **Note:** The desktop GUI (`HSYNC Desktop`) and the Android app (`HSYNC Android`)
> are still under active development and are not yet ready for production use.

## Security & Vulnerability Reporting

To report a vulnerability, please use GitHub's **Private Vulnerability Reporting**:

👉 **[Report a vulnerability](https://github.com/albertobasso/hsync-common/security/advisories/new)**

See our [Security Policy](SECURITY.md) for supported versions and hardening
recommendations.

## Disclaimer

> [!WARNING]
> **HSYNC manipulates files and directories** — it creates, overwrites, moves, and deletes data.
> Misconfiguration, software defects, or other unforeseen conditions may lead to **data loss or
> corruption**. **Use at your own risk and always keep verified, independent backups.**

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. Although the author has implemented reasonable safety measures, IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY — including, without limitation, any direct, indirect, incidental, special, exemplary, or consequential damages, loss of data, or business interruption — WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

This disclaimer supplements, and does not replace, Sections 6 ("Disclaimer of Warranty") and 7 ("Limitation of Liability") of the [Mozilla Public License 2.0](LICENSE), which govern this software.

## License

Distributed under the [Mozilla Public License 2.0](LICENSE).
