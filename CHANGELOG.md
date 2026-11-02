# Changelog

Versions follow semantic versioning while the 0.x series remains a beta; review
release notes for compatibility changes.

## [Unreleased]

### Documentation
- Correct the README verification status to reflect successful live junking and
  gifting by the maintainer, separately from mocked automated test coverage.

## [0.1.3]

### Added
- Reusable ProgressWindow class with the centered-title/inset-status-and-bar
  layout, configurable action callback, progress/ETA methods, and standalone CSS.
  Operation and name-resolution windows now share it.
- Reviewed-queue execution: faster junking and all gifting send only prepare and
  execute commands, without additional public checks. Gift bank floors use local
  reviewed-balance accounting, with estimated-bank labeling and updated ETA.
- Sort card tables by clicked column with numeric money/count ordering; show
  per-copy estimated market value without changing reviewed execution order.
- Compact selected-nation bank/deck-value fields with explicit cached/unavailable
  states, plus Python/runtime/startup-command details in About.
- Reviewed gifting to another saved nation, ordered by descending estimated
  market value, with a user-set sender bank floor, fee projections, both-nation
  confirmation, reviewed-queue execution, Stop/ETA, and no uncertain-write retries.
  Includes cleanup-protected cards and excludes listed cards.
- Manage nations and API settings dialogs, Enter-to-submit single-line inputs,
  and immediate credential prompting after adding a nation.
- Dialog-based preview/execution progress with Stop controls, bordered function
  groups, selected-card exact-name protection, and About with both versions.
- Optional per-nation flag-derived accent colors with bounded public downloads,
  session caching, and Pillow decoding; reuse shared names in cached deck views.
- Separate Resolve card names action with progress, immediate cancellation of
  public reads, partial results retained on cancel/error, and resumable lookups.
  Deck loading now returns quick ownership data and cached names by default.
- Opt-in per-account faster execution using only prepare/execute commands for
  reviewed copies, with mode confirmation and adjusted ETA. Standard per-copy
  checks remain the default.
- Persistent SQLite card catalog populated by public reads, with local name or
  card-number lookup across seasons in the library and TUI.
- Cleanup countdown with estimated time remaining and copies left, adjusted for
  live skips, request timing, and rate-limit delays.
- Conditional manual-sale review buttons for bids equal to or above junk value,
  respecting rarity and all protections. Include owned copies, snapshot prices,
  and identified market-page links; no sale commands are sent.
- Default own-nation card protection plus saved per-account exact/contains name
  lists, applied during preview and live execution rechecks.
- Fixed bottom-left API session/lifetime counters; persist aggregate lifetime
  attempts in SQLite, without credentials or request contents.
- Session-only per-account deck/preview caches with timestamps and restored
  display filters. Add Refresh deck; explicit preview always rechecks live data.
  Policy changes invalidate previews; execution evicts consumed snapshots.
- Preview ETA with a ticking countdown based on remaining market checks,
  observed response time, and current rate-limit spacing/backoff. The estimate
  starts after protections load and clears on completion, failure, or stop.
- Show preview stages, market-check counts, request/response waits, and a live
  pacing countdown. Default request spacing is 0.65 seconds; response headers
  adjust spacing to remaining shared budget and server retry deadlines.
- Load the selected nation's public deck automatically, without unlocking
  credentials. Keep eligibility unchecked until Preview cleanup; preserve visible
  cards when policy changes invalidate a preview, and discard stale account loads.
- Preview table filter for all, eligible, or ineligible cards, with visible row
  counts and an empty-state message. Filtering changes only the table view;
  cleanup quantities and confirmation still use the full reviewed plan.

### Fixed
- Accept normal capitalization and spaces in nation-name confirmations while
  still matching the selected nations; show field guidance and support Escape.
- Add subtle vertical separators to card table headers and rows without changing
  cell values, sorting, or row selection.
- Center progress-dialog headings above a recessed panel containing only
  the status line and progress bar.
- Preserve reviewed cards, quantities, filters, and cached previews when toggling
  faster execution; save the mode immediately and confirm it before execution.
- Refine progress dialogs with a clear task heading, full-width progress bar,
  separate count/time metrics, concise pacing text, and a quiet Stop control.
- Resolve names independently of cleanup eligibility when explicitly requested;
  preserve execution request counts and live safety checks.
- Repair corrupted UI punctuation in labels, status messages, and placeholders;
  shorten the faster-mode note and show it only when enabled.
- Execution ETA completion text now identifies cleanup rather than preview.

## [0.1.2]

### Changed
- Manage environments, dependencies, locking, builds, and the Windows launcher
  with Poetry 2.2+ and poetry-core.
- Declare the MIT license in package metadata and include LICENSE.

### Added
- Human and agent contribution guidance, commit conventions, issue/PR templates,
  security guidance, architecture, troubleshooting, and release instructions.
- Sphinx/MyST docs, Read the Docs configuration, and CI for tests, docs, and artifacts.

## [0.1.1]

### Fixed
- Qualify Windows Passport key names with the current user's SID to address
  key-creation error 0x80090027; identify native failing operations/properties.
- Run updated extracted source from the Windows launcher with an existing venv.

## [0.1.0]

### Added
- Initial local beta: cleanup library, Textual preview/confirmation workflow,
  per-account settings, and session/encrypted/Hello/keyring/plaintext credentials.

Historical entries describe the supplied source and README; they do not imply
published package releases or successful native credential-store verification.
