"""
文件系统抽象层 (File System Abstraction Layer)

为写作工坊提供统一、可测试、带缓存的文件访问接口。
后续可逐步替换 routers/ 中直接的 Path.glob / read_text / write_text 调用。

设计目标：
  - 透明缓存：读文件自动缓存，写文件自动失效
  - 缓存 TTL：文件列表 2s，文件内容 5s
  - 无侵入：不修改现有路由，仅在 core/ 中提供
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ─── FileInfo ────────────────────────────────────────────────────────────────


@dataclass
class FileInfo:
    """文件元信息"""
    name: str
    path: str
    size: int
    mtime: float
    word_count: int


# ─── 缓存条目 ────────────────────────────────────────────────────────────────


class _CacheEntry:
    """带时间戳的缓存条目"""

    def __init__(self, value, ttl: float = 2.0):
        self.value = value
        self._ttl = ttl
        self._ts = time.time()

    def is_fresh(self) -> bool:
        return time.time() - self._ts < self._ttl

    def touch(self):
        self._ts = time.time()


# ─── FSAL 主类 ───────────────────────────────────────────────────────────────


class FileSystemAbstractionLayer:
    """文件系统抽象层，带双缓存（列表缓存 + 内容缓存）"""

    def __init__(self):
        # 缓存键设计：
        #   "list:{base_dir}:{pattern}" → FileInfo 列表
        #   "content:{resolved_path}"   → (str, mtime)
        #   "mtime:{resolved_path}"     → float
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        # 默认 TTL（秒）
        self.list_ttl: float = 2.0
        self.content_ttl: float = 5.0

    # ── 公开方法 ──────────────────────────────────────────────────────────

    def list_files(self, base_dir: str | Path, pattern: str = "*.md") -> list[FileInfo]:
        """列出目录下匹配模式的文件，返回 FileInfo 列表（缓存 2s）"""
        base = Path(base_dir).resolve()
        cache_key = f"list:{base}:{pattern}"

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and entry.is_fresh():
                return entry.value  # type: ignore[return-value]

        # 缓存失效 / 未命中 → 扫描
        files: list[FileInfo] = []
        for p in sorted(base.glob(pattern)):
            if not p.is_file():
                continue
            stat = p.stat()
            text = p.read_text(encoding="utf-8", errors="replace")
            wc = self._count_words(text)
            files.append(FileInfo(
                name=p.name,
                path=str(p),
                size=stat.st_size,
                mtime=stat.st_mtime,
                word_count=wc,
            ))

        with self._lock:
            self._cache[cache_key] = _CacheEntry(files, ttl=self.list_ttl)

        return files

    def read_file(self, path: str | Path) -> str:
        """读取文件内容（缓存 5s，若文件 mtime 未变则复用缓存）"""
        resolved = Path(path).resolve()
        cache_key = f"content:{resolved}"

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and entry.is_fresh():
                content, cached_mtime = entry.value  # type: ignore[misc]
                # 二次校验：如果磁盘 mtime 没变，直接返回缓存
                if resolved.stat().st_mtime == cached_mtime:
                    return content

        # 重新读取
        content = resolved.read_text(encoding="utf-8", errors="replace")
        mtime = resolved.stat().st_mtime

        with self._lock:
            self._cache[cache_key] = _CacheEntry(
                (content, mtime), ttl=self.content_ttl,
            )

        return content

    def write_file(self, path: str | Path, content: str):
        """写入文件，自动使相关缓存失效"""
        resolved = Path(path).resolve()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

        mtime = resolved.stat().st_mtime

        with self._lock:
            # 使此文件的内容缓存失效（用新的值覆盖）
            content_key = f"content:{resolved}"
            self._cache[content_key] = _CacheEntry(
                (content, mtime), ttl=self.content_ttl,
            )

            # 使此文件所在目录的所有列表缓存失效
            parent = str(resolved.parent)
            stale_keys = [
                k for k in self._cache
                if k.startswith("list:") and parent in k
            ]
            for k in stale_keys:
                del self._cache[k]

    def get_mtime(self, path: str | Path) -> float:
        """获取文件修改时间（缓存 2s）"""
        resolved = Path(path).resolve()
        cache_key = f"mtime:{resolved}"

        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and entry.is_fresh():
                return entry.value  # type: ignore[return-value]

        mtime = resolved.stat().st_mtime

        with self._lock:
            self._cache[cache_key] = _CacheEntry(mtime, ttl=2.0)

        return mtime

    def watch_directory(
        self,
        path: str | Path,
        callback: Callable[[list[FileInfo]], None],
        interval: float = 5.0,
        pattern: str = "*.md",
        stop_event: threading.Event | None = None,
    ) -> threading.Thread:
        """轮询监听目录变化（每 interval 秒），变化时调用 callback。

        返回后台线程对象，外部调用 thread.join() / stop_event.set() 控制生命周期。
        """
        base = Path(path).resolve()
        stop = stop_event or threading.Event()

        def _poll():
            # 记录初始快照 {name -> mtime}
            snapshot: dict[str, float] = {}
            for p in base.glob(pattern):
                if p.is_file():
                    snapshot[p.name] = p.stat().st_mtime

            while not stop.is_set():
                stop.wait(interval)
                if stop.is_set():
                    break

                changed = False
                current: dict[str, float] = {}
                for p in base.glob(pattern):
                    if p.is_file():
                        m = p.stat().st_mtime
                        current[p.name] = m
                        if snapshot.get(p.name) != m:
                            changed = True

                # 检查是否有文件被删除
                if set(snapshot.keys()) != set(current.keys()):
                    changed = True

                if changed:
                    snapshot = current
                    # 使列表缓存失效
                    cache_key = f"list:{base}:{pattern}"
                    with self._lock:
                        self._cache.pop(cache_key, None)
                    # 重新扫描并入 callback
                    files = self.list_files(base, pattern)
                    callback(files)

        t = threading.Thread(target=_poll, daemon=True, name="fsal-watcher")
        t.start()
        return t

    def invalidate_cache(self, path: str | Path | None = None):
        """主动使缓存失效。

        path=None  → 清空全部缓存
        path=路径  → 使该文件/目录的缓存失效
        """
        with self._lock:
            if path is None:
                self._cache.clear()
                return

            resolved = str(Path(path).resolve())
            stale_keys = [
                k for k in self._cache
                if resolved in k  # content:/mtime:/list: 都可能包含此路径
            ]
            for k in stale_keys:
                del self._cache[k]

    # ── 内部方法 ──────────────────────────────────────────────────────────

    @staticmethod
    def _count_words(text: str) -> int:
        """统计中英文混合字数"""
        # 中文字符
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
        # 英文单词（连续字母 + 数字）
        words = len(re.findall(r'[a-zA-Z0-9]+', text))
        return cjk + words
