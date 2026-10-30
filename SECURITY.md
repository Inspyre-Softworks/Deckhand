# Security policy

Deckhand is a local beta. Security fixes target the latest source/version; older
betas do not have a separate support branch. Native Hello and desktop keyring
behavior must be verified on the target system.

## Reporting a vulnerability

Do not post vulnerabilities involving credential exposure or unintended junking
in public issues. Use the repository's GitHub Security tab and private vulnerability
reporting if available. If unavailable, contact the maintainer privately through
their published GitHub contact channel before sharing details. No dedicated
security mailbox or response-time guarantee is currently established.

Provide the affected version, platform, impact, and a minimal reproduction with
synthetic cards or fake credentials. Never attach passwords, PINs, prepare tokens,
credential files, account metadata, or unredacted HTTP traces.

## Boundaries

Preview uses public API reads; execution requires a nation password and explicit
review/confirmation. Junking is irreversible and market checks are not atomic.
Unexpected write outcomes must be reconciled by rescanning, never automatic retry.
Credential stores must fail closed with no silent downgrade. Plaintext storage
is explicit opt-in. See README.md for storage and recovery limitations.
