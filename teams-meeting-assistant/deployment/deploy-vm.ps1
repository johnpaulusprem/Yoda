#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Deploys Teams Meeting Assistant (Python backend + C# Media Bot) on Azure Windows VM.

.DESCRIPTION
    Run this script on the Azure VM after RDP-ing in.
    It installs all prerequisites, clones the repo, sets up SSL, and starts both services.

.PARAMETER Domain
    The domain name pointing to this VM's public IP (e.g., yoda-bot.centralindia.cloudapp.azure.com)

.PARAMETER PublicIp
    The VM's public IP address

.PARAMETER RepoUrl
    Git clone URL for the project (HTTPS)

.EXAMPLE
    .\deploy-vm.ps1 -Domain "yoda-bot.centralindia.cloudapp.azure.com" -PublicIp "20.219.x.x"
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$Domain,

    [Parameter(Mandatory=$true)]
    [string]$PublicIp,

    [string]$RepoUrl = "",
    [string]$InstallDir = "C:\yoda"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Teams Meeting Assistant - VM Deployment"   -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Domain:    $Domain"
Write-Host "Public IP: $PublicIp"
Write-Host "Install:   $InstallDir"
Write-Host ""

# ── Step 1: Install prerequisites ───────────────────────────────────────────

Write-Host "[1/8] Installing prerequisites..." -ForegroundColor Yellow

# Install Chocolatey if not present
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:PATH += ";C:\ProgramData\chocolatey\bin"
}

# Install .NET 8 SDK
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    choco install dotnet-8.0-sdk -y
    $env:PATH += ";C:\Program Files\dotnet"
}

# Install Python 3.11+
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    choco install python311 -y
    $env:PATH += ";C:\Python311;C:\Python311\Scripts"
}

# Install Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    choco install git -y
    $env:PATH += ";C:\Program Files\Git\cmd"
}

# Install nginx
if (-not (Test-Path "C:\nginx")) {
    choco install nginx -y
}

# Install win-acme for Let's Encrypt certs
if (-not (Test-Path "C:\win-acme")) {
    choco install win-acme -y
}

# Install Redis
choco install redis-64 -y --force

Write-Host "[1/8] Prerequisites installed." -ForegroundColor Green

# ── Step 2: Clone / copy repo ───────────────────────────────────────────────

Write-Host "[2/8] Setting up project files..." -ForegroundColor Yellow

if (-not (Test-Path $InstallDir)) {
    if ($RepoUrl -ne "") {
        git clone $RepoUrl $InstallDir
    } else {
        Write-Host "  No RepoUrl provided. Copy project files to $InstallDir manually." -ForegroundColor Red
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }
}

Write-Host "[2/8] Project files ready." -ForegroundColor Green

# ── Step 3: Generate SSL certificate ────────────────────────────────────────

Write-Host "[3/8] Setting up SSL certificate..." -ForegroundColor Yellow

$certDir = "C:\nginx\conf\ssl"
New-Item -ItemType Directory -Path $certDir -Force | Out-Null

# Check if cert already exists
$existingCert = Get-ChildItem -Path Cert:\LocalMachine\My | Where-Object {
    $_.DnsNameList.Unicode -contains $Domain
} | Select-Object -First 1

if ($existingCert) {
    Write-Host "  Certificate already exists: $($existingCert.Thumbprint)" -ForegroundColor Green
    $certThumbprint = $existingCert.Thumbprint
} else {
    # Create self-signed cert for immediate use (replace with Let's Encrypt later)
    Write-Host "  Creating self-signed certificate for $Domain..."
    $cert = New-SelfSignedCertificate `
        -DnsName $Domain `
        -CertStoreLocation "Cert:\LocalMachine\My" `
        -NotAfter (Get-Date).AddYears(2) `
        -KeySpec KeyExchange `
        -KeyExportPolicy Exportable `
        -FriendlyName "Yoda Media Bot - $Domain"

    $certThumbprint = $cert.Thumbprint
    Write-Host "  Certificate created: $certThumbprint" -ForegroundColor Green

    # Export for nginx (PEM format)
    # Self-signed → export PFX then convert
    $pfxPass = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    $pfxPassword = ConvertTo-SecureString -String $pfxPass -Force -AsPlainText
    $pfxPath = "$certDir\mediabot.pfx"
    Export-PfxCertificate -Cert "Cert:\LocalMachine\My\$certThumbprint" -FilePath $pfxPath -Password $pfxPassword | Out-Null

    # Note: For nginx PEM files, you'll need openssl to convert:
    # openssl pkcs12 -in mediabot.pfx -out fullchain.pem -nokeys -clcerts
    # openssl pkcs12 -in mediabot.pfx -out privkey.pem -nocerts -nodes
    Write-Host "  PFX exported to $pfxPath. Convert to PEM for nginx if needed." -ForegroundColor Yellow
}

Write-Host "[3/8] SSL certificate ready (Thumbprint: $certThumbprint)." -ForegroundColor Green

# ── Step 4: Configure nginx ─────────────────────────────────────────────────

Write-Host "[4/8] Configuring nginx..." -ForegroundColor Yellow

