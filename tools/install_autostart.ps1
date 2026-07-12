# Installa l'avvio automatico del server vocale locale su Windows.
# ESEGUIRE COME AMMINISTRATORE (serve per la regola del firewall).
#   Clic destro su PowerShell -> "Esegui come amministratore", poi:
#   powershell -ExecutionPolicy Bypass -File tools\install_autostart.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$taskName = "SqueezeSay"
$runner = Join-Path $repo "tools\run_local.ps1"
$port = 8730

# 1) Scheduled Task: avvia il server all'accesso dell'utente, nascosto, con riavvio.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "SqueezeSay - server vocale locale per Daphile/LMS" -Force | Out-Null
Write-Host "Scheduled Task '$taskName' registrato (avvio all'accesso utente)."

# 2) Firewall: consenti connessioni in ingresso sulla porta (per il telefono).
try {
  New-NetFirewallRule -DisplayName "SqueezeSay $port" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort $port -Profile Private -ErrorAction Stop | Out-Null
  Write-Host "Regola firewall aggiunta per la porta $port (profilo Private)."
} catch {
  Write-Warning "Regola firewall non aggiunta (serve Amministratore): $($_.Exception.Message)"
}

# 3) Avvia subito.
Start-ScheduledTask -TaskName $taskName
Write-Host "Avviato. Apri dal telefono: https://<ip-di-questo-pc>:$port"
