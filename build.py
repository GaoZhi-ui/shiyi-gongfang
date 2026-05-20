"""
写作助手工坊 — 跨平台 PyInstaller 构建脚本
用法: python build.py [--clean] [--debug] [--onedir]
"""

import sys
import subprocess
import argparse
from pathlib import Path

APP_NAME = "shiyi-gongfang"
ENTRY = "main.py"
GUI_ENTRY = "run_gui.py"
BASE = Path(__file__).resolve().parent
DIST_DIR = BASE / "dist"
BUILD_DIR = BASE / "build"

# 需要随 exe 打包的额外资源目录
ADD_DATA_DIRS = [
    "routers",
    "core",
    "services",
    "static",
    "templates",
    "data",
]


def detect_platform() -> str:
    system = sys.platform.lower()
    if system.startswith("win"):
        return "windows"
    elif system.startswith("linux"):
        return "linux"
    elif system.startswith("darwin"):
        return "macos"
    else:
        print(f"[!] 无法识别的平台: {system}")
        sys.exit(1)


def build(clean: bool = False, debug: bool = False, onedir: bool = False, gui: bool = False):
    platform = detect_platform()
    sep = ";" if platform == "windows" else ":"
    entry = GUI_ENTRY if gui else ENTRY
    
    print(f">>> Platform: {platform}")
    print(f">>> App: {APP_NAME}")
    print(f">>> Entry: {entry}")
    print(f">>> Mode: {'onedir' if onedir else 'onefile'}")
    if gui:
        print(">>> GUI mode: native window (no browser needed)")

    # 清理旧构建
    if clean:
        import shutil
        print(">>> Cleaning old builds...")
        for d in [DIST_DIR, BUILD_DIR]:
            if d.exists():
                shutil.rmtree(d)
                print(f"  Removed: {d}")

    # 确保 PyInstaller 已安装
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(">>> Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"]
        )

    # 构建基础命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BUILD_DIR),
        "--noconfirm",
    ]

    if onedir:
        cmd.append("--onedir")
    else:
        cmd.append("--onefile")

    # 添加额外的资源目录（使用绝对路径）
    for dirname in ADD_DATA_DIRS:
        src = BASE / dirname
        if src.exists():
            cmd.append(f"--add-data={src}{sep}{dirname}")
            print(f"  [+] Pack: {dirname}")

    # 隐式导入
    cmd.append("--hidden-import=uvicorn.logging")
    cmd.append("--hidden-import=uvicorn.loops.auto")
    cmd.append("--hidden-import=uvicorn.protocols.http.auto")
    cmd.append("--hidden-import=docx")
    cmd.append("--hidden-import=fpdf2")
    cmd.append("--hidden-import=pydantic")
    cmd.append("--hidden-import=multipart")

    # 集合路径
    cmd.append("--collect-submodules=routers")

    if debug:
        cmd.append("--debug")
        cmd.append("all")

    if gui:
        cmd.append("--windowed")  # 无控制台窗口
        cmd.append("--hidden-import=webview")
        cmd.append("--hidden-import=bottle")
        cmd.append("--hidden-import=proxy_tools")
    else:
        cmd.append("--console")
    if gui:
        # GUI 入口
        cmd.append(str(BASE / GUI_ENTRY))
    else:
        cmd.append(str(BASE / ENTRY))

    print(">>> Building...")
    subprocess.check_call(cmd)

    # 输出信息
    if platform == "windows":
        if onedir:
            output = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
        else:
            output = DIST_DIR / f"{APP_NAME}.exe"
    else:
        if onedir:
            output = DIST_DIR / APP_NAME / APP_NAME
        else:
            output = DIST_DIR / APP_NAME

    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"\n[OK] Build complete: {output.name} ({size_mb:.1f} MB)")
        return str(output)
    else:
        print(f"\n[!] 构建产物未找到，检查 {DIST_DIR}/ 目录")
        if DIST_DIR.exists():
            for f in sorted(DIST_DIR.rglob("*")):
                print(f"  {f.relative_to(DIST_DIR)}")
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="写作助手工坊 PyInstaller 构建脚本")
    parser.add_argument("--clean", action="store_true", help="构建前清理旧产物")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--onedir", action="store_true", help="使用目录模式打包（默认单文件）")
    parser.add_argument("--gui", action="store_true", help="构建GUI版本（原生窗口，无需浏览器）")
    args = parser.parse_args()
    build(clean=args.clean, debug=args.debug, onedir=args.onedir, gui=args.gui)
