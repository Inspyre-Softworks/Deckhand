# Accounts and credentials

Accounts have separate labels, credential methods, and cleanup preferences.
Account metadata is stored in accounts.json under
`platformdirs.user_config_path("ns-deckhand", appauthor=False)`. File credentials
live in credentials/ keyed by account UUID. Override the root with:

```console
poetry run deckhand --config-dir PATH
```

Keep this directory private. POSIX files use owner-only permissions; Windows
files inherit parent ACLs. OS keyring and Hello keys remain OS-bound.

| Backend | Behavior |
| --- | --- |
| Session only | Password remains in memory until exit or Forget credentials |
| Password encrypted | Scrypt-derived key and AES-256-GCM; separate vault password is never saved |
| Windows Hello | Passport RSA key wraps an AES key; mandatory authentication, no weaker fallback |
| System keyring | Supported secure OS backend required; plaintext/unknown backends rejected |
| Plaintext | Explicit opt-in; anyone who can read files or backups can obtain the password |

Hello is the default selector on Windows; keyring elsewhere. Adding an account
never saves credentials. Failures do not silently change the backend. To change
storage method in this beta, forget credentials, remove the account, and add it
again with the chosen method.

Losing a master password or resetting Hello can make saved credentials
unrecoverable. Re-enter the nation password to restore access. Deleted files
may survive in backups. Python cannot guarantee erasure of immutable secret
strings from process memory. See the root README for cryptographic parameters
and native integration limitations.
