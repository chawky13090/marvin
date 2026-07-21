[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$SourceIso,

    [Parameter(Mandatory)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$Preseed,

    [Parameter(Mandatory)]
    [string]$OutputIso
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$expectedSourceHash = 'CE0EEEE7B51FDCDBED1E5116668C1FEE27E528767BDF488E5F115A67B225E5DFD0AFCA1D456AAA9408CEB6B8527521FF7B6B5D62FDBE6F8C5FAAF8DF56A96292'
$dockerImage = 'debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd'
$grub = Join-Path $PSScriptRoot 'assets\debian13-marvin-grub.cfg'
$source = (Resolve-Path -LiteralPath $SourceIso).Path
$seed = (Resolve-Path -LiteralPath $Preseed).Path
$grub = (Resolve-Path -LiteralPath $grub).Path
$output = [IO.Path]::GetFullPath($OutputIso)

if ((Get-FileHash -Algorithm SHA512 -LiteralPath $source).Hash -ne $expectedSourceHash) {
    throw 'Empreinte de l ISO Debian source invalide. Construction refusée.'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker est requis uniquement pour construire le média Debian automatisé.'
}
docker version --format '{{.Server.Version}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Le moteur Docker n est pas disponible.' }

$outputDirectory = Split-Path -Parent $output
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
if (Test-Path -LiteralPath $output) { Remove-Item -LiteralPath $output -Force }
$temporary = Join-Path $outputDirectory ('.debian-unattended-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary -Force | Out-Null
try {
    Copy-Item -LiteralPath $seed -Destination (Join-Path $temporary 'preseed.cfg')
    Copy-Item -LiteralPath $grub -Destination (Join-Path $temporary 'grub.cfg')
    $sourceDirectory = Split-Path -Parent $source
    $sourceName = Split-Path -Leaf $source
    $outputName = Split-Path -Leaf $output
    $containerCommand = @'
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends xorriso ca-certificates >/dev/null
xorriso -indev "/source/$SOURCE_NAME" -outdev "/output/$OUTPUT_NAME" \
  -map /seed/preseed.cfg /preseed.cfg \
  -map /seed/grub.cfg /boot/grub/grub.cfg \
  -boot_image any replay -commit -end >/tmp/xorriso.log 2>&1
xorriso -osirrox on -indev "/output/$OUTPUT_NAME" \
  -extract /preseed.cfg /tmp/observed-preseed.cfg \
  -extract /boot/grub/grub.cfg /tmp/observed-grub.cfg >/dev/null 2>&1
cmp /seed/preseed.cfg /tmp/observed-preseed.cfg
cmp /seed/grub.cfg /tmp/observed-grub.cfg
'@
    docker run --rm `
        -e SOURCE_NAME=$sourceName -e OUTPUT_NAME=$outputName `
        -v "${sourceDirectory}:/source:ro" -v "${temporary}:/seed:ro" `
        -v "${outputDirectory}:/output" $dockerImage sh -lc $containerCommand
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
        throw 'La construction ou la validation du média Debian automatisé a échoué.'
    }
    [ordered]@{
        profile = 'debian13'
        source_iso = $source
        output_iso = $output
        output_sha512 = (Get-FileHash -Algorithm SHA512 -LiteralPath $output).Hash
        builder_image = $dockerImage
        preseed_contains_private_secret = $false
        verified_files = @('/preseed.cfg', '/boot/grub/grub.cfg')
        created_at = (Get-Date).ToString('o')
    } | ConvertTo-Json -Depth 5
}
finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Recurse -Force }
}
