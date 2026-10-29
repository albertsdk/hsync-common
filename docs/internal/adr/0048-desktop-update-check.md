# ADR 0048 — Desktop release check is opt-in and never self-installs

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

`hsync-desktop` ships through several channels: a PyInstaller bundle and
`install.sh` from GitHub Releases, `.deb`/`.rpm` packages, an AppImage, a Snap
(published to `edge`, `confinement: classic`), a Windows installer (Inno Setup,
which upgrades in place) and an unsigned macOS `.dmg`. Until now nothing inside
the app told the operator that a newer release existed: only their package
manager or the release page could.

Three constraints shape any in-app mechanism:

- **Unsigned artifacts.** The release workflow publishes `SHA256SUMS`, but the
  checksums live on the same host as the artifacts and there is no signature.
  A downloaded artifact therefore proves integrity against corruption, not
  authenticity: running it automatically would be the only code path in the app
  that executes code with no shared trust anchor.
- **Frozen distribution.** The app is a onefile bundle: on Windows a running
  executable cannot be replaced, and on macOS the unsigned `.dmg` cannot be
  swapped by the app without tripping Gatekeeper. Self-replacement is not a
  portable behaviour.
- **No telemetry.** The project avoids unsolicited outbound requests to
  third parties; an update check necessarily reveals the machine's IP to the
  release host.

## Decision

The desktop app performs an **update check only**, never a self-update.

- A manual action (**Help → Check for Updates…**) is always available.
- The automatic check at startup is **opt-in** (`updates/check_enabled`,
  default off) and runs **at most once every 24 hours**; it is skipped when the
  OS autostart entry launched the app into the tray.
- The newest release is resolved from the project's own
  `https://github.com/albertsdk/hsync-desktop/releases/latest` redirect
  (pinned constant, allowlisted by `docs_links.is_allowed_docs_url`), reading
  the tag from the final URL. No GitHub API, no token, no query identifier.
- Failures are silent: offline, timeout and malformed redirects produce no
  warning during the automatic path.
- The result is a dialog that reports the release and offers **Download**, which
  opens the release page in the browser. The app never downloads or executes an
  artifact; the upgrade itself stays with the platform's own process (snapd,
  the Windows installer, `apt`/`dnf`).
- The automatic path reminds once per release: a dismissed version is not
  reported again.

Rejected alternatives: a self-replacing updater (needs signed artifacts plus
per-platform atomic replacement and rollback; out of scope today), the GitHub
API (60 requests/hour unauthenticated and unneeded), an always-on silent check
(no consent), and an update feed served by `hsync-server` (would tie desktop
upgrades to a server deployment that many users do not run).

## Consequences

- The app gains exactly one outbound destination (`github.com`) and only after
  the operator opts in or clicks the menu action; the check is cached in
  `QSettings` so a launch never exceeds one request per day.
- The upgrade UX is honest: the dialog routes the user to a signed-by-process
  upgrade path instead of promising an in-app install that some channels cannot
  provide.
- Revisit this ADR if release artifacts become signed (minisign/cosign): a
  verified, per-platform installer path could then be considered, and
  `install.sh` could verify `SHA256SUMS` as well.
- Follow-up obligations: the parsing/caching/pinning logic is covered by
  `tests/test_updates.py`; the strings exist in all eleven locales; the opt-in
  key and the manual entry point are documented in
  `hsync-desktop/docs/configuration.md`.
