"""
Token化导出引擎

将原始Markdown文本解析为Token流，再组装为FormattedDocument中间表示，
供下游Consumer消费。

架构：原始文本 → tokenize() → ChapterToken[] → FormattedDocument → DocumentBuilder → Consumer
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


# ─── Token 定义 ───

TokenType = Literal["heading", "paragraph", "list", "diary", "blank"]


@dataclass
class ChapterToken:
    """单个章节内容Token"""

    type: TokenType
    level: int = 0  # 标题层级(1-3)或列表缩进层级
    content: list[str] = field(default_factory=list)

    def __post_init__(self):
        # 规范化类型值
        if self.type not in ("heading", "paragraph", "list", "diary", "blank"):
            raise ValueError(f"未知的Token类型: {self.type}")

    @property
    def text(self) -> str:
        """合并所有content行为一个字符串，方便Consumer直接用"""
        return "\n".join(self.content)

    @property
    def is_heading(self) -> bool:
        return self.type == "heading"

    @property
    def is_blank(self) -> bool:
        return self.type == "blank"

    @property
    def is_diary(self) -> bool:
        return self.type == "diary"


# ─── Token化解析器 ───

def tokenize(text: str) -> list[ChapterToken]:
    """
    将Markdown文本解析为Token流。

    规则：
      - # ## ### → heading token，level 对应 1/2/3
      - 以 - 或 * 开头的行 → list token
      - 与正文之间由 --- 分隔的末尾段落 → diary token
      - 纯空白行 → blank token
      - 其余 → paragraph token（跨行合并为一个paragraph）
    """
    tokens: list[ChapterToken] = []

    # 阶段1：检测 --- 分隔符，分离正文与日记
    body_text = text
    diary_text = ""
    sep_index = _find_diary_separator(text)
    if sep_index is not None:
        body_text = text[:sep_index]
        diary_text = text[sep_index + 3:]  # skip "---"

    # 阶段2：解析正文
    body_tokens = _tokenize_body(body_text)
    tokens.extend(body_tokens)

    # 阶段3：解析日记部分
    if diary_text.strip():
        diary_lines = diary_text.split("\n")
        # 去掉开头可能的空行
        while diary_lines and not diary_lines[0].strip():
            diary_lines.pop(0)
        # 去掉结尾的空行
        while diary_lines and not diary_lines[-1].strip():
            diary_lines.pop()
        if diary_lines:
            tokens.append(ChapterToken(type="diary", level=0, content=diary_lines))

    return tokens


def _find_diary_separator(text: str) -> int | None:
    """
    查找日记分隔符 --- 的位置。
    规则：--- 必须独占一行，且前后都有非空内容。
    只匹配第一个出现的分隔符。
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "---" and line.strip() == line.rstrip():
            # 确保前后都有内容（前后至少有一段非空文本）
            before = "\n".join(lines[:i]).strip()
            after = "\n".join(lines[i + 1 :]).strip()
            if before and after:
                # 返回这个 --- 在原始文本中的偏移位置
                offset = 0
                for j in range(i):
                    offset += len(lines[j]) + 1  # +1 for newline
                return offset
    return None


def _tokenize_body(text: str) -> list[ChapterToken]:
    """将正文部分解析为Token流，跨行合并普通段落"""
    tokens: list[ChapterToken] = []
    lines = text.split("\n")
    pending_paragraph: list[str] | None = None

    def _flush_paragraph():
        nonlocal pending_paragraph
        if pending_paragraph is not None:
            joined = [l for l in pending_paragraph if l.strip()]
            # 如果全部为空行，产出 blank
            if not joined:
                tokens.append(ChapterToken(type="blank", content=pending_paragraph))
            else:
                tokens.append(ChapterToken(type="paragraph", content=pending_paragraph))
            pending_paragraph = None

    for line in lines:
        stripped = line.strip()

        # 空行：刷新当前段落，加 blank
        if not stripped:
            _flush_paragraph()
            tokens.append(ChapterToken(type="blank", content=[line]))
            continue

        # 标题
        if stripped.startswith("### "):
            _flush_paragraph()
            tokens.append(
                ChapterToken(type="heading", level=3, content=[stripped[4:]])
            )
            continue
        if stripped.startswith("## "):
            _flush_paragraph()
            tokens.append(
                ChapterToken(type="heading", level=2, content=[stripped[3:]])
            )
            continue
        if stripped.startswith("# "):
            _flush_paragraph()
            tokens.append(
                ChapterToken(type="heading", level=1, content=[stripped[2:]])
            )
            continue

        # 列表项：- 或 * 开头
        if stripped.startswith("- ") or stripped.startswith("* "):
            _flush_paragraph()
            tokens.append(
                ChapterToken(type="list", level=0, content=[stripped[2:]])
            )
            continue

        # 普通行：合并到待处理的段落中
        if pending_paragraph is None:
            pending_paragraph = []
        pending_paragraph.append(line)

    _flush_paragraph()
    return tokens


# ─── 文档结构 ───

@dataclass
class FormattedDocument:
    """导出文档的中间表示"""

    title: str
    chapters: list[tuple[str, list[ChapterToken]]] = field(default_factory=list)

    @property
    def chapter_count(self) -> int:
        return len(self.chapters)

    def get_chapter(self, filename: str) -> list[ChapterToken] | None:
        for fn, tokens in self.chapters:
            if fn == filename:
                return tokens
        return None

    def all_tokens(self) -> list[ChapterToken]:
        """返回所有章节目录的扁平Token流（含分隔标记）"""
        result: list[ChapterToken] = []
        for filename, tokens in self.chapters:
            result.append(
                ChapterToken(
                    type="heading",
                    level=1,
                    content=[filename.replace(".md", "")],
                )
            )
            result.extend(tokens)
        return result


# ─── 文档构建器 ───

class DocumentBuilder:
    """将FormattedDocument转换为消费端可用的中间表示。

    当前阶段为验证/整理层，可扩展添加：
      - Token去重与合并
      - 元数据注入
      - 样式标记
    """

    def build(self, doc: FormattedDocument) -> FormattedDocument:
        """验证并返回FormattedDocument。
        子类可重写此方法以添加中间处理步骤。"""
        if not doc.title:
            doc.title = "未命名文档"
        for filename, tokens in doc.chapters:
            if not tokens:
                continue
            # 确保第一行不是blank
            while tokens and tokens[0].type == "blank":
                tokens.pop(0)
            # 确保最后一行不是blank
            while tokens and tokens[-1].type == "blank":
                tokens.pop()
        return doc


# ─── 便捷函数 ───

def build_document(
    title: str,
    chapters_content: list[tuple[str, str]],
) -> FormattedDocument:
    """从原始章节内容直接构建FormattedDocument。

    Args:
        title: 文档标题
        chapters_content: [(filename, markdown_text), ...]

    Returns:
        组装好的FormattedDocument
    """
    chapters: list[tuple[str, list[ChapterToken]]] = []
    for filename, text in chapters_content:
        tokens = tokenize(text)
        chapters.append((filename, tokens))
    doc = FormattedDocument(title=title, chapters=chapters)
    builder = DocumentBuilder()
    return builder.build(doc)
