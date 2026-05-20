"""
Token化导出消费者

将 FormattedDocument（Token流中间表示）渲染为具体输出格式。
每个 Consumer 继承 BaseConsumer 并实现 consume() 方法。
"""

from __future__ import annotations
import re
import zipfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from .export_engine import FormattedDocument, ChapterToken


def _safe_filename(title: str, ext: str) -> str:
    """生成安全文件名"""
    safe = re.sub(r'[<>:"/\\|?*]', "_", title)
    safe = safe.strip().replace(" ", "_")
    if not safe:
        safe = "export"
    return f"{safe}{ext}"


# ─── 抽象基类 ───


class BaseConsumer(ABC):
    """导出消费者抽象基类。

    子类必须实现 consume(document) -> Any。
    """

    def __init__(self, export_dir: str | Path):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def consume(self, document: FormattedDocument) -> Any:
        """消费 FormattedDocument，生成目标格式文件。"""
        ...


# ─── 辅助：从 Token 流重新渲染为 Markdown ───

def _tokens_to_markdown(tokens: list[ChapterToken], include_diary_label: bool = True) -> str:
    """将Token列表渲染为Markdown文本"""
    lines: list[str] = []
    diary_mode = False
    for token in tokens:
        if token.type == "heading":
            prefix = "#" * token.level
            lines.append(f"{prefix} {token.content[0]}")
            lines.append("")
        elif token.type == "paragraph":
            lines.extend(token.content)
            lines.append("")
        elif token.type == "list":
            for item in token.content:
                lines.append(f"- {item}")
            lines.append("")
        elif token.type == "blank":
            lines.append("")
        elif token.type == "diary":
            if include_diary_label and not diary_mode:
                # Insert the diary separator
                if lines and lines[-1] != "":
                    lines.append("")
                lines.append("---")
                lines.append("")
                diary_mode = True
            lines.extend(token.content)
            lines.append("")
    # 去掉末尾多余的换行
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")
    return "\n".join(lines)


# ─── Docx 消费者 ───


class DocxConsumer(BaseConsumer):
    """将 FormattedDocument 渲染为 DOCX 文件。"""

    def consume(self, document: FormattedDocument) -> Path:
        """生成 .docx 文件，返回文件路径"""
        try:
            from docx import Document
            from docx.shared import Pt, Cm, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            raise RuntimeError(
                "python-docx 未安装，请执行 pip install python-docx"
            )

        doc = Document()

        # 文档标题
        title_para = doc.add_heading(document.title, level=0)
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # 元数据
        meta = doc.add_paragraph()
        meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        run = meta.add_run(
            f"共 {document.chapter_count} 章 | 导出时间: {now_str}"
        )
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

        doc.add_page_break()

        for i, (filename, tokens) in enumerate(document.chapters):
            # 章节标题
            chapter_title = filename.replace(".md", "")
            doc.add_heading(chapter_title, level=1)

            # 遍历Token渲染
            diary_mode = False
            for token in tokens:
                if token.type == "heading":
                    level = min(token.level, 4)
                    doc.add_heading(token.content[0], level=level)

                elif token.type == "paragraph":
                    for line in token.content:
                        stripped = line.strip()
                        if stripped:
                            doc.add_paragraph(stripped)

                elif token.type == "list":
                    for item in token.content:
                        doc.add_paragraph(item, style="List Bullet")

                elif token.type == "blank":
                    pass  # 跳过，DOCX段落间距自动处理

                elif token.type == "diary":
                    if not diary_mode:
                        diary_mode = True
                        doc.add_paragraph("")  # spacing
                        diary_label = doc.add_paragraph()
                        run_lbl = diary_label.add_run("—— 章末日记 ——")
                        run_lbl.bold = True
                        run_lbl.font.size = Pt(10)
                        run_lbl.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

                    for line in token.content:
                        stripped = line.strip()
                        if stripped:
                            p = doc.add_paragraph(stripped)
                            p.paragraph_format.left_indent = Cm(1)

            # 章节间分页
            if i < len(document.chapters) - 1:
                doc.add_page_break()

        filename = _safe_filename(document.title, ".docx")
        filepath = self.export_dir / filename
        doc.save(str(filepath))
        return filepath


# ─── Txt 消费者 ───


