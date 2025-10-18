# Security Guidance

**Mandatory reading**: [SECURITY.md](../../SECURITY.md) covers the risks of automated implementation of pull-request feedback. This page summarises key policies and links to operational practices.

## Threat Model

- Attackers may craft malicious PR comments that trigger unsafe code changes.
- Leaked GitHub tokens expose private repository metadata.
- Long-running agents can drift from intended repository context.

## Required Controls

1. Review generated specs manually before execution.
2. Use fine-grained GitHub tokens scoped to read-only permissions when possible.
3. Enforce rate limits via `PR_FETCH_MAX_*` environment variables.
4. Mirror logs to a secure sink for forensic analysis.

## Incident Response

- Revoke compromised tokens through GitHub security settings.
- Rotate credentials on a schedule and after suspicious activity.
- File GitHub support tickets if you believe API abuse has occurred.

For detailed mitigation strategies, consult [SECURITY.md](../../SECURITY.md).