$nginxConf = @"
worker_processes 1;

events {
    worker_connections 1024;
}

http {
    upstream media_bot {
        server 127.0.0.1:9441;
    }

    upstream python_backend {
        server 127.0.0.1:8000;
    }

    server {
        listen 443 ssl;
        server_name $Domain;

        ssl_certificate     $($certDir -replace '\\','/')/fullchain.pem;
        ssl_certificate_key $($certDir -replace '\\','/')/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;

        # Graph Communications callbacks → C# Media Bot
        location /api/callbacks {
            proxy_pass http://media_bot;
            proxy_set_header Host `$host;
            proxy_set_header X-Real-IP `$remote_addr;
            proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto `$scheme;
            proxy_read_timeout 60s;
        }

        # Everything else → Python FastAPI backend
        location / {
            proxy_pass http://python_backend;
            proxy_set_header Host `$host;
            proxy_set_header X-Real-IP `$remote_addr;
            proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto `$scheme;
            proxy_read_timeout 60s;
            proxy_http_version 1.1;
            proxy_set_header Upgrade `$http_upgrade;
            proxy_set_header Connection "upgrade";
        }
    }

    server {
        listen 80;
        server_name $Domain;
        return 301 https://`$host`$request_uri;
    }
}
"@

$nginxConf | Out-File -FilePath "C:\nginx\conf\nginx.conf" -Encoding UTF8 -Force
Write-Host "[4/8] nginx configured." -ForegroundColor Green

# ── Step 5: Update application configs ──────────────────────────────────────

Write-Host "[5/8] Updating application configuration..." -ForegroundColor Yellow

# Update Python .env.production with domain
$envProd = "$InstallDir\.env.production"
if (Test-Path $envProd) {
    $envContent = Get-Content $envProd -Raw
    $envContent = $envContent -replace "REPLACE_WITH_VM_DOMAIN", $Domain
    $envContent | Set-Content $envProd -Encoding UTF8
    Write-Host "  Python .env.production domain updated." -ForegroundColor Green
}

# Prompt for secrets that go into environment variables (not config files)
Write-Host ""
Write-Host "  Enter Azure credentials (these are set as environment variables, not stored in config files):" -ForegroundColor Cyan
$appId = Read-Host "  Azure App ID (Bot)"
$appSecret = Read-Host "  Azure App Secret"
$tenantId = Read-Host "  Azure Tenant ID"
$speechKey = Read-Host "  Azure Speech Subscription Key"
$hmacKey = Read-Host "  Inter-service HMAC Key"

# Store secrets in a .env file for the Media Bot service (read by NSSM)
$mediaBotEnv = @"
Bot__AppId=$appId
Bot__AppSecret=$appSecret
Bot__TenantId=$tenantId
Bot__BotBaseUrl=https://$Domain
Bot__CertificateThumbprint=$certThumbprint
Bot__MediaPlatformInstancePublicIp=$PublicIp
Speech__SubscriptionKey=$speechKey
PythonBackend__HmacKey=$hmacKey
"@
$mediaBotEnv | Set-Content "$InstallDir\media-bot-secrets.env" -Encoding UTF8
Write-Host "  Media Bot secrets saved to media-bot-secrets.env" -ForegroundColor Green

# Update Python .env.production with secrets
$envContent = Get-Content $envProd -Raw
$envContent = $envContent -replace "^AZURE_TENANT_ID=.*$", "AZURE_TENANT_ID=$tenantId"
$envContent = $envContent -replace "^AZURE_CLIENT_ID=.*$", "AZURE_CLIENT_ID=$appId"
$envContent = $envContent -replace "^AZURE_CLIENT_SECRET=.*$", "AZURE_CLIENT_SECRET=$appSecret"
$envContent = $envContent -replace "^INTER_SERVICE_HMAC_KEY=.*$", "INTER_SERVICE_HMAC_KEY=$hmacKey"
# Prompt remaining Python secrets
$acsConn = Read-Host "  ACS Connection String"
$acsEndpoint = Read-Host "  ACS Endpoint"
$aiEndpoint = Read-Host "  AI Foundry Endpoint"
$aiKey = Read-Host "  AI Foundry API Key"
$dbUrl = Read-Host "  Database URL (postgresql+asyncpg://...)"
$envContent = $envContent -replace "^ACS_CONNECTION_STRING=.*$", "ACS_CONNECTION_STRING=$acsConn"
$envContent = $envContent -replace "^ACS_ENDPOINT=.*$", "ACS_ENDPOINT=$acsEndpoint"
$envContent = $envContent -replace "^AI_FOUNDRY_ENDPOINT=.*$", "AI_FOUNDRY_ENDPOINT=$aiEndpoint"
$envContent = $envContent -replace "^AI_FOUNDRY_API_KEY=.*$", "AI_FOUNDRY_API_KEY=$aiKey"
$envContent = $envContent -replace "^DATABASE_URL=.*$", "DATABASE_URL=$dbUrl"
$envContent | Set-Content $envProd -Encoding UTF8
Write-Host "  Python .env.production secrets updated." -ForegroundColor Green

Write-Host "[5/8] Configuration updated." -ForegroundColor Green

# ── Step 6: Install Python dependencies ─────────────────────────────────────

Write-Host "[6/8] Installing Python dependencies..." -ForegroundColor Yellow

Push-Location $InstallDir
if (Test-Path "requirements.txt") {
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
}
Pop-Location

Write-Host "[6/8] Python dependencies installed." -ForegroundColor Green

# ── Step 7: Build C# Media Bot ──────────────────────────────────────────────

Write-Host "[7/8] Building C# Media Bot..." -ForegroundColor Yellow

$mediaBotDir = "$InstallDir\media-bot\src\MediaBot"
if (Test-Path $mediaBotDir) {
    Push-Location $mediaBotDir
    dotnet publish -c Release -o "$InstallDir\media-bot\publish"
    Pop-Location
    Write-Host "  Media Bot built → $InstallDir\media-bot\publish" -ForegroundColor Green
}

Write-Host "[7/8] Media Bot built." -ForegroundColor Green

# ── Step 8: Create Windows Services ─────────────────────────────────────────

Write-Host "[8/8] Creating Windows services..." -ForegroundColor Yellow

# Create service for Media Bot using NSSM (Non-Sucking Service Manager)
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    choco install nssm -y
}

# Remove old services if they exist
nssm remove YodaMediaBot confirm 2>$null
nssm remove YodaPythonBackend confirm 2>$null
nssm remove YodaNginx confirm 2>$null

# Media Bot service
nssm install YodaMediaBot "dotnet" "$InstallDir\media-bot\publish\MediaBot.dll"
nssm set YodaMediaBot AppDirectory "$InstallDir\media-bot\publish"
# Load secrets from media-bot-secrets.env as environment variables
$mediaBotSecrets = Get-Content "$InstallDir\media-bot-secrets.env" | Where-Object { $_ -match "=" }
$envArgs = @("ASPNETCORE_ENVIRONMENT=Production", "DOTNET_ENVIRONMENT=Production")
foreach ($line in $mediaBotSecrets) { $envArgs += $line.Trim() }
nssm set YodaMediaBot AppEnvironmentExtra $envArgs
nssm set YodaMediaBot DisplayName "Yoda Media Bot"
nssm set YodaMediaBot Description "Teams Meeting Assistant - C# Media Bot"
nssm set YodaMediaBot Start SERVICE_AUTO_START
nssm set YodaMediaBot AppStdout "$InstallDir\logs\media-bot.log"
nssm set YodaMediaBot AppStderr "$InstallDir\logs\media-bot-error.log"

# Python Backend service
$pythonPath = (Get-Command python).Source
nssm install YodaPythonBackend "$pythonPath" "-m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"
nssm set YodaPythonBackend AppDirectory "$InstallDir"
nssm set YodaPythonBackend AppEnvironmentExtra "ENV_FILE=$InstallDir\.env.production"
nssm set YodaPythonBackend DisplayName "Yoda Python Backend"
nssm set YodaPythonBackend Description "Teams Meeting Assistant - Python FastAPI Backend"
nssm set YodaPythonBackend Start SERVICE_AUTO_START
nssm set YodaPythonBackend AppStdout "$InstallDir\logs\python-backend.log"
nssm set YodaPythonBackend AppStderr "$InstallDir\logs\python-backend-error.log"

# nginx service
nssm install YodaNginx "C:\nginx\nginx.exe"
nssm set YodaNginx AppDirectory "C:\nginx"
nssm set YodaNginx DisplayName "Yoda Nginx"
nssm set YodaNginx Start SERVICE_AUTO_START

# Create logs directory
New-Item -ItemType Directory -Path "$InstallDir\logs" -Force | Out-Null

Write-Host "[8/8] Windows services created." -ForegroundColor Green

# ── Summary ─────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Services created:"
Write-Host "  - YodaMediaBot     (dotnet, port 9441 + media 8445)"
Write-Host "  - YodaPythonBackend (uvicorn, port 8000)"
Write-Host "  - YodaNginx        (SSL proxy, port 443)"
Write-Host ""
Write-Host "SSL Certificate Thumbprint: $certThumbprint"
Write-Host ""
Write-Host "NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Convert PFX to PEM for nginx:"
Write-Host "       openssl pkcs12 -in $certDir\mediabot.pfx -out $certDir\fullchain.pem -nokeys -clcerts"
Write-Host "       openssl pkcs12 -in $certDir\mediabot.pfx -out $certDir\privkey.pem -nocerts -nodes"
Write-Host "  2. Start services:"
Write-Host "       nssm start YodaNginx"
Write-Host "       nssm start YodaMediaBot"
Write-Host "       nssm start YodaPythonBackend"
Write-Host "  3. Update Azure Bot messaging endpoint to:"
Write-Host "       https://$Domain/api/callbacks"
Write-Host "  4. Open Windows Firewall for ports 443, 8445 (TCP+UDP)"
Write-Host "  5. For Let's Encrypt (production cert):"
Write-Host "       wacs.exe --target manual --host $Domain --store pemfiles --pemfilespath $certDir"
Write-Host ""
Write-Host "Logs: $InstallDir\logs\"
Write-Host ""
