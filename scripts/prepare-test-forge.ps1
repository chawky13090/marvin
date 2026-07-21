Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$images = @(
    'koalaman/shellcheck@sha256:61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d',
    'bats/bats@sha256:6e4b9369468b7f3fd8f402ac6cc8ea7b2e4903eae28d08785f31a0245eb51a44',
    'python@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b',
    'node@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3',
    'debian@sha256:020c0d20b9880058cbe785a9db107156c3c75c2ac944a6aa7ab59f2add76a7bd'
)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI est introuvable. Installez et démarrez Docker Desktop.'
}

$serverVersion = & docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $serverVersion) {
    throw 'Docker Engine ne répond pas. Démarrez Docker Desktop puis relancez ce script.'
}

Write-Output "Docker Engine $serverVersion disponible."
foreach ($image in $images) {
    & docker image inspect $image *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Output "[OK] $image"
        continue
    }
    Write-Output "[PULL] $image"
    & docker pull $image
    if ($LASTEXITCODE -ne 0) {
        throw "Téléchargement impossible : $image"
    }
}

$requiredModules = @(
    @{ Name = 'PSScriptAnalyzer'; Version = '1.25.0' },
    @{ Name = 'Pester'; Version = '5.8.0' }
)
$repository = Get-PSRepository -Name PSGallery -ErrorAction Stop
$previousPolicy = $repository.InstallationPolicy
try {
    if ($previousPolicy -ne 'Trusted') {
        Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    }
    foreach ($module in $requiredModules) {
        $installed = Get-Module -ListAvailable -Name $module.Name |
            Where-Object { $_.Version -eq [version]$module.Version } |
            Select-Object -First 1
        if ($installed) {
            Write-Output "[OK] $($module.Name) $($module.Version)"
            continue
        }
        Write-Output "[INSTALL] $($module.Name) $($module.Version)"
        Install-Module -Name $module.Name -RequiredVersion $module.Version `
            -Scope CurrentUser -Force -AllowClobber -SkipPublisherCheck
    }
}
finally {
    if ($previousPolicy -ne 'Trusted') {
        Set-PSRepository -Name PSGallery -InstallationPolicy $previousPolicy
    }
}

Write-Output 'Test Forge prêt : images épinglées et analyseurs PowerShell disponibles.'