class TxtConsumer(BaseConsumer):
    """将 FormattedDocument 渲染为 TXT 纯文本文件。"""

    def __init__(self, export_dir: str | Path, line_width: int = 60):
        super().__init__(export_dir)
        self.line_width = line_width

    def consume(self, document: FormattedDocument) -> Path:
        """生成 .txt 文件，返回文件路径"""
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        w = self.line_width
        lines: list[str] = []

        # 文档标题横幅
        lines.append(f"{'=' * w}")
        lines.append(f"{document.title:^{w}}")
        lines.append(f"{'=' * w}")
        lines.append(f"共 {document.chapter_count} 章")
        lines.append(f"导出时间: {now_str}")
        lines.append("")
        lines.append(f"{'=' * w}")
        lines.append("")

        for filename, tokens in document.chapters:
            chapter_title = filename.replace(".md", "")
            lines.append("")
            lines.append(f"{'─' * 40}")
            lines.append(f"  {chapter_title}")
            lines.append(f"{'─' * 40}")
            lines.append("")

            diary_mode = False
            for token in tokens:
                if token.type == "heading":
                    prefix = "#" * token.level
                    for item in token.content:
                        lines.append(f"{prefix} {item}")
                    lines.append("")

                elif token.type == "paragraph":
                    for line_text in token.content:
                        stripped = line_text.strip()
                        if stripped:
                            lines.append(stripped)
                    lines.append("")

                elif token.type == "list":
                    for item in token.content:
                        lines.append(f"  - {item}")
                    lines.append("")

                elif token.type == "blank":
                    lines.append("")

                elif token.type == "diary":
                    if not diary_mode:
                        diary_mode = True
                        lines.append("")
                        lines.append("[章末日记]")
                    for line_text in token.content:
                        stripped = line_text.strip()
                        if stripped:
                            lines.append(f"  {stripped}")
                    lines.append("")

        content = "\n".join(lines)
        filename = _safe_filename(document.title, ".txt")
        filepath = self.export_dir / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath


# ─── PDF 消费者 ───


def _find_cjk_font() -> str | None:
    """查找系统中可用的 CJK 字体，按平台依次尝试。"""
    import platform as _platform
    from pathlib import Path

    system = _platform.system()

    candidates: list[str] = []
    if system == "Windows":
        candidates = [
            r"C:\Windows\Fonts\msyh.ttc",        # 微软雅黑
            r"C:\Windows\Fonts\simsun.ttc",       # 宋体
            r"C:\Windows\Fonts\simhei.ttf",       # 黑体
            r"C:\Windows\Fonts\deng.ttf",         # 等线
            r"C:\Windows\Fonts\yahei.ttf",        # 雅黑（备选）
        ]
    elif system == "Darwin":
        candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    else:  # Linux
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
        ]

    for path in candidates:
        p = Path(path)
        if p.exists():
            return str(p)
    return None


