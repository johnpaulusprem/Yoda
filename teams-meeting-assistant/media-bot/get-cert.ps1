param(
    [string]$Subject = "localhost"
)
$cert = Get-ChildItem -Path Cert:\CurrentUser\My | Where-Object { $_.Subject -like "*$Subject*" } | Select-Object -First 1
if ($cert) {
    Write-Output $cert.Thumbprint
} else {
    Write-Output "NO_CERT_FOUND"
}
