"""
拾遗工坊 — 跨平台 PyInstaller 构建脚本
用法: python build.py [--clean] [--debug]
"""

import sys
import subprocess
import argparse
from pathlib import Path

APP_NAME = "拾遗工坊"
ENTRY = "main.py"
DIST_DIR = Path("dist")
BUILD_DIR = Path("build")


def detect_platform() -> str:
    """自动识别当前平台"""
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


def build(clean: bool = False, debug: bool = False):
    platform = detect_platform()
    print(f"[*] 平台: {platform}")
    print(f"[*] 应用: {APP_NAME}")
    print(f"[*] 入口: {ENTRY}")

    # 清理旧构建
    if clean:
        print("[*] 清理旧构建产物...")
        for d in [DIST_DIR, BUILD_DIR]:
            if d.exists():
                subprocess.run(["rm", "-rf", str(d)], shell=(platform == "windows"))

    # 检查 PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[*] PyInstaller 未安装，正在安装...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"]
        )

    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", APP_NAME,
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(BUILD_DIR),
    ]

    if debug:
        cmd.append("--debug")
        cmd.append("all")

    if platform == "windows":
        cmd.append("--console")
    else:
        cmd.append("--console")

    cmd.append(ENTRY)

    print(f"[*] 执行: {' '.join(cmd)}")
    subprocess.check_call(cmd)

    # 输出信息
    if platform == "windows":
        output = DIST_DIR / f"{APP_NAME}.exe"
    else:
        output = DIST_DIR / APP_NAME

    if output.exists():
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"[✓] 构建完成: {output} ({size_mb:.1f} MB)")
    else:
        print(f"[!] 构建产物未找到，检查 {DIST_DIR}/ 目录")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="拾遗工坊 PyInstaller 构建脚本")
    parser.add_argument("--clean", action="store_true", help="构建前清理旧产物")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    args = parser.parse_args()
    build(clean=args.clean, debug=args.debug)
