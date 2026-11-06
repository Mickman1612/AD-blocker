# The one part that needs administrator rights: the certificate and the hosts file.
# The certificate's private key no longer exists, so it can't be used to issue anything new.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CaPath,
    [switch]$Off
)

$Name = 'Local Ad Blocker Root'
$HostsScript = Join-Path (Split-Path $PSScriptRoot -Parent) 'pc-wide\hosts.ps1'

# Remove any earlier copy first, so there is never more than one.
for ($attempt = 0; $attempt -lt 3; $attempt++) {
    & certutil -delstore Root $Name 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { break }
}

if ($Off) {
    & $HostsScript -Off
} else {
    & certutil -addstore -f Root $CaPath 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { exit 1 }
    & $HostsScript
}
