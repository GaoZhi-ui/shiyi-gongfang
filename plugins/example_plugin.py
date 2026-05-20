"""
示例插件 — 字数统计自动追加

功能：
  - after_save: 保存后自动在章节文件末尾追加字数统计行
  - before_export: 导出时清理额外追加的统计行

演示了 Plugin 基类的用法和两个钩子点的注册。
"""

from __future__ import annotations

import re
from core.plugin_manager import Plugin


class WordCountAppenderPlugin(Plugin):
    name = "wordcount_appender"
    version = "1.0.0"
    description = "保存后自动在未尾追加字数统计，导出时自动清理"

    def on_load(self, app):
        self.register_hook("after_save", self.append_wordcount)

    def append_wordcount(self, filename: str, **ctx):
        """根据上下文中的 content 计算字数并追加。"""
        content = ctx.get("content", "")
        if not content:
            return

        # 计算中英文混合字数
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', content))
        words = len(re.findall(r'[a-zA-Z0-9]+', content))
        total = cjk + words

        # 追加统计行到文件
        filepath = ctx.get("filepath", "")
        if filepath:
            from pathlib import Path
            p = Path(filepath)
            existing = p.read_text(encoding="utf-8")
            # 避免重复追加
            if "<!-- wordcount:" in existing:
                existing = re.sub(
                    r'<!-- wordcount:.*?-->',
                    f'<!-- wordcount: {cjk}字 + {words}英文 = {total} -->',
                    existing,
                )
            else:
                existing += f'\n\n<!-- wordcount: {cjk}字 + {words}英文 = {total} -->\n'
            p.write_text(existing, encoding="utf-8")


class DebugLogPlugin(Plugin):
    """调试用示例插件，在控制台打印钩子调用。"""
    name = "debug_logger"
    version = "0.1.0"
    description = "调试日志插件，打印所有钩子调用"

    def on_load(self, app):
        self.register_hook("before_save", self.log_before_save)
        self.register_hook("after_save", self.log_after_save)

    def log_before_save(self, content: str, **ctx) -> str:
        print(f"[DebugPlugin] before_save: {len(content)} chars")
        return content  # 不做修改

    def log_after_save(self, filename: str, **ctx):
        print(f"[DebugPlugin] after_save: {filename}")
