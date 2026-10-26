# ADR 0040 — P2P master trust policy (ask / accept-new / strict)

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

In p2p mode a slave authenticates the elected master with Trust-On-First-Use: the
first certificate fingerprint seen for a `(device ID, bucket)` is pinned and a
later change is refused as a possible man-in-the-middle (ADR-0020). TOFU protects
every connection after the first one, but the first one is accepted silently —
exactly the window an attacker sharing the LAN during setup needs.

The previous control was a boolean *strict pairing* switch. It conflated two
different behaviours: "ask the operator and proceed on acceptance" (meaningful on a
terminal, in the desktop app and on Android) and "refuse until the fingerprint is
pinned out of band" (the only workable behaviour for a daemon). A single flag also
left the default at *silent auto-trust*, so the secure behaviour required an
opt-in, and it diverged from the `TrustPolicy` vocabulary already used for the
bootnode (ADR-0035) and the sync server (ADR-0036).

## Decision

The trust decision for the p2p master is the shared `TrustPolicy` of the
self-signed transports, restricted to the three values that actually pin:
`ask`, `accept-new` and `strict`.

- `evaluate_tls_trust(policy, stored, observed)` (`hsync_common/protocol/tls_trust.py`)
  is the canonical rule, as for the bootnode and the server.
- `resolve_self_signed_policy` resolves the effective policy: the `--p2p-trust`
  flag wins over `HSYNC_P2P_TRUST`, which wins over `DEFAULT_SELF_SIGNED_POLICY`
  (`ask`). `chain` and `none` are rejected: they never pin, so they would disable
  the master identity check entirely.
- Front-ends supply the confirmation channel: an SSH-style terminal prompt when a
  terminal is interactive, the desktop pairing dialog, and the Android in-app
  confirmation. With no confirmation channel the connection fails closed
  (`pairing_needed`) and the operator pins the peer with `hsync trust peer add`.
- `strict` is the unattended equivalent of `ask`: the same refusal, without a
  prompt.
- A **changed** fingerprint is refused under every policy and can only be cleared
  by an explicit re-pin.

The policy authenticates the master towards this device. Devices that *connect to*
a master are authorized by the shared p2p key (ADR-0029), not by this policy.

## Consequences

- **Secure by default**: an unknown master is confirmed before it is trusted;
  silent auto-trust becomes an explicit `accept-new` choice.
- **One confirmation per new master** per device and bucket — the cost the model
  is designed to pay, since it closes the first-connection window.
- **Unattended deployments must declare their policy**: a host with no operator
  (service unit, container, NAS) either runs `strict` and pins peers out of band
  or opts into `accept-new` knowingly. The WD OS5 appliance, whose web UI cannot
  prompt during discovery, ships `accept-new` explicitly.
- The boolean flag and its environment variable are removed; the vocabulary,
  fixtures (`master_trust_scenarios`) and the Kotlin mirror follow the policy.
- Tests must lock the default: a default that no test defends drifts at the first
  refactor.
