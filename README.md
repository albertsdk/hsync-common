# hsync-common

> [!WARNING]
> **HSYNC manipulates files and directories** — it creates, overwrites, moves, and deletes data.
> Misconfiguration, software defects, or other unforeseen conditions may lead to **data loss or
> corruption**. **Use at your own risk and always keep verified, independent backups.**
> The software is provided "as is", without warranty of any kind — see the full
> [Disclaimer](#disclaimer) and [License](#license) below.

---

Shared models, constants, compression utilities, and ignore-file support for the HSYNC ecosystem.

## Key modules

| Module | Purpose |
|--------|---------|
| `hsync_common.models` | Unified `File`, `Dir`, `Symlink`, `Event`, `SyncAction`, `Tombstone` models |
| `hsync_common.compression` | Zstandard helpers, `PRECOMPRESSED_EXTENSIONS`, `should_compress` |
| `hsync_common.ignore` | `.hsyncignore` gitignore-style matcher (`IgnoreMatcher`) |
| `hsync_common.constants` | Shared constants (`HSYNCKEEP_FILENAME`, `HSYNCIGNORE_FILENAME`, `HSYNCTOMBSTONES_FILENAME`, …) |
| `hsync_common.ssl_utils` | Shared SSL primitives |
| `hsync_common.logger` | `BaseInterceptHandler`, log rotation helpers |
| `hsync_common.exceptions` | `HSyncError` base class |
| `hsync_common.path_validation` | Path safety helpers |
| `hsync_common.env` | Environment-variable parsing helpers |
| `hsync_common.text` | Text utilities (e.g. `escape_loguru_braces`) |

## Ignore file (`.hsyncignore`)

Place a `.hsyncignore` file in the root of a bucket to control which files are
excluded from sync.  The syntax is identical to `.gitignore`:

```
# Ignore build artefacts
/dist/
*.pyc

# Re-include a specific file
!important.log
```

`IgnoreMatcher` combines three layers:

1. **Default hidden patterns** (files/dirs starting with `.`, swap files, …)
2. **Per-bucket `.hsyncignore`** file
3. **Extra patterns** provided programmatically (e.g. from CLI `--ignore-patterns`)

The sentinel `.hsynckeep` is always preserved regardless of any pattern.

Use `set_active_matcher()` / `get_active_matcher()` to install a process-wide
matcher; `should_skip(rel_path, is_dir)` is a convenience wrapper that falls
back to the legacy hidden-file check when no matcher is active.

## Documentation

- [Architecture](docs/architecture.md) - Shared models, utilities, and how they fit the HSYNC ecosystem
- [Contributing](CONTRIBUTING.md) - Development setup and contribution guidelines
- [Security Policy](SECURITY.md) - Supported versions and how to report vulnerabilities

### Related projects

`hsync-common` is the shared foundation consumed by the other HSYNC projects:

- [HSYNC Client](../hsync-client/README.md) - Sync client (Server Mode and LAN/P2P Mode)
- [HSYNC Server](../hsync-server/README.md) - Central synchronization server

## License

[Mozilla Public License 2.0](LICENSE)

## Disclaimer

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NONINFRINGEMENT. Although the author has implemented reasonable safety measures, IN NO EVENT SHALL THE AUTHOR OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY — including, without limitation, any direct, indirect, incidental, special, exemplary, or consequential damages, loss of data, or business interruption — WHETHER IN AN ACTION OF CONTRACT, TORT, OR OTHERWISE, ARISING FROM, OUT OF, OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

This disclaimer supplements, and does not replace, Sections 6 ("Disclaimer of Warranty") and 7 ("Limitation of Liability") of the [Mozilla Public License 2.0](LICENSE), which govern this software.
