param([switch]$Demo)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command poetry -ErrorAction SilentlyContinue)) {
    throw 'Install Poetry 2.2 or newer, then run this launcher again. See CONTRIBUTING.md.'
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & poetry install --only main --no-interaction
    if ($LASTEXITCODE -ne 0) { throw 'Could not install Deckhand with Poetry.' }
    if ($Demo) { & poetry run deckhand --demo }
    else { & poetry run deckhand }
    if ($LASTEXITCODE -ne 0) { throw 'Deckhand exited with an error.' }
}
finally { Pop-Location }
