# ============================================
# 同步服务端所需全部文件到 NAS 网盘
# 用法: 右键 → 使用 PowerShell 运行
# ============================================
$ErrorActionPreference = "Stop"
$src  = "D:\采购管理\媽媽5"
$dst  = "\\iKuai\南北机车\IMAO\FuWuduan_3987"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 同步服务端文件到网盘" -ForegroundColor Cyan
Write-Host " 源: $src" -ForegroundColor Cyan
Write-Host " 目标: $dst" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 确保目标目录存在
$dirs = @("$dst", "$dst\routes", "$dst\templates", "$dst\slider")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}

# ---- 1. 核心 Python 文件 ----
Write-Host "`n[1/4] 核心文件..." -ForegroundColor Yellow
$coreFiles = @(
    "moutai_automation.py",
    "moutai_client_worker.py",
    "demo.py",
    "crypto.py",
    "requirements.txt"
)
foreach ($f in $coreFiles) {
    $from = Join-Path $src $f
    $to   = Join-Path $dst $f
    if (Test-Path $from) {
        Copy-Item $from $to -Force
        Write-Host "  ✓ $f" -ForegroundColor Green
    } else {
        Write-Host "  ✗ $f (源文件不存在!)" -ForegroundColor Red
    }
}

# ---- 2. routes 路由文件 ----
Write-Host "`n[2/4] routes/ 路由文件..." -ForegroundColor Yellow
$routeFiles = Get-ChildItem "$src\routes\*.py" | Select-Object -ExpandProperty Name
foreach ($f in $routeFiles) {
    Copy-Item "$src\routes\$f" "$dst\routes\$f" -Force
    Write-Host "  ✓ routes/$f" -ForegroundColor Green
}

# ---- 3. templates 模板 ----
Write-Host "`n[3/4] templates/ 模板文件..." -ForegroundColor Yellow
$tplFiles = Get-ChildItem "$src\templates\*" -Include "*.html","*.css" | Select-Object -ExpandProperty Name
foreach ($f in $tplFiles) {
    Copy-Item "$src\templates\$f" "$dst\templates\$f" -Force
    Write-Host "  ✓ templates/$f" -ForegroundColor Green
}

# ---- 4. slider 滑块 ----
Write-Host "`n[4/4] slider/ 滑块文件..." -ForegroundColor Yellow
$sliderFiles = Get-ChildItem "$src\slider\*" | Select-Object -ExpandProperty Name
foreach ($f in $sliderFiles) {
    Copy-Item "$src\slider\$f" "$dst\slider\$f" -Force
    Write-Host "  ✓ slider/$f" -ForegroundColor Green
}

# ---- 统计 ----
$total = (Get-ChildItem $dst -Recurse -File | Measure-Object).Count
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " 同步完成! 共 $total 个文件" -ForegroundColor Green
Write-Host " 网盘地址: http://ipla.top:6789/FuWuduan_3987/" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Read-Host "按 Enter 退出"
