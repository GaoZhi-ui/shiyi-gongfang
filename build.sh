#!/usr/bin/env bash
#
# 拾遗工坊 — Linux/macOS 构建脚本
# 用法: chmod +x build.sh && ./build.sh [--clean] [--debug]
#

set -euo pipefail

APP_NAME="拾遗工坊"
ENTRY="main.py"
DIST_DIR="dist"

# ── 颜色 ──
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[*]${NC} $1"; }
ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; }

# ── 参数 ──
CLEAN=false
DEBUG=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) CLEAN=true; shift ;;
        --debug) DEBUG=true; shift ;;
        *) warn "未知参数: $1"; shift ;;
    esac
done

# ── 检测 Python ──
info "检测 Python 环境..."

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" --version 2>&1 | grep -oP '\d+\.\d+')
        MAJOR="${VER%%.*}"
        if [[ "$MAJOR" -ge 3 ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "未找到 Python 3 (请安装 Python 3.10+)"
    exit 1
fi

"$PYTHON" --version
ok "Python 可用"

# ── 清理 ──
if $CLEAN; then
    info "清理旧构建..."
    rm -rf "$DIST_DIR" build *.spec
    ok "清理完成"
fi

# ── 安装依赖 ──
if [[ ! -f "requirements.txt" ]]; then
    warn "未找到 requirements.txt，跳过依赖安装"
else
    info "检查依赖..."
    "$PYTHON" -m pip install -r requirements.txt --quiet
    ok "依赖安装完成"
fi

# ── 安装 PyInstaller ──
if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    info "安装 PyInstaller..."
    "$PYTHON" -m pip install pyinstaller --quiet
    ok "PyInstaller 安装完成"
fi

# ── 构建 ──
info "开始构建 ${APP_NAME}..."

CMD=("$PYTHON" -m PyInstaller --onefile --name "$APP_NAME" --distpath "$DIST_DIR")

if $DEBUG; then
    CMD+=(--debug all)
fi

CMD+=(--console "$ENTRY")

info "执行: ${CMD[*]}"
"${CMD[@]}"
ok "构建成功"

# ── 输出 ──
if [[ -f "$DIST_DIR/$APP_NAME" ]]; then
    SIZE=$(du -h "$DIST_DIR/$APP_NAME" | cut -f1)
    ok "产物: $DIST_DIR/$APP_NAME ($SIZE)"
elif [[ -f "$DIST_DIR/${APP_NAME}.exe" ]]; then
    SIZE=$(du -h "$DIST_DIR/${APP_NAME}.exe" | cut -f1)
    ok "产物: $DIST_DIR/${APP_NAME}.exe ($SIZE)"
else
    warn "产物未找到，检查 $DIST_DIR/ 目录"
    ls -la "$DIST_DIR/" 2>/dev/null || true
fi
