[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Uri,
    [ValidateRange(1, 900)]
    [int]$TimeoutSeconds = 240,
    [ValidateRange(1, 30)]
    [int]$RequestTimeoutSeconds = 3,
    [ValidateRange(100, 5000)]
    [int]$PollMilliseconds = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Parsed = $null
if (-not [Uri]::TryCreate($Uri, [UriKind]::Absolute, [ref]$Parsed)) {
    [Console]::Error.WriteLine('URI HTTP invalide.')
    exit 2
}
if ($Parsed.Scheme -ne 'http' -or $Parsed.Host -notin @('127.0.0.1', 'localhost', '::1')) {
    [Console]::Error.WriteLine('Seules les sondes HTTP en boucle locale sont autorisees.')
    exit 2
}

$Deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
$Attempts = 0
do {
    $Attempts++
    try {
        $Response = Invoke-WebRequest -UseBasicParsing -Uri $Parsed.AbsoluteUri -TimeoutSec $RequestTimeoutSeconds
        if ([int]$Response.StatusCode -eq 200) {
            Write-Output ("ready attempts={0}" -f $Attempts)
            exit 0
        }
    } catch {
        # Une connexion refusee ou une reponse HTTP transitoire est attendue
        # pendant l'initialisation. La borne globale reste autoritative.
    }
    if ([DateTimeOffset]::UtcNow -lt $Deadline) {
        Start-Sleep -Milliseconds $PollMilliseconds
    }
} while ([DateTimeOffset]::UtcNow -lt $Deadline)

[Console]::Error.WriteLine(("Service loopback indisponible apres {0}s ({1} tentatives)." -f $TimeoutSeconds, $Attempts))
exit 1
