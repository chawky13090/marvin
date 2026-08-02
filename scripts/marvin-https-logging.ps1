function Write-MarvinHttpsEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][ValidateSet('success', 'failure', 'planned')][string]$Result,
        [hashtable]$Context = @{}
    )

    try {
        $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
        $LogRoot = Join-Path $ProjectRoot 'runtime\logs'
        $LogPath = Join-Path $LogRoot 'https-security.jsonl'
        New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

        if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -ge 10MB) {
            $Archive = Join-Path $LogRoot ("https-security-{0}.jsonl" -f [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))
            Move-Item -LiteralPath $LogPath -Destination $Archive
        }
        $Archives = @(Get-ChildItem -LiteralPath $LogRoot -Filter 'https-security-*.jsonl' -File |
            Sort-Object LastWriteTimeUtc -Descending)
        foreach ($Expired in @($Archives | Where-Object { $_.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddDays(-90) })) {
            Remove-Item -LiteralPath $Expired.FullName -Force -ErrorAction SilentlyContinue
        }
        $Archives = @(Get-ChildItem -LiteralPath $LogRoot -Filter 'https-security-*.jsonl' -File |
            Sort-Object LastWriteTimeUtc -Descending)
        foreach ($Excess in @($Archives | Select-Object -Skip 30)) {
            Remove-Item -LiteralPath $Excess.FullName -Force -ErrorAction SilentlyContinue
        }
        $Archives = @(Get-ChildItem -LiteralPath $LogRoot -Filter 'https-security-*.jsonl' -File |
            Sort-Object LastWriteTimeUtc)
        $TotalBytes = [long](@($Archives | Measure-Object -Property Length -Sum).Sum)
        foreach ($Oldest in $Archives) {
            if ($TotalBytes -le 300MB) { break }
            $TotalBytes -= $Oldest.Length
            Remove-Item -LiteralPath $Oldest.FullName -Force -ErrorAction SilentlyContinue
        }

        $Event = [ordered]@{
            timestamp = [DateTimeOffset]::UtcNow.ToString('o')
            level = if ($Result -eq 'failure') { 'ERROR' } else { 'INFO' }
            component = 'marvin-https-security'
            action = $Action
            correlation_id = [Guid]::NewGuid().ToString('N')
            result = $Result
            context = $Context
        }
        Add-Content -LiteralPath $LogPath -Value ($Event | ConvertTo-Json -Compress -Depth 4) -Encoding UTF8
    } catch {
        # La journalisation est best-effort et ne doit pas inverser le résultat de sécurité.
    }
}
