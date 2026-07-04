# Security Policy

Lab Organizer moves real files on real servers, so security reports are taken
seriously.

## Supported versions

Only the latest release / `main` branch receives security fixes.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via
[GitHub private vulnerability reporting](https://github.com/Vin124/lab-organizer/security/advisories/new)
(Security tab → "Report a vulnerability").

Include what you can: affected endpoint or module, reproduction steps, and
impact (e.g. path traversal out of `LAB_ROOT`, audit-log forgery, unconfirmed
writes). You should get an initial response within a week.

## Scope notes (threat model)

The default posture is **localhost + SSH tunnel, single trusted user** — see
the "Threat model & network exposure" section of the README. Especially
interesting reports:

- Escaping the `LAB_ROOT` allowlist (symlinks, junctions, `..`, encoding tricks)
- Executing or altering moves without `confirmed: true`
- Overwriting/merging files despite the never-overwrite guarantee
- Forging or corrupting the append-only audit log (and misdirecting undo)
- Auth bypass when `AUTH_TOKEN` is set

Out of scope for v1 (documented, by design): TLS termination, user accounts /
RBAC, CSRF on an unauthenticated same-origin localhost API, and anything that
requires a hostile reverse proxy already inside the trust boundary.
