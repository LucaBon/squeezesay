# Rimuove l'avvio automatico e la regola firewall. Esegui come Amministratore.
$taskName = "SqueezeSay"
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "SqueezeSay 8730" -ErrorAction SilentlyContinue
Write-Host "Avvio automatico rimosso."
