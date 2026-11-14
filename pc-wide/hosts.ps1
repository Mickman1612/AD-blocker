# Turns PC-wide ad blocking on or off by editing a marked section of the Windows hosts file.
# Changing the real hosts file needs administrator rights. Everything else in it is left alone.
[CmdletBinding()]
param(
    [string]$HostsPath = (Join-Path $env:WINDIR 'System32\drivers\etc\hosts'),
    [string]$BackupPath,
    [switch]$Off,
    [switch]$Status,
    [switch]$NoFlush
)

$ErrorActionPreference = 'Stop'
# Not a parameter default: when a script is run directly, $PSScriptRoot is empty up there.
if (-not $BackupPath) { $BackupPath = Join-Path $PSScriptRoot 'hosts.original' }
$Begin = '# BEGIN Local Ad Blocker'
$End = '# END Local Ad Blocker'
$TestName = 'securepubads.g.doubleclick.net'

# A one-byte-per-character encoding reads and writes any existing file back byte for byte.
$Bytes = [Text.Encoding]::GetEncoding(28591)
$BlockPattern = '\r?\n' + [regex]::Escape($Begin) + '[\s\S]*?' + [regex]::Escape($End) + '\r?\n'

function Read-Hosts {
    if (Test-Path -LiteralPath $HostsPath) { return [IO.File]::ReadAllText($HostsPath, $Bytes) }
    return ''
}

function Show-Status {
    if ((Read-Hosts).Contains($Begin)) {
        try {
            $addresses = [Net.Dns]::GetHostAddresses($TestName) | ForEach-Object { $_.ToString() }
        } catch {
            $addresses = @('no address')
        }
        Write-Output "PC-wide blocking is ON. Test lookup of an ad server: $($addresses -join ', ')"
    } else {
        Write-Output 'PC-wide blocking is OFF.'
    }
}

try {
    if ($Status) {
        Show-Status
        # 3 means off, so the double-click file can tell when the permission step didn't happen.
        if ((Read-Hosts).Contains($Begin)) { exit 0 } else { exit 3 }
    }

    $current = Read-Hosts
    $clean = [regex]::Replace($current, $BlockPattern, '')

    if ($Off) {
        if ($clean -ceq $current) {
            Write-Output 'PC-wide blocking was already off. Nothing changed.'
        } else {
            [IO.File]::WriteAllText($HostsPath, $clean, $Bytes)
            Write-Output 'PC-wide blocking is off. Your other hosts entries are unchanged.'
        }
    } else {
        $block = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'hosts-block.txt'), $Bytes).TrimEnd()
        $block = $block -replace '\r?\n', "`r`n"
        if (-not (Test-Path -LiteralPath $BackupPath)) {
            [IO.File]::WriteAllText($BackupPath, $clean, $Bytes)
        }
        [IO.File]::WriteAllText($HostsPath, $clean + "`r`n" + $block + "`r`n", $Bytes)
        Write-Output 'PC-wide blocking is on.'
    }

    if (-not $NoFlush) {
        & ipconfig /flushdns | Out-Null
    }
} catch {
    Write-Output "Couldn't update the hosts file, so nothing changed: $($_.Exception.Message)"
    exit 1
}