class PdfConsumer(BaseConsumer):
    """将 FormattedDocument 渲染为 PDF 文件。

    使用 fpdf2 库（纯 Python，无系统依赖）。
    包含标题页、章节标题、正文、自动分页。
    """

    def __init__(
        self,
        export_dir: str | Path,
        font_path: str | None = None,
        font_name: str = "CJK",
        title_font_size: int = 24,
        chapter_font_size: int = 16,
        body_font_size: int = 11,
    ):
        super().__init__(export_dir)
        self.font_name = font_name
        self.title_font_size = title_font_size
        self.chapter_font_size = chapter_font_size
        self.body_font_size = body_font_size

        # 解析字体路径
        self.font_path = font_path or _find_cjk_font()
        if not self.font_path:
            raise RuntimeError(
                "未找到系统 CJK 字体。请通过 font_path 参数指定中文字体路径，"
                "或安装 Noto Sans CJK / 微软雅黑等字体。"
            )

    def _init_pdf(self) -> any:
        """初始化 FPDF 实例并注册字体"""
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)

        # TTC 字体集需要指定索引
        font_path_lower = self.font_path.lower()
        if font_path_lower.endswith(".ttc"):
            pdf.add_font(self.font_name, "", self.font_path, collection_font_number=0)
        else:
            pdf.add_font(self.font_name, "", self.font_path)
        return pdf

    def _add_title_page(self, pdf: any, document: any) -> None:
        """生成标题页"""
        from datetime import datetime, timezone

        pdf.add_page()
        pdf.ln(50)  # 垂直居中

        # 书名
        pdf.set_font(self.font_name, size=self.title_font_size)
        pdf.cell(w=0, text=document.title, align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)

        # 元信息
        pdf.set_font(self.font_name, size=11)
        now_str = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        pdf.cell(w=0, text=f"共 {document.chapter_count} 章", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(w=0, text=f"导出时间: {now_str}", align="C", new_x="LMARGIN", new_y="NEXT")

    def _render_tokens(self, pdf: any, tokens: list[ChapterToken]) -> None:
        """将 Token 列表渲染到 PDF"""
        diary_mode = False

        for token in tokens:
            if token.type == "heading":
                if token.level <= 2:
                    pdf.set_font(self.font_name, size=self.chapter_font_size)
                    pdf.ln(4)
                    for item in token.content:
                        pdf.multi_cell(w=0, text=item)
                    pdf.ln(3)
                else:
                    pdf.set_font(self.font_name, size=self.body_font_size + 2)
                    pdf.ln(2)
                    for item in token.content:
                        pdf.multi_cell(w=0, text=item)
                    pdf.ln(2)

            elif token.type == "paragraph":
                pdf.set_font(self.font_name, size=self.body_font_size)
                for line in token.content:
                    stripped = line.strip()
                    if stripped:
                        pdf.multi_cell(w=0, text=stripped)
                        pdf.ln(1)
                pdf.ln(2)

            elif token.type == "list":
                pdf.set_font(self.font_name, size=self.body_font_size)
                for item in token.content:
                    pdf.multi_cell(w=0, text=f"  · {item}")
                    pdf.ln(1)
                pdf.ln(2)

            elif token.type == "blank":
                pass

            elif token.type == "diary":
                if not diary_mode:
                    diary_mode = True
                    pdf.ln(3)
                    pdf.set_font(self.font_name, size=self.body_font_size)
                    pdf.set_text_color(100, 100, 100)
                    pdf.multi_cell(w=0, text="—— 章末日记 ——")
                    pdf.ln(2)

                for line in token.content:
                    stripped = line.strip()
                    if stripped:
                        pdf.set_font(self.font_name, size=self.body_font_size)
                        pdf.set_text_color(80, 80, 80)
                        pdf.multi_cell(w=0, text=stripped)
                        pdf.ln(1)

                pdf.set_text_color(0, 0, 0)

    def consume(self, document: FormattedDocument) -> Path:
        """生成 .pdf 文件，返回文件路径"""
        pdf = self._init_pdf()

        # 标题页
        self._add_title_page(pdf, document)

        # 各章节
        for i, (filename, tokens) in enumerate(document.chapters):
            pdf.add_page()

            # 章节标题
            chapter_title = filename.replace(".md", "")
            pdf.set_font(self.font_name, size=self.chapter_font_size)
            pdf.multi_cell(w=0, text=chapter_title)
            pdf.ln(4)

            # 渲染内容
            self._render_tokens(pdf, tokens)

        filename = _safe_filename(document.title, ".pdf")
        filepath = self.export_dir / filename
        pdf.output(str(filepath))
        return filepath


# ─── Markdown 消费者 ───


class MarkdownConsumer(BaseConsumer):
    """将 FormattedDocument 渲染为 Markdown 源码压缩包。

    以独立 .md 文件 + README.md 元信息的方式打包为 ZIP。
    """

    def consume(self, document: FormattedDocument) -> Path:
        """生成 .zip 压缩包，返回文件路径"""
        buf = BytesIO()

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # README.md 元信息
            readme_lines = [
                f"# {document.title}",
                "",
                f"导出时间: {datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}",
                f"章节数: {document.chapter_count}",
                "",
                "| # | 文件名 | 字数 |",
                "|---|--------|------|",
            ]
            for i, (filename, tokens) in enumerate(document.chapters, 1):
                word_count = sum(
                    len(token.text)
                    for token in tokens
                )
                readme_lines.append(f"| {i} | {filename} | {word_count} |")

            zf.writestr("README.md", "\n".join(readme_lines).encode("utf-8"))

            # 各章节 Markdown 文件
            for filename, tokens in document.chapters:
                md_content = _tokens_to_markdown(tokens, include_diary_label=True)
                zf.writestr(filename, md_content.encode("utf-8"))

        filename = _safe_filename(document.title, ".zip")
        filepath = self.export_dir / filename
        filepath.write_bytes(buf.getvalue())
        return filepath
