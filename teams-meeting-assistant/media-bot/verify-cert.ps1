param(
    [Parameter(Mandatory=$true)]
    [string]$Thumbprint
)
$cert = Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $Thumbprint }
if ($cert) { Write-Output "FOUND:$($cert.Thumbprint) Subject:$($cert.Subject)" } else { Write-Output "NOT_FOUND" }
