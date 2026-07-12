# Start the local voice server in HTTPS (so the microphone works from a phone).
# Uses the venv python created by `uv sync`. The LMS server is auto-discovered on
# the LAN; pass `-Lms http://IP:9000` to pin it if discovery doesn't find it.
param([string]$Lms = "", [int]$Port = 8730)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$py   = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path $py)) { throw "Venv mancante: esegui prima 'uv sync' in $repo" }
if (-not (Test-Path (Join-Path $repo "cert.pem"))) {
  & $py (Join-Path $repo "tools\make_cert.py")
}

$serverArgs = @((Join-Path $repo "localvoice\server.py"),
  "--port", $Port,
  "--cert", (Join-Path $repo "cert.pem"), "--key", (Join-Path $repo "key.pem"))
if ($Lms) { $serverArgs += @("--lms", $Lms) }

& $py @serverArgs
