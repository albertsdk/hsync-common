# ADR 0026 — Special permission bits (setuid/setgid/sticky) policy

- **Status:** Accepted
- **Date:** 2026-08-26

## Context

HSYNC synchronises file and directory permissions as an octal POSIX mode string
(e.g. `"644"`, `"755"`) on the wire, the same model used by rsync and Syncthing.
The low 12 bits of a POSIX `st_mode` include three **special bits** that carry
safety and security implications well beyond the ordinary rwx triplets:

- **setuid** (`0o4000`): a file runs with the privileges of its owner.
- **setgid** (`0o2000`): a file runs with the group of its owner (or, on a
  directory, forces the group of newly created entries).
- **sticky** (`0o1000`): on a directory, restricts deletion/rename to the owner
  of the entry, the directory owner, or root.

If a synced file carrying `4755` were applied verbatim on every receiving host,
it would become a **setuid executable owned by whomever produced it upstream** —
a local privilege-escalation vector the moment the sync daemon runs with elevated
privileges. Directory modes supplied by a peer can equally be used to lock the
receiver out of its own bucket (e.g. a mode of `000`).

The reference tools disagree on how to handle these bits: **rsync** preserves
them with `--perms`/`-a` but a non-privileged receiver cannot actually set
setuid/setgid (and `--fake-super` explicitly clears them to `u-s,g-s,o-t` for
safety on the real file), while **Syncthing** strips them *at read time* by
masking to `0o777`. HSYNC's owners-and-operator threat model (self-signed LAN
transport, TOFU pinning, LAN-key write auth) wanted a single, unconditional rule
that is secure regardless of privilege level on the receiving host — without
forfeiting the ability to *detect* a chmod from a distance.

This decision was previously implemented in code with only inline comments. This
ADR formalises it so the policy cannot drift across the separate repositories.

## Decision

HSYNC adopts an **asymmetric, always-defensive** policy on special bits:

1. **Detect and transmit (read side).** Permissions are read and serialised with
   the full 12 permission bits — `PERMISSION_MASK = 0o7777`
   (`hsync-common/hsync_common/permissions.py`). A file with `setuid` is
   serialised as `"4755"` on the wire, and a chmod that flips special bits is
   detected as a permission change (the client snapshot key masks to the same 12
   bits, `st_mode & 0o7777`). This keeps the metadata honest: a local setuid file
   is never silently normalised to `755` before it reaches peers.

2. **Never apply to the filesystem (write).** On **every** path that applies a
   permission received from a remote peer, the mode is sanitised through
   `sanitize_remote_permissions` / `REMOTE_PERMISSION_MASK = 0o777` — the setuid,
   setgid and sticky bits are stripped **before** the `chmod`, so `"4755"` is
   applied as `"755"`. Rationale is recorded in the SSOT docstring: a synced setuid
   executable must never materialise on a receiving host.

3. **Owner floor for directories.** When applying a peer-supplied directory mode,
   the resulting mode ORs in `OWNER_DIRECTORY_ACCESS = 0o700` so the sync engine
   and the server's storage layer always retain owner rwx and can traverse and
   update their own tree — a peer-supplied `000` can never lock a receiver out of
   its bucket.

The sanctioned wire conversion is `octal_to_mode` (masked to `0o7777`) on the
reading side and `sanitize_remote_permissions` (masked to `0o777` plus the
directory owner floor) on the apply side.

**Alternatives rejected:**

- *rsync-style privilege-gated apply* (root applies, non-root strips): adds
  privilege-dependent, non-deterministic behaviour and a privilege-escalation
  surface in exactly the deployment the daemon runs as. Rejected.
- *Syncthing-style strip-at-read* (never transmit special bits at all): simpler,
  but loses the ability to **detect** a chmod-of-special-bits change on the local
  source, converging to a silent `755` on the wire. Retains the transmission
  because the bits are meaningful locally; only their application is stripped.
- *Never transmit permissions at all*: breaks nice per-file executability
  behaviour and chunk-identical-output reuse. Rejected.

## Consequences

- **Security:** a remote peer can never create a setuid/setgid executable or a
  sticky/owner-locked directory on a receiving host. This holds even when the
  sync engine runs with elevated privileges.
- **Fidelity:** the `rwx` triplets (owner/group/other) are preserved and applied;
  the special bits are not. Any local `chmod 4755` propagates to peers as a
  `chmod 755` permission-change event — never as a setuid. This is documented
  behaviour, not a bug.
- **Consistency:** the rule is enforced through a single SSOT
  (`hsync_common.permissions`) consumed by `hsync-client` and `hsync-server` (both
  `set_permissions`/`set_permissions_on_dir`), with a mirrored contract enforced
  on the metadata-only `PATCH …/files/permissions` REST/LAN route and unit-tested
  in `hsync-common/tests/test_permissions.py` and `hsync-client/tests/test_security_inbound.py`.
- **Directory availability:** recipient directories always expose at least
  `0o700` for the storage owner, preventing self-lockout from peer-supplied `000`.
- **No backward compatibility burden** (per HSYNC's *Zero Backward Compatibility*
  stance): consumer repositories apply the policy atomically from the SSOT.

## See also

- [`permissions.py`](../../../hsync_common/permissions.py) — the SSOT: masks,
  `mode_to_octal`, `sanitize_remote_permissions`, `octal_to_mode`.
- `hsync-client/hsync_client/utils.py` (`_apply_permissions`, `set_permissions`,
  `set_permissions_on_dir`) and `hsync-server/hsync_server/api/utils.py`
  (`set_permissions`, `set_directory_permissions`) — apply-side wiring.
- Reference behaviour: rsync `--perms`/`-a` + `--fake-super`; Syncthing
  `lib/scanner/walk.go` (`CreateFileInfo`, mask to `fs.ModePerm` = `0o777`).
