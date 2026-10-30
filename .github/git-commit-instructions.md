# Commit conventions

Use `<type>(<scope>): <imperative summary>` with a subject at most 72 characters.
Types: feat, fix, refactor, test, docs, chore, perf, revert. Useful scopes:
api, service, models, storage, credentials, hello, tui, launcher, packaging, ci,
docs, tests. Omit scope for broad changes. Explain why in the body and reference
related issues. Use ! and a BREAKING CHANGE footer for incompatible changes.

Examples:

```text
fix(service): stop after an uncertain junk response
docs: explain credential recovery limitations
chore(packaging): manage dependencies with Poetry
```

Update CHANGELOG.md for user-visible changes. Shipped behavior, packaging,
dependencies, native integration, and release automation also require a version
bump in pyproject.toml, once per change set. Docs/templates alone may skip it.
Do not duplicate the version into source files.
