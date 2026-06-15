Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot

Push-Location (Join-Path $Root "backend")
try {
  python -m pytest
}
finally {
  Pop-Location
}

Push-Location (Join-Path $Root "frontend")
try {
  npm run build
}
finally {
  Pop-Location
}
