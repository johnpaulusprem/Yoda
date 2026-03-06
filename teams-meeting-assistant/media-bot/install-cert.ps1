param(
    [Parameter(Mandatory=$true)]
    [string]$Thumbprint,

    [string]$ExportPassword = (-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }))
)

# Export dev cert from CurrentUser and import to LocalMachine
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Thumbprint -eq $Thumbprint }
if (-not $cert) {
    Write-Error "Certificate not found in CurrentUser\My with thumbprint $Thumbprint"
    exit 1
}

# Export to temp PFX
$password = ConvertTo-SecureString -String $ExportPassword -Force -AsPlainText
$tempPfx = "$env:TEMP\mediabot-cert.pfx"
Export-PfxCertificate -Cert $cert -FilePath $tempPfx -Password $password | Out-Null

# Import to LocalMachine\My
Import-PfxCertificate -FilePath $tempPfx -CertStoreLocation Cert:\LocalMachine\My -Password $password | Out-Null

# Clean up
Remove-Item $tempPfx -Force

# Verify
$installed = Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object { $_.Thumbprint -eq $Thumbprint }
if ($installed) {
    Write-Output "SUCCESS: Certificate installed to LocalMachine\My (Thumbprint: $($installed.Thumbprint))"
} else {
    Write-Error "FAILED: Certificate not found in LocalMachine\My after import"
}
