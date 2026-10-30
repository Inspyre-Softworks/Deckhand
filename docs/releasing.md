# Release checklist

The source version in pyproject.toml is authoritative. Poetry-core builds the
wheel and source distribution. CI retains artifacts but does not publish them.

1. Review user-facing changes and native credential integration limitations.
2. Update the version once and move Unreleased notes into the version's entry
   in CHANGELOG.md. Do not invent release dates for unpublished versions.
3. Run the same checks as contributors and CI:

   ```console
   poetry install --with dev,docs --no-interaction
   poetry check --lock
   poetry run pytest
   poetry run sphinx-build -W --keep-going -b html docs docs/_build/local-html
   poetry build
   ```

4. Inspect the wheel and sdist for correct metadata, MIT license, and absence
   of credentials/configuration. Test wheel installation in a disposable
   environment and check `deckhand --help`; use demo mode for UI smoke checks.
5. Record native Windows Hello and Linux keyring checks separately. Mocked tests
   do not certify native unlock, and no release check should junk live cards.
6. A maintainer reviews and explicitly publishes approved artifacts/tags.
   PyPI trusted publishing, GitHub releases, and Windows installers are not
   configured by this scaffold.

Read the Docs can import the repository using .readthedocs.yaml. Hosting setup
and repository URLs are external configuration; a local docs build does not
mean a hosted site has been published.
