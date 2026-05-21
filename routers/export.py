"""
一键导出路由

POST /api/v1/export/docx       — 导出为 docx（传章节 ID 列表或 "all"）
POST /api/v1/export/txt        — 导出为 txt
POST /api/v1/export/markdown   — 导出为 markdown 压缩包

导出文件存 export/ 临时目录，返回下载链接。
路径前缀 /api/v1/export

架构：原始文本 → tokenize() → ChapterToken[] → FormattedDocument → Consumer
"""

import json, re, zipfile, uuid
from io import BytesIO
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from core.export_engine import build_document
from core.export_consumers import (
    DocxConsumer, TxtConsumer, PdfConsumer, MarkdownConsumer,
    EpubConsumer, EbookConsumer,
)

router = APIRouter(prefix="/export", tags=["export"])
BASE = Path(__file__).resolve().parent.parent
EXPORT_DIR = BASE / "export"

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

MAX_EXPORT_FILES = 100


# ─── 共享：章节目录解析 ───

def _resolve_chapters_dir() -> Path:
    """从 config.yaml 读取章节目录路径，失败则回退到本地 chapters/"""
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            active = cfg.get("active_project", "")
            proj = cfg.get("projects", {}).get(active, {})
            root = proj.get("root")
            chapters_rel = proj.get("chapters_dir", "chapters")
            if root:
                p = Path(root).expanduser().resolve() / chapters_rel
                if p.is_dir():
                    return p
        except Exception:
            pass  # fallback to local dir
    local_dir = (BASE / "chapters").resolve()
    local_dir.mkdir(exist_ok=True)
    return local_dir


CHAPTERS_DIR = _resolve_chapters_dir()
ALLOWED_EXTENSIONS = {".md"}


# ─── 请求体模型 ───


class ExportBody(BaseModel):
    chapters: list[str] | Literal["all"] = Field(
        "all",
        description="要导出的章节列表，或 'all' 表示全部",
    )
    title: str | None = Field(
        None,
        description="导出文件标题（可选，默认使用项目名或当前日期）",
    )


# ─── 工具函数 ───


def _collect_chapters(
    chapters_param: list[str] | str,
) -> list[tuple[str, str]]:
    """
    根据参数收集章节文件内容。
    返回 [(filename, content), ...] 列表。
    """
    all_files: list[Path] = sorted(
        CHAPTERS_DIR.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
    )

    if not all_files:
        raise HTTPException(400, detail={
            "code": "NO_CHAPTERS",
            "message": "当前项目没有章节文件，无法导出",
        })

    selected: list[Path] = []

    if chapters_param == "all":
        selected = all_files
    else:
        if not isinstance(chapters_param, list) or not chapters_param:
            raise HTTPException(400, detail={
                "code": "INVALID_PARAMETER",
                "message": "chapters 必须为 'all' 或非空文件名列表",
            })
        requested = set(chapters_param)
        for f in all_files:
            if f.name in requested:
                selected.append(f)

        not_found = requested - {f.name for f in all_files}
        if not_found:
            raise HTTPException(404, detail={
                "code": "CHAPTERS_NOT_FOUND",
                "message": f"以下章节不存在: {', '.join(sorted(not_found))}",
                "hint": "请先通过 GET /api/v1/chapters 查看可用章节列表",
            })

    if len(selected) > MAX_EXPORT_FILES:
        raise HTTPException(413, detail={
            "code": "TOO_MANY_FILES",
            "message": f"单次导出最多 {MAX_EXPORT_FILES} 个文件，当前选择了 {len(selected)} 个",
        })

    result: list[tuple[str, str]] = []
    for f in selected:
        result.append((f.name, f.read_text(encoding="utf-8", errors="replace")))

    return result


def _export_title(chapters_param: list[str] | str, custom_title: str | None) -> str:
    """生成导出文件标题"""
    if custom_title:
        return custom_title
    now = datetime.now(timezone.utc).astimezone()
    return f"写作助手_导出_{now.strftime('%Y%m%d_%H%M')}"


# ─── 内部导出函数（基于 export_engine） ───


