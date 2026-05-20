"""
输入消毒模块

提供文本消毒和路径安全检查，防止 XSS 和路径穿越。
所有入库前的用户输入应经过 sanitize_text 处理。
"""

import re
from pathlib import Path


# 保留的字符集合（正则互补集之外的全部移除）：
#   - 中文字符和中文标点
#   - 英文字母、数字
#   - 英文标点
#   - 空白（空格、制表符、换行）
_SAFE_PATTERN = re.compile(
    r"[^\u4e00-\u9fff"          # 中文
    r"\u3400-\u4dbf"            # 中文扩展A
    r"\uf900-\ufaff"            # 中文兼容
    r"\u3000-\u303f"            # 中文标点（CJK符号）
    r"\uff00-\uffef"            # 全角ASCII/标点
    r"a-zA-Z0-9"               # 英文 + 数字
    r" .,!?;:'\"()\[\]{}<>"    # 半角标点（不含反斜杠等危险字符）
    r"@#\$%^&*+=_~|/\\"        # 常用符号（保留部分技术写作所需）
    r"\-"                       # 连字符
    r"\s"                       # 所有空白字符
    r"]"
)

# 完整的 HTML 标签（包括自闭合和注释）
_HTML_TAG = re.compile(r"<[^>]*>", re.DOTALL)

# 事件处理属性（onclick, onload, onerror 等）
_JS_EVENT = re.compile(r"\bon\w+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]*)", re.IGNORECASE)

# javascript: / data: / vbscript: URI 模式
_DANGEROUS_URI = re.compile(r"\b(javascript|data|vbscript):", re.IGNORECASE)


def sanitize_text(text: str) -> str:
    """移除 / 转义 HTML 标签和 XSS 向量，保留写作所需的正常文本。

    处理顺序：
      1. 移除事件处理属性（onclick 等）
      2. 移除完整 HTML 标签（<tag>...</tag>）
      3. 保留剩余的纯文本内容

    Args:
        text: 原始用户输入

    Returns:
        消毒后的安全文本
    """
    if not text:
        return text

    # 第一步：移除事件处理属性
    cleaned = _JS_EVENT.sub("", text)

    # 第二步：移除完整 HTML 标签
    cleaned = _HTML_TAG.sub("", cleaned)

    # 第三步：清理残余的 URI 危险前缀
    # 不直接移除整个文本，只移除危险协议部分
    cleaned = _DANGEROUS_URI.sub("", cleaned)

    # 第四步：trim
    cleaned = cleaned.strip()

    return cleaned


def is_safe_path(path: str, base_dir: str) -> bool:
    """检查目标路径是否在基目录内，防止路径穿越。

    将相对路径解析为绝对路径后，验证其前缀是否等于基目录。

    Args:
        path: 待检查的文件或目录路径
        base_dir: 合法的基目录路径

    Returns:
        True 如果解析后的路径在 base_dir 之内
    """
    try:
        resolved = Path(path).resolve()
        base = Path(base_dir).resolve()
        return str(resolved).startswith(str(base))
    except (ValueError, OSError, RuntimeError):
        return False
