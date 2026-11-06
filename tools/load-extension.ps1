# Walks through loading the extension, one browser at a time. Browsers ignore extensions-page
# addresses passed in from other programs, and they don't let a script press these buttons,
# so this puts the right text on the clipboard for each step and checks the result afterwards.
[CmdletBinding()]
param(
    [string]$EdgeProfile = (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\Default'),
    [string]$ChromeProfile = (Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default'),
    [switch]$Status
)

$Folder = Join-Path (Split-Path $PSScriptRoot -Parent) 'extension'
$WaitSeconds = 25

$Browsers = @(
    @{
        Name = 'Edge'; Program = 'msedge'; Address = 'edge://extensions'; Profile = $EdgeProfile
        SwitchAt = 'in the left sidebar, near the bottom'
        ButtonAt = 'near the top of the page'
    }
    @{
        Name = 'Chrome'; Program = 'chrome'; Address = 'chrome://extensions'; Profile = $ChromeProfile
        SwitchAt = 'at the top right of the page'
        ButtonAt = 'at the top left of the page'
    }
)

function Test-Loaded($browser) {
    foreach ($file in 'Secure Preferences', 'Preferences') {
        $path = Join-Path $browser.Profile $file
        if ((Test-Path -LiteralPath $path) -and ((Get-Content -LiteralPath $path -Raw) -match 'ad blocker')) {
            return $true
        }
    }
    return $false
}

if ($Status) {
    foreach ($browser in $Browsers) {
        $state = if (Test-Loaded $browser) { 'loaded' } else { 'not loaded' }
        Write-Output "$($browser.Name): $state"
    }
    exit 0
}

foreach ($browser in $Browsers) {
    Write-Host ''
    Write-Host "=== $($browser.Name) ===" -ForegroundColor Cyan
    if (Test-Loaded $browser) {
        Write-Host "$($browser.Name) already has the extension. Nothing to do here." -ForegroundColor Green
        continue
    }

    Set-Clipboard $browser.Address
    try {
        Start-Process $browser.Program -ErrorAction Stop
    } catch {
        Write-Host "Please open $($browser.Name) yourself."
    }
    Write-Host "1. Go to $($browser.Name). Click the address bar at the very top of the window."
    Write-Host "2. Press Ctrl+V, then press Enter. The Extensions page opens."
    Read-Host 'When you can see the Extensions page, come back here and press Enter'

    Set-Clipboard $Folder
    Write-Host ''
    Write-Host "3. In $($browser.Name), turn on the 'Developer mode' switch, $($browser.SwitchAt)."
    Write-Host "4. Click the 'Load unpacked' button, $($browser.ButtonAt). A folder window opens."
    Write-Host '5. Click the address bar at the top of that folder window, press Ctrl+V, press Enter.'
    Write-Host "6. Click the 'Select Folder' button."
    Write-Host "A card named 'Local Ad Blocker' should appear on the page."
    Read-Host 'When you have done that, come back here and press Enter'

    Write-Host 'Checking...'
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $loaded = $false
    while (-not $loaded -and (Get-Date) -lt $deadline) {
        $loaded = Test-Loaded $browser
        if (-not $loaded) { Start-Sleep -Seconds 2 }
    }
    if ($loaded) {
        Write-Host "$($browser.Name): loaded." -ForegroundColor Green
    } else {
        Write-Host "$($browser.Name): I can't see it yet. If an error appeared, tell Claude what it says." -ForegroundColor Yellow
    }
}

Write-Host ''
Write-Host 'Finished.'
