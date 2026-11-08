param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not $SkipTests) {
    python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw "测试失败" }
}

Write-Host "==> 构建 Python 后端"
python -m PyInstaller --noconfirm --clean --distpath backend-dist --workpath build-backend AutoBellBackend.spec
if ($LASTEXITCODE -ne 0) { throw "后端构建失败" }

Write-Host "==> 构建 Electron 目录"
Push-Location desktop
try {
    if (-not (Test-Path "node_modules\electron\dist\electron.exe")) {
        throw "缺少 Electron 运行时，请先在 desktop 目录执行 npm install"
    }
    $env:NODE_TLS_REJECT_UNAUTHORIZED = "0"
    $env:CSC_IDENTITY_AUTO_DISCOVERY = "false"
    & ".\node_modules\.bin\electron-builder.cmd" --dir --x64
    if ($LASTEXITCODE -ne 0) { throw "Electron 打包失败" }
} finally {
    Pop-Location
}

$appDir = Join-Path $root "dist-electron\win-unpacked"
if (Test-Path (Join-Path $appDir "自动铃声系统.exe")) {
    Move-Item (Join-Path $appDir "自动铃声系统.exe") (Join-Path $appDir "AutoBellDesktop.exe") -Force
}

Write-Host "==> 编译启动器"
$csc = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { throw "找不到 csc.exe" }
& $csc /nologo /target:winexe `
    /win32icon:"$root\desktop\assets\app.ico" `
    /r:System.Windows.Forms.dll `
    /out:"$appDir\自动铃声系统.exe" `
    "$root\desktop\launcher.cs"
if ($LASTEXITCODE -ne 0) { throw "启动器编译失败" }

Write-Host "==> 生成安装程序"
$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { throw "找不到 Inno Setup 6" }
& $iscc "$root\installer\自动铃声系统-Web.iss"
if ($LASTEXITCODE -ne 0) { throw "安装程序构建失败" }

Write-Host "==> 生成单文件安装引导器"
$inner = Join-Path $root "dist-electron\自动铃声系统-1.0.0-安装程序.exe"
$bootstrapper = Join-Path $root "dist-electron\AutoBellSystem-Setup-1.0.0.exe"
& $csc /nologo /target:winexe `
    /win32icon:"$root\desktop\assets\app.ico" `
    /r:System.Windows.Forms.dll `
    /resource:"$inner",AutoBellSetup.exe `
    /out:"$bootstrapper" `
    "$root\desktop\setup-bootstrapper.cs"
if ($LASTEXITCODE -ne 0) { throw "安装引导器编译失败" }

Get-ChildItem (Join-Path $root "dist-electron") -Filter "*.exe" |
    Select-Object Name, Length, LastWriteTime
