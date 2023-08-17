# Security Policy

## Supported Versions

Security fixes are applied to the latest released version on the `main` branch.
HSYNC components share a single protocol version (`hsync_common.VERSION`).

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅        |
| < 1.0   | ❌        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, use GitHub's private vulnerability reporting:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability** to start a private advisory.

Please include the affected component and version, steps to reproduce, the
impact, and any suggested mitigation. Allow a reasonable time for a fix before
any public disclosure. We aim to acknowledge reports within a few days and to
keep you informed of remediation progress.

## Security Model

`hsync-common` is a library and performs no network I/O on its own, but it
provides security-sensitive building blocks reused by the other components:

- **Path validation** (`path_validation`) — filename checks and path-traversal
  protection for bucket-relative paths.
- **SSL utilities** (`ssl_utils`) — self-signed certificate generation and
  fingerprint helpers used by LAN HTTPS.
- **Tombstones** (`models/tombstone`) — privacy-preserving (hashed) deletion
  keys.

Vulnerabilities in these areas affect every consumer, so they are treated with
the highest priority.
