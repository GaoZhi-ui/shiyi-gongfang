@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ╔══════════════════════════════════════╗
echo ║     泰拉拾遗录 · 写作工坊启动工具     ║
echo ╚══════════════════════════════════════╝
echo.

:: ── 检查 Python ──
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 确认 Python 版本 ≥ 3.10
python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if %ERRORLEVEL% neq 0 (
    echo [错误] Python 版本过低，需要 3.10 或更高版本
    python --version
    echo.
    pause
    exit /b 1
)

echo ✓ Python 版本： OK
python --version
echo.

:: ── 虚拟环境 ──
if not exist venv\Scripts\activate (
    echo [安装] 首次运行，正在创建虚拟环境...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo ✓ 虚拟环境已创建
) else (
    echo ✓ 虚拟环境已存在
)
echo.

:: ── 激活虚拟环境 ──
call venv\Scripts\activate

:: ── 安装依赖 ──
echo [检查] 正在检查依赖...
pip show fastapi >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [安装] 正在安装依赖...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
    echo ✓ 依赖安装完成
) else (
    echo ✓ 依赖已安装
)
echo.

:: ── 创建 .env（如果完全不存在） ──
if not exist .env (
    if exist .env.example (
        echo [提示] 未检测到 .env 配置文件，已从 .env.example 创建模板
        echo       请编辑 .env 填入 API Key 以启用 AI 聊天功能
        copy .env.example .env >nul
        echo.
    )
)

:: ── 启动 ──
echo ═══════════════════════════════════════
echo  正在启动服务...
echo  访问地址：http://localhost:8000
echo  按 Ctrl+C 停止服务
echo ═══════════════════════════════════════
echo.

:: 自动打开浏览器
start http://localhost:8000

uvicorn main:app --reload --host 127.0.0.1 --port 8000

pause
