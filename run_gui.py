"""
写作助手工坊 — GUI 启动器
用 pywebview 在原生窗口中内嵌 Web 界面，无需手动打开浏览器。

用法: python run_gui.py
"""

import sys
import threading
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format="[%(name)s] %(levelname)s: %(message)s")
log = logging.getLogger("gui")

# 启动服务器
def start_server():
    import uvicorn
    from main import app
    log.info("启动后端服务...")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


def main():
    # 在后台线程中启动服务器
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # 等待服务器就绪
    import time
    import urllib.request
    for i in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health")
            log.info("后端服务已就绪")
            break
        except Exception:
            time.sleep(0.5)
    else:
        log.error("后端服务启动失败")
        sys.exit(1)

    # 打开 GUI 窗口
    import webview
    log.info("打开 GUI 窗口...")
    window = webview.create_window(
        title="写作助手工坊",
        url="http://127.0.0.1:8000",
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
        easy_drag=False,
    )
    webview.start(gui="cef" if sys.platform == "win32" else None)

    log.info("窗口已关闭")


if __name__ == "__main__":
    main()
