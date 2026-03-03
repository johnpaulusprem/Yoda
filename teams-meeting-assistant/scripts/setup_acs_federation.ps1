<#
.SYNOPSIS
    Enable Azure Communication Services (ACS) - Teams interop federation.

.DESCRIPTION
    This script configures the Teams tenant to allow ACS users (bots) to join
    Teams meetings.  It must be run ONCE by a user who holds the
    **Teams Administrator** role.

    Prerequisites:
      - PowerShell 5.1+ or PowerShell 7+
      - Internet access to the PowerShell Gallery
      - Teams Administrator credentials

    After running this script, ACS bots created with Call Automation will be
    able to join Teams meetings as external participants and capture
    audio / transcription independently of the native Teams recording settings.

.NOTES
    Reference: https://learn.microsoft.com/en-us/azure/communication-services/concepts/teams-interop

.EXAMPLE
    .\setup_acs_federation.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  ACS-Teams Interop Federation Setup" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# ---------- Step 1: Install / Update MicrosoftTeams module ----------

$moduleName = "MicrosoftTeams"
$installed = Get-Module -ListAvailable -Name $moduleName | Select-Object -First 1

if (-not $installed) {
    Write-Host "[1/4] Installing $moduleName PowerShell module..." -ForegroundColor Yellow
    Install-Module -Name $moduleName -Force -AllowClobber -Scope CurrentUser
    Write-Host "      Module installed." -ForegroundColor Green
} else {
    Write-Host "[1/4] $moduleName module already installed (v$($installed.Version))." -ForegroundColor Green
    # Check for updates
    $latest = Find-Module -Name $moduleName -ErrorAction SilentlyContinue
    if ($latest -and $latest.Version -gt $installed.Version) {
        Write-Host "      A newer version ($($latest.Version)) is available.  Updating..." -ForegroundColor Yellow
        Update-Module -Name $moduleName -Force -Scope CurrentUser
        Write-Host "      Updated to v$($latest.Version)." -ForegroundColor Green
    }
}

# ---------- Step 2: Connect to Microsoft Teams ----------

Write-Host "[2/4] Connecting to Microsoft Teams..." -ForegroundColor Yellow
Write-Host "      A browser window will open for authentication." -ForegroundColor Gray
Write-Host "      Sign in with an account that has the Teams Administrator role." -ForegroundColor Gray
Write-Host ""

try {
    Connect-MicrosoftTeams
    Write-Host "      Connected successfully." -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to connect to Microsoft Teams." -ForegroundColor Red
    Write-Host "       Ensure you have the Teams Administrator role." -ForegroundColor Red
    Write-Host "       Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------- Step 3: Enable ACS federation ----------

Write-Host "[3/4] Enabling ACS-Teams federation..." -ForegroundColor Yellow

try {
    # Read the current configuration so we can report the before/after state
    $before = Get-CsTeamsAcsFederationConfiguration
    Write-Host "      Current EnableAcsUsers: $($before.EnableAcsUsers)" -ForegroundColor Gray

    if ($before.EnableAcsUsers -eq $true) {
        Write-Host "      ACS federation is ALREADY enabled.  No changes needed." -ForegroundColor Green
    } else {
        Set-CsTeamsAcsFederationConfiguration -EnableAcsUsers $true
        Write-Host "      ACS federation has been ENABLED." -ForegroundColor Green
    }
} catch {
    Write-Host "ERROR: Failed to configure ACS federation." -ForegroundColor Red
    Write-Host "       Error: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# ---------- Step 4: Verify ----------

Write-Host "[4/4] Verifying configuration..." -ForegroundColor Yellow

try {
    $after = Get-CsTeamsAcsFederationConfiguration
    Write-Host ""
    Write-Host "  EnableAcsUsers          : $($after.EnableAcsUsers)" -ForegroundColor White
    Write-Host "  AllowedAcsResources     : $($after.AllowedAcsResources -join ', ')" -ForegroundColor White
    Write-Host ""

    if ($after.EnableAcsUsers -eq $true) {
        Write-Host "SUCCESS: ACS federation is enabled." -ForegroundColor Green
        Write-Host "         ACS bots can now join Teams meetings." -ForegroundColor Green
    } else {
        Write-Host "WARNING: EnableAcsUsers is still False." -ForegroundColor Yellow
        Write-Host "         The change may take a few minutes to propagate." -ForegroundColor Yellow
        Write-Host "         Re-run 'Get-CsTeamsAcsFederationConfiguration' in a few minutes." -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: Could not verify.  Error: $($_.Exception.Message)" -ForegroundColor Yellow
}

# ---------- Optional: Restrict to specific ACS resources ----------

Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  Optional: Restrict federation to specific ACS resources" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  By default, ANY ACS resource can join meetings in this tenant." -ForegroundColor Gray
Write-Host "  To restrict to your specific ACS resource(s), run:" -ForegroundColor Gray
Write-Host ""
Write-Host '  $allowList = @("<your-acs-resource-id>")' -ForegroundColor White
Write-Host '  Set-CsTeamsAcsFederationConfiguration `' -ForegroundColor White
Write-Host '      -EnableAcsUsers $true `' -ForegroundColor White
Write-Host '      -AllowedAcsResources $allowList' -ForegroundColor White
Write-Host ""
Write-Host "  The ACS resource ID is the immutable resource ID found in the" -ForegroundColor Gray
Write-Host "  Azure portal under your Communication Services resource overview." -ForegroundColor Gray
Write-Host ""

# ---------- Disconnect ----------

Write-Host "Disconnecting from Microsoft Teams..." -ForegroundColor Gray
Disconnect-MicrosoftTeams -Confirm:$false -ErrorAction SilentlyContinue
Write-Host "Done." -ForegroundColor Green
