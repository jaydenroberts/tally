# Security Policy

## Supported Versions

Only the latest release line receives security fixes. If you are on an older version, update to the latest release before reporting.

| Version | Supported |
|---------|-----------|
| Latest release | ✅ |
| Older releases | ❌ |

## Reporting a Vulnerability

Report vulnerabilities privately via **GitHub Security Advisories**: open the repository's **Security** tab and click **Report a vulnerability**. Do **not** report security issues in public GitHub issues.

What to expect:

- Your report will be acknowledged, and fixes for confirmed issues will ship in a subsequent release.
- Tally is a solo-maintained hobby project — there is no formal response SLA. Reports are triaged as time allows.

## Deployment Scope

Tally is designed for single-household deployment on a private LAN or behind a VPN/private tunnel. It is **not** designed or hardened for public-internet exposure, and the data layer is not user-scoped — any authenticated user can read all data in the instance (see the single-tenant warning in the [README](README.md)). Reports that assume a public-internet or hostile multi-tenant deployment may be closed as out of scope, though hardening suggestions are welcome.