def _export_docx(chapters: list[tuple[str, str]], title: str) -> Path:
    """Token化 → DocxConsumer 管线"""
    doc = build_document(title, chapters)
    consumer = DocxConsumer(export_dir=EXPORT_DIR)
    return consumer.consume(doc)


def _export_txt(chapters: list[tuple[str, str]], title: str) -> Path:
    """Token化 → TxtConsumer 管线"""
    doc = build_document(title, chapters)
    consumer = TxtConsumer(export_dir=EXPORT_DIR)
    return consumer.consume(doc)


def _export_pdf(chapters: list[tuple[str, str]], title: str) -> Path:
    """Token化 → PdfConsumer 管线"""
    doc = build_document(title, chapters)
    consumer = PdfConsumer(export_dir=EXPORT_DIR)
    return consumer.consume(doc)


def _export_markdown_zip(chapters: list[tuple[str, str]], title: str) -> Path:
    """Token化 → MarkdownConsumer 管线"""
    doc = build_document(title, chapters)
    consumer = MarkdownConsumer(export_dir=EXPORT_DIR)
    return consumer.consume(doc)


def _export_epub(chapters: list[tuple[str, str]], title: str) -> Path:
    """Token化 → EpubConsumer 管线"""
    doc = build_document(title, chapters)
    consumer = EpubConsumer(export_dir=EXPORT_DIR)
    return consumer.consume(doc)


def _export_ebook(
    chapters: list[tuple[str, str]],
    title: str,
    author: str = "写作助手工坊",
    subtitle: str | None = None,
) -> Path:
    """Token化 → EbookConsumer 管线（含封面 + 目录）"""
    doc = build_document(title, chapters)
    consumer = EbookConsumer(
        export_dir=EXPORT_DIR,
        author=author,
        cover_subtitle=subtitle,
    )
    return consumer.consume(doc)


# ─── 路由 ───


@router.post("/docx", status_code=201)
def export_docx(body: ExportBody):
    """导出为 DOCX 文档"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_docx(chapters, title)
    return {
        "status": "ok",
        "format": "docx",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


@router.post("/txt", status_code=201)
def export_txt(body: ExportBody):
    """导出为 TXT 纯文本"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_txt(chapters, title)
    return {
        "status": "ok",
        "format": "txt",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


@router.post("/markdown", status_code=201)
def export_markdown(body: ExportBody):
    """导出为 Markdown 压缩包"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_markdown_zip(chapters, title)
    return {
        "status": "ok",
        "format": "zip",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


@router.post("/pdf", status_code=201)
def export_pdf(body: ExportBody):
    """导出为 PDF 文档"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_pdf(chapters, title)
    return {
        "status": "ok",
        "format": "pdf",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


# ─── EPUB 导出模型 ───


class EpubExportBody(ExportBody):
    """EPUB 导出请求体，复用 ExportBody 的字段"""
    pass


# ─── 电子书编译请求体 ───


class EbookExportBody(BaseModel):
    chapters: list[str] | Literal["all"] = Field(
        "all",
        description="要编译的章节列表，或 'all' 表示全部",
    )
    title: str | None = Field(
        None,
        description="电子书标题（可选）",
    )
    author: str = Field(
        "写作助手工坊",
        description="作者名，用于封面页",
    )
    subtitle: str | None = Field(
        None,
        description="封面副标题（可选）",
    )


# ─── EPUB 导出端点 ───


@router.post("/epub", status_code=201)
def export_epub(body: EpubExportBody):
    """导出为 EPUB 电子书"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_epub(chapters, title)
    return {
        "status": "ok",
        "format": "epub",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


# ─── 电子书编译（多章合并 + 封面 + 目录）端点 ───


@router.post("/ebook", status_code=201)
def export_ebook(body: EbookExportBody):
    """编译为完整电子书（含封面页 + 完整目录），输出 EPUB 格式"""
    chapters = _collect_chapters(body.chapters)
    title = _export_title(body.chapters, body.title)
    filepath = _export_ebook(
        chapters=chapters,
        title=title,
        author=body.author,
        subtitle=body.subtitle,
    )
    return {
        "status": "ok",
        "format": "ebook",
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "author": body.author,
        "download_url": f"/export/{filepath.name}",
    }
