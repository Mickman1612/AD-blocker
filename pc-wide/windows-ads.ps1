# Turns off the ads and promotions built into Windows for this user, and can undo it.
# These are ordinary per-user settings. No administrator rights are needed.
[CmdletBinding()]
param(
    [string]$Root = 'HKCU:',
    [string]$BackupPath,
    [switch]$Undo
)

$ErrorActionPreference = 'Stop'
# Not a parameter default: when a script is run directly, $PSScriptRoot is empty up there.
if (-not $BackupPath) { $BackupPath = Join-Path $PSScriptRoot 'windows-settings.backup.json' }
$Delivery = 'Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager'
$Explorer = 'Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'

# Every setting here is turned off by writing 0.
$Settings = @(
    @{ Path = $Delivery; Name = 'SubscribedContent-338388Enabled' }      # Start menu suggestions
    @{ Path = $Delivery; Name = 'SubscribedContent-338389Enabled' }      # Tips and suggestions
    @{ Path = $Delivery; Name = 'SubscribedContent-338393Enabled' }      # Suggestions in Settings
    @{ Path = $Delivery; Name = 'SubscribedContent-353694Enabled' }      # Suggestions in Settings
    @{ Path = $Delivery; Name = 'SubscribedContent-353696Enabled' }      # Suggestions in Settings
    @{ Path = $Delivery; Name = 'SubscribedContent-338387Enabled' }      # Facts and tips on the lock screen
    @{ Path = $Delivery; Name = 'SubscribedContent-310093Enabled' }      # Welcome screens after updates
    @{ Path = $Delivery; Name = 'RotatingLockScreenOverlayEnabled' }     # Promotions on the lock screen
    @{ Path = $Delivery; Name = 'SystemPaneSuggestionsEnabled' }         # Start menu suggestions
    @{ Path = $Delivery; Name = 'SoftLandingEnabled' }                   # Tips as you use Windows
    @{ Path = $Delivery; Name = 'SilentInstalledAppsEnabled' }           # Promoted apps installing themselves
    @{ Path = $Explorer; Name = 'ShowSyncProviderNotifications' }        # Ads in File Explorer
    @{ Path = $Explorer; Name = 'Start_IrisRecommendations' }            # Promotions in Start's Recommended
    @{ Path = 'Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo'; Name = 'Enabled' }  # Advertising ID
    @{ Path = 'Software\Microsoft\Windows\CurrentVersion\Privacy'; Name = 'TailoredExperiencesWithDiagnosticDataEnabled' }
    @{ Path = 'Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement'; Name = 'ScoobeSystemSettingEnabled' }  # "Finish setting up"
    @{ Path = 'Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\Windows.SystemToast.Suggested'; Name = 'Enabled' }
)

function Get-RegistryPath([string]$Path) { return Join-Path $Root $Path }

function Get-Current([string]$Path, [string]$Name) {
    $key = Get-RegistryPath $Path
    if (-not (Test-Path -LiteralPath $key)) { return $null }
    $item = Get-ItemProperty -LiteralPath $key -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    return $item.$Name
}

function Set-Value([string]$Path, [string]$Name, [int]$Value) {
    $key = Get-RegistryPath $Path
    if (-not (Test-Path -LiteralPath $key)) { New-Item -Path $key -Force | Out-Null }
    New-ItemProperty -LiteralPath $key -Name $Name -Value $Value -PropertyType DWord -Force | Out-Null
}

try {
    if ($Undo) {
        if (-not (Test-Path -LiteralPath $BackupPath)) {
            Write-Output 'Nothing to undo: these Windows settings were not changed by this tool.'
            exit 0
        }
        foreach ($entry in (Get-Content -LiteralPath $BackupPath -Raw | ConvertFrom-Json)) {
            if ($entry.Existed) {
                Set-Value $entry.Path $entry.Name $entry.Value
            } else {
                $key = Get-RegistryPath $entry.Path
                if (Test-Path -LiteralPath $key) {
                    Remove-ItemProperty -LiteralPath $key -Name $entry.Name -ErrorAction SilentlyContinue
                }
            }
        }
        Remove-Item -LiteralPath $BackupPath
        Write-Output 'Windows ad settings are back as they were.'
        exit 0
    }

    # Only the first run records the originals, so undo always returns to the user's own settings.
    if (-not (Test-Path -LiteralPath $BackupPath)) {
        $backup = foreach ($setting in $Settings) {
            $value = Get-Current $setting.Path $setting.Name
            [pscustomobject]@{ Path = $setting.Path; Name = $setting.Name; Existed = ($null -ne $value); Value = $value }
        }
        $backup | ConvertTo-Json | Set-Content -LiteralPath $BackupPath -Encoding UTF8
    }
    foreach ($setting in $Settings) {
        Set-Value $setting.Path $setting.Name 0
    }
    Write-Output "Turned off $($Settings.Count) Windows ad settings. Some apply only after you sign out and back in."
} catch {
    Write-Output "Couldn't update Windows ad settings: $($_.Exception.Message)"
    exit 1
}
