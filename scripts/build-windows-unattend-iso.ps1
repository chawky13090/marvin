[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$AnswerFile,

    [Parameter(Mandatory)]
    [string]$OutputIso
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$builderTag = 'marvin/vm-media-builder:debian13-xorriso1.5.6'
$answer = (Resolve-Path -LiteralPath $AnswerFile).Path
$output = [IO.Path]::GetFullPath($OutputIso)
$outputDirectory = Split-Path -Parent $output
$answerDirectory = Split-Path -Parent $answer
$answerName = Split-Path -Leaf $answer
$outputName = Split-Path -Leaf $output
$dockerfileDirectory = Join-Path $PSScriptRoot '..\docker\vm-media-builder'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker est requis pour construire le média Autounattend.' }
docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Le moteur Docker n est pas disponible.' }
$imagePresent = @(
    docker image ls --format '{{.Repository}}:{{.Tag}}' |
        Where-Object { $_ -eq $builderTag }
).Count -gt 0
if (-not $imagePresent) {
    docker build --pull --tag $builderTag $dockerfileDirectory
    if ($LASTEXITCODE -ne 0) { throw 'La construction du générateur ISO isolé a échoué.' }
}
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if (Test-Path -LiteralPath $output) {
    & icacls.exe $output /grant:r "${env:USERNAME}:F" | Out-Null
    Remove-Item -LiteralPath $output -Force
}

docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges `
    --tmpfs /tmp:rw,noexec,nosuid,size=32m `
    -v "${answerDirectory}:/seed:ro" -v "${outputDirectory}:/output" `
    $builderTag -as mkisofs -iso-level 3 -J -joliet-long -V MARVIN_UNATTEND `
    -o "/output/$outputName" "/seed/$answerName"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw 'La construction du média Autounattend a échoué.'
}
& icacls.exe $output /grant:r "${env:USERNAME}:F" '*S-1-5-18:F' '*S-1-5-32-544:F' | Out-Null
$validationDirectory = Join-Path $outputDirectory ('.validate-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $validationDirectory -Force | Out-Null
try {
    docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges `
        --tmpfs /tmp:rw,noexec,nosuid,size=32m `
        -v "${outputDirectory}:/input:ro" -v "${validationDirectory}:/output" `
        $builderTag -osirrox on -indev "/input/$outputName" `
        -extract "/$answerName" "/output/$answerName"
    if ($LASTEXITCODE -ne 0) { throw 'Lecture de contrôle du média Autounattend impossible.' }
    $originalHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $answer).Hash
    $observedHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $validationDirectory $answerName)).Hash
    if ($originalHash -ne $observedHash) { throw 'Le fichier Autounattend relu diffère de la source.' }
    [ordered]@{
        output_iso = $output
        output_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $output).Hash
        answer_sha256 = $originalHash
        builder_image = $builderTag
        builder_network_during_secret_processing = $false
        contains_transient_secret = $true
        must_destroy_after_installation = $true
        created_at = (Get-Date).ToString('o')
    } | ConvertTo-Json -Depth 5
}
finally {
    if (Test-Path -LiteralPath $validationDirectory) { Remove-Item -LiteralPath $validationDirectory -Recurse -Force }
}
