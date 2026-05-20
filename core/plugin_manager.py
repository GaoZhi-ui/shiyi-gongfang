"""
最小可行插件框架 (Minimal Viable Plugin Framework)

为写作工坊提供插件扩展能力。插件可以注册钩子，在特定事件点被调用。
预定义钩子点：
  - before_save:      保存前对内容做预处理
  - after_save:       保存后执行副作用（如备份、通知）
  - before_export:    导出前修改内容
  - after_chapter_load: 章节加载后做后处理

用法示例：
  ```python
  from core.plugin_manager import Plugin, plugin_manager

  class MyPlugin(Plugin):
      name = "my_plugin"
      version = "1.0.0"
      description = "我的插件"

      def on_load(self, app):
          # 注册钩子
          self.register_hook("before_save", self.my_hook)

      def my_hook(self, content: str, **ctx) -> str:
          return content.replace("foo", "bar")

  plugin_manager.register(MyPlugin())
  ```
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import os
import sys
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("writing-app.plugins")


# ─── 预定义钩子点 ────────────────────────────────────────────────────────────

HOOK_BEFORE_SAVE = "before_save"          # (content: str, **ctx) -> str
HOOK_AFTER_SAVE = "after_save"            # (filename: str, **ctx) -> None
HOOK_BEFORE_EXPORT = "before_export"      # (content: str, format: str, **ctx) -> str
HOOK_AFTER_CHAPTER_LOAD = "after_chapter_load"  # (filename: str, content: str, **ctx) -> None

ALL_HOOKS = frozenset({
    HOOK_BEFORE_SAVE,
    HOOK_AFTER_SAVE,
    HOOK_BEFORE_EXPORT,
    HOOK_AFTER_CHAPTER_LOAD,
})


# ─── 插件抽象基类 ────────────────────────────────────────────────────────────


class Plugin(ABC):
    """插件抽象基类。

    子类必须定义：
      - name: str         插件唯一标识名
      - version: str      语义版本号
      - description: str  简要描述

    可选实现：
      - on_load(app)      加载时回调，通常在此注册钩子
      - on_unload()       卸载时回调，清理资源
    """

    name: str = ""
    version: str = "0.0.0"
    description: str = ""

    def __init__(self):
        if not self.name:
            raise ValueError("Plugin must define a non-empty 'name'")
        self._hooks: dict[str, list[Callable]] = {h: [] for h in ALL_HOOKS}
        self._loaded = False

    # ── 子类可重写 ──────────────────────────────────────────────────────

    def on_load(self, app: Any) -> None:
        """加载时回调。app 为 FastAPI application 实例。"""
        pass

    def on_unload(self) -> None:
        """卸载时回调。清理注册的钩子、关闭连接等。"""
        pass

    # ── 钩子管理 ─────────────────────────────────────────────────────────

    def register_hook(self, hook_name: str, fn: Callable) -> None:
        """注册一个钩子实现。"""
        if hook_name not in ALL_HOOKS:
            logger.warning(f"[{self.name}] 未知钩子名: {hook_name}，跳过")
            return
        self._hooks.setdefault(hook_name, []).append(fn)
        logger.info(f"[{self.name}] 注册钩子: {hook_name}")

    def unregister_hook(self, hook_name: str, fn: Optional[Callable] = None) -> None:
        """注销钩子。fn=None 则注销该钩子的所有实现。"""
        if hook_name not in ALL_HOOKS:
            return
        if fn is None:
            self._hooks[hook_name] = []
        else:
            self._hooks[hook_name] = [f for f in self._hooks[hook_name] if f is not fn]

    def get_hooks(self, hook_name: str) -> list[Callable]:
        """获取某钩子的所有注册函数。"""
        return list(self._hooks.get(hook_name, []))

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _do_load(self, app: Any) -> None:
        if self._loaded:
            return
        try:
            self.on_load(app)
            self._loaded = True
            logger.info(f"[{self.name}] v{self.version} 加载成功")
        except Exception as e:
            logger.error(f"[{self.name}] on_load 异常: {e}\n{traceback.format_exc()}")

    def _do_unload(self) -> None:
        if not self._loaded:
            return
        try:
            self.on_unload()
        except Exception as e:
            logger.error(f"[{self.name}] on_unload 异常: {e}\n{traceback.format_exc()}")
        finally:
            self._hooks = {h: [] for h in ALL_HOOKS}
            self._loaded = False
            logger.info(f"[{self.name}] 已卸载")


# ─── 插件管理器 ──────────────────────────────────────────────────────────────


class PluginManager:
    """管理插件的注册、加载、钩子分发。"""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}
        # 全局钩子注册表：hook_name -> [(plugin_name, fn)]
        self._global_hooks: dict[str, list[tuple[str, Callable]]] = {
            h: [] for h in ALL_HOOKS
        }

    # ── 插件管理 ─────────────────────────────────────────────────────────

    def register(self, plugin: Plugin) -> None:
        """注册一个插件实例（覆盖同名插件）。"""
        if plugin.name in self._plugins:
            logger.warning(f"插件 '{plugin.name}' 已存在，将被覆盖")
            self._plugins[plugin.name]._do_unload()
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> None:
        """注销一个插件。"""
        plugin = self._plugins.pop(name, None)
        if plugin:
            plugin._do_unload()
            # 从全局钩子表中移除
            for hook_name in ALL_HOOKS:
                self._global_hooks[hook_name] = [
                    (pn, fn) for pn, fn in self._global_hooks[hook_name]
                    if pn != name
                ]

    def load_plugin(self, path: str | Path) -> Optional[str]:
        """从文件动态加载插件。

        搜索文件中所有 Plugin 子类，实例化并注册。
        返回插件名注册成功，返回 None 表示失败。
        """
        path = Path(path).resolve()
        if not path.exists():
            logger.error(f"插件文件不存在: {path}")
            return None

        try:
            # 动态导入
            module_name = f"_plugin_{path.stem}_{id(path)}"
            spec = importlib.util.spec_from_file_location(module_name, str(path))
            if spec is None or spec.loader is None:
                logger.error(f"无法加载模块: {path}")
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error(f"加载插件文件失败 [{path.name}]: {e}\n{traceback.format_exc()}")
            return None

        # 搜索 Plugin 子类
        loaded_names: list[str] = []
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, Plugin) and cls is not Plugin and not inspect.isabstract(cls):
                try:
                    instance = cls()
                    self.register(instance)
                    loaded_names.append(instance.name)
                except Exception as e:
                    logger.error(f"实例化插件类失败 [{cls.__name__}]: {e}")

        if loaded_names:
            logger.info(f"从 {path.name} 加载插件: {', '.join(loaded_names)}")
            return loaded_names[0] if len(loaded_names) == 1 else ", ".join(loaded_names)
        return None

    def list_plugins(self) -> list[dict]:
        """列出已注册插件的元信息。"""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "loaded": p._loaded,
            }
            for p in self._plugins.values()
        ]

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """按名称获取插件实例。"""
        return self._plugins.get(name)

    def get_hook(self, hook_name: str) -> list[tuple[str, Callable]]:
        """获取指定钩子的所有已注册实现 (plugin_name, fn)。"""
        return list(self._global_hooks.get(hook_name, []))

    # ── 生命周期 ─────────────────────────────────────────────────────────

    def load_all(self, app: Any, plugins_dir: str | Path = "plugins") -> int:
        """加载 plugins_dir 目录下所有 .py 插件，并调用 on_load。

        返回成功加载的插件数量。
        """
        plugins_path = Path(plugins_dir).resolve()
        if not plugins_path.is_dir():
            logger.warning(f"插件目录不存在: {plugins_path}")
            return 0

        count = 0
        for pyfile in sorted(plugins_path.glob("*.py")):
            # 跳过 __init__.py
            if pyfile.name == "__init__.py":
                continue
            result = self.load_plugin(pyfile)
            if result:
                count += 1

        # 调用所有插件的 on_load
        for plugin in self._plugins.values():
            plugin._do_load(app)

        # 重建全局钩子注册表
        self._rebuild_global_hooks()

        logger.info(f"插件加载完毕: {count} 个成功, 共 {len(self._plugins)} 个注册")
        return count

    def unload_all(self) -> None:
        """卸载所有插件。"""
        for name in list(self._plugins.keys()):
            self.unregister(name)
        self._global_hooks = {h: [] for h in ALL_HOOKS}
        logger.info("所有插件已卸载")

    # ── 钩子分发 ─────────────────────────────────────────────────────────

    def dispatch_before_save(self, content: str, **ctx) -> str:
        """分发 before_save 钩子：content -> 链式处理 -> str"""
        for plugin_name, fn in self._global_hooks[HOOK_BEFORE_SAVE]:
            try:
                result = fn(content, **ctx)
                if isinstance(result, str):
                    content = result
            except Exception as e:
                logger.error(f"[{plugin_name}] before_save 异常: {e}")
        return content

    def dispatch_after_save(self, filename: str, **ctx) -> None:
        """分发 after_save 钩子"""
        for plugin_name, fn in self._global_hooks[HOOK_AFTER_SAVE]:
            try:
                fn(filename, **ctx)
            except Exception as e:
                logger.error(f"[{plugin_name}] after_save 异常: {e}")

    def dispatch_before_export(self, content: str, format: str, **ctx) -> str:
        """分发 before_export 钩子：content -> 链式处理 -> str"""
        for plugin_name, fn in self._global_hooks[HOOK_BEFORE_EXPORT]:
            try:
                result = fn(content, format=format, **ctx)
                if isinstance(result, str):
                    content = result
            except Exception as e:
                logger.error(f"[{plugin_name}] before_export 异常: {e}")
        return content

    def dispatch_after_chapter_load(self, filename: str, content: str, **ctx) -> None:
        """分发 after_chapter_load 钩子"""
        for plugin_name, fn in self._global_hooks[HOOK_AFTER_CHAPTER_LOAD]:
            try:
                fn(filename, content, **ctx)
            except Exception as e:
                logger.error(f"[{plugin_name}] after_chapter_load 异常: {e}")

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _rebuild_global_hooks(self) -> None:
        """从所有已加载插件的 _hooks 重建全局注册表。"""
        self._global_hooks = {h: [] for h in ALL_HOOKS}
        for plugin_name, plugin in self._plugins.items():
            if not plugin._loaded:
                continue
            for hook_name in ALL_HOOKS:
                for fn in plugin.get_hooks(hook_name):
                    self._global_hooks[hook_name].append((plugin_name, fn))


# ─── 全局单例 ────────────────────────────────────────────────────────────────

plugin_manager = PluginManager()
