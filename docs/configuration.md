# Accounts and credentials

## Nation-name protections

Protect my nations defaults on for every account, including existing accounts.
It protects cards whose nation name matches any configured account's nation,
across seasons and copies. The Protected name rules editor saves exact names
and literal contains strings per account, one entry per line. Matching is
case-insensitive and treats underscores and spaces alike; blank entries do not
match everything. Custom rules remain active when the own-nation toggle is off.
Changed rules invalidate the account's preview. Other accounts' cached previews
are checked against the current configured-nation list when restored.

## API call counters

The fixed sidebar footer displays session and lifetime HTTP attempt counts.
Lifetime usage is stored in api_usage.sqlite3 under the configuration directory;
it begins with this feature and persists across launches. Portable config roots
maintain separate totals. Demo and cached views make no requests and add no calls.
Failures count as attempts; waiting does not. No request content is stored.

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
immediately prompts for credentials; only submitting the prompt saves them. Failures do not silently change the backend. To change
storage method in this beta, forget credentials, remove the account, and add it
again with the chosen method.

Losing a master password or resetting Hello can make saved credentials
unrecoverable. Re-enter the nation password to restore access. Deleted files
may survive in backups. Python cannot guarantee erasure of immutable secret
strings from process memory. See the root README for cryptographic parameters
and native integration limitations.

## Faster execution

The per-account **Faster execution** checkbox defaults off and is saved when
toggled. It preserves the reviewed plan and filter. Enabled execution sends
only prepare/execute commands for reviewed copies, without live ownership,
protection, name, or bid checks. Standard mode keeps its per-copy revalidation.
The confirmation identifies the mode. Changes since review can be missed.

## Dialogs and appearance

Manage nations contains the nation selector for account management, credential
controls, and removal. API settings contains the saved contact nation/email;
Enter saves that single-line input. New nations immediately prompt for
credentials, with Cancel preserving the account without a password.

`flag_theme` defaults to false and is saved per account independently of cleanup
policy. Enabled flag colors use a bounded same-site image download and Pillow
to derive readable accents; the dark base and safety colors remain consistent.
One flag-information API call and one image download are paced and counted on
first use per nation per session. Session-cached accents avoid repeat downloads;
restart to refresh a changed flag. Failure falls back to the default colors.

The shared `cards.sqlite3` catalog is independent of account ownership; quick
loads and restored session snapshots use names learned from any nation. Adding
a selected card's exact name to protections is per-account and invalidates its
reviewed preview.
