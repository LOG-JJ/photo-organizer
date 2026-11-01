param(
    [string]$BuildRoot = (Join-Path $env:LOCALAPPDATA 'PhotoOrganizerBuild'),
    [string]$InnoCompiler,
    [string]$ReleaseFolder
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $ReleaseFolder) { $ReleaseFolder = Join-Path $projectRoot '배포' }
$buildPython = Join-Path $BuildRoot 'venv\Scripts\python.exe'
New-Item -ItemType Directory -Path $BuildRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $buildPython)) {
    python -m venv (Join-Path $BuildRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw '빌드용 Python 환경을 만들지 못했습니다.' }
}
& $buildPython -X utf8 -c 'import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize("P") == 8'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 64비트로 빌드용 가상 환경을 만들어 주세요.' }
& $buildPython -X utf8 -m pip install --quiet --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) { throw '빌드 패키지 설치에 실패했습니다.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '글꼴\NotoSansKR-Regular.ttf'))) {
    & $buildPython -X utf8 (Join-Path $PSScriptRoot 'prepare_fonts.py') (Join-Path $BuildRoot 'NotoSansKR-source.ttf')
    if ($LASTEXITCODE -ne 0) { throw '배포용 글꼴 준비에 실패했습니다.' }
}
if (-not $InnoCompiler) { $InnoCompiler = Join-Path $BuildRoot 'inno\ISCC.exe' }
if (-not (Test-Path -LiteralPath $InnoCompiler)) { throw 'Inno Setup 6.7 이상을 설치하고 -InnoCompiler 경로를 지정하세요.' }
Push-Location $projectRoot
try {
    $version = & $buildPython -X utf8 -c 'from photo_version import VERSION; print(VERSION)'
    $distFolder = Join-Path $BuildRoot 'dist'
    & $buildPython -X utf8 -m PyInstaller --noconfirm --distpath $distFolder --workpath (Join-Path $BuildRoot 'work') (Join-Path $PSScriptRoot 'PhotoOrganizer.spec')
    if ($LASTEXITCODE -ne 0) { throw '실행 파일 빌드에 실패했습니다.' }
    $bundle = Join-Path $distFolder 'PhotoOrganizer'
    & $InnoCompiler /Q "/DAppVersion=$version" "/DBundleDir=$bundle" "/DReleaseDir=$ReleaseFolder" (Join-Path $PSScriptRoot 'PhotoOrganizer.iss')
    if ($LASTEXITCODE -ne 0) { throw '설치 파일 빌드에 실패했습니다.' }
    Get-Item -LiteralPath (Join-Path $ReleaseFolder 'PhotoOrganizer-Setup.exe')
}
finally { Pop-Location }
