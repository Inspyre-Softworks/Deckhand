# Changelog

Versions follow semantic versioning while the 0.x series remains a beta; review
release notes for compatibility changes.

## [Unreleased]

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
