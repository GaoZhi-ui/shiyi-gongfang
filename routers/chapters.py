"""
章节管理路由

GET    /chapters                     — 列出所有章节文件
GET    /chapters/{filename}          — 读取某个章节文件
POST   /chapters                     — 创建新章节
PUT    /chapters/{filename}          — 覆盖写入章节
DELETE /chapters/{filename}          — 删除章节
POST   /chapters/{filename}/rename   — 重命名章节
GET    /chapters/{filename}/diff     — 查看 git 版本差异（若启用）

路径前缀 /api/v1/chapters
"""

import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/chapters", tags=["chapters"])
BASE = Path(__file__).resolve().parent.parent

# ─── 章节目录解析 ───


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
            pass

    local_dir = (BASE / "chapters").resolve()
    local_dir.mkdir(exist_ok=True)
    return local_dir


CHAPTERS_DIR = _resolve_chapters_dir()
ALLOWED_EXTENSIONS = {".md"}
MAX_FILE_SIZE = 5 * 1024 * 1024

# ─── 异常定义 ───


class ChapterPathTraversalError(Exception):
    pass
class ChapterNotFound(Exception):
    pass
class ChapterFileTypeError(Exception):
    pass


# ─── 安全文件操作 ───


def _safe_chapter_path(filename: str) -> Path:
    """解析并校验章节文件路径（防路径穿越）"""
    target = (CHAPTERS_DIR / filename).resolve()
    if not str(target).startswith(str(CHAPTERS_DIR.resolve())):
        raise ChapterPathTraversalError(f"路径越界: {filename}")
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ChapterFileTypeError(f"不支持的文件类型: {target.suffix}")
    return target


def _read_chapter_raw(filename: str) -> tuple[Path, str]:
    """读取章节文件原始内容"""
    target = _safe_chapter_path(filename)
    if not target.exists():
        raise ChapterNotFound(f"章节文件不存在: {filename}")
    if target.stat().st_size > MAX_FILE_SIZE:
        raise HTTPException(413, detail={"code": "FILE_TOO_LARGE", "message": "文件过大"})
    return target, target.read_text(encoding="utf-8")


# ─── 文件名解析 ───

CHAPTER_PATTERN = re.compile(r"^(?:第(\d+)(?:[-~](\d+))?章_)?(.+?)\.md$")
TMP_PREFIX = "_tmp_"
ANCHOR_KEYWORD = "锚点"
COMPILATION_KEYWORD = "合集"


def _parse_filename(name: str) -> dict:
    """解析章节文件名，返回结构化信息"""
    info = {
        "filename": name,
        "stem": Path(name).stem,
        "is_draft": name.startswith(TMP_PREFIX),
        "is_anchor": ANCHOR_KEYWORD in name,
        "is_compilation": COMPILATION_KEYWORD in name,
        "chapter_number": None,
        "chapter_end": None,
        "title": Path(name).stem,
    }
    stem = Path(name).stem
    if stem.startswith(TMP_PREFIX):
        stem = stem[len(TMP_PREFIX):]
    m = CHAPTER_PATTERN.match(stem + ".md")
    if m:
        if m.group(1):
            info["chapter_number"] = int(m.group(1))
        if m.group(2):
            info["chapter_end"] = int(m.group(2))
        info["title"] = m.group(3)
    return info


# ─── Pydantic 模型 ───


class ChapterListItem(BaseModel):
    filename: str
    stem: str
    title: str
    chapter_number: int | None = None
    chapter_end: int | None = None
    is_draft: bool = False
    is_anchor: bool = False
    is_compilation: bool = False
    size: int
    modified: str
    cjk_chars: int


class ChapterContent(BaseModel):
    filename: str
    content: str
    parsed: dict | None = None


class ChapterCreate(BaseModel):
    title: str = Field("", description="章节标题（可选，不提供则自动命名）")
    content: str = Field("", description="正文内容（Markdown）")
    filename: str | None = Field(None, description="指定文件名，不指定则自动生成")


class ChapterUpdate(BaseModel):
    content: str = Field(..., description="完整覆盖写入的 Markdown 内容")


class ChapterRename(BaseModel):
    new_filename: str = Field(..., min_length=1, description="新文件名，如 第41章_新的开始.md")


# ─── 帮助函数 ───


def _parse_chapter_path(entry: Path, result: list):
    """解析一个章节文件路径，追加到 result 列表"""
    name = entry.name
    parsed = _parse_filename(name)
    text = entry.read_text(encoding="utf-8", errors="replace")
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
    mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat()
    result.append(ChapterListItem(
        filename=name,
        stem=parsed["stem"],
        title=parsed["title"],
        chapter_number=parsed["chapter_number"],
        chapter_end=parsed["chapter_end"],
        is_draft=parsed["is_draft"],
        is_anchor=parsed["is_anchor"],
        is_compilation=parsed["is_compilation"],
        size=entry.stat().st_size,
        modified=mtime,
        cjk_chars=cjk,
    ))


def _auto_filename(title: str, existing_names: set[str]) -> str:
    """自动生成章节文件名"""
    if not title:
        max_n = 0
        for name in existing_names:
            m = re.match(r"第(\d+)章_", name)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
        next_n = max_n + 1
        return f"第{next_n}章_新章节.md"
    if re.match(r"^第\d+章_", title):
        return title if title.endswith(".md") else title + ".md"
    return f"第1章_{title}.md"


# ─── 路由 ───


@router.get("")
def list_chapters(
    status: str | None = Query(None, pattern="^(draft|published|all)?$"),
):
    """列出所有章节文件，支持状态过滤。

    - draft: 仅 _tmp_ 前缀的草稿
    - published: 排除 _tmp_ 前缀的正式章节
    - all / 不传: 全部
    """
    result = []
    for entry in sorted(CHAPTERS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        name = entry.name
        if status == "draft" and not name.startswith(TMP_PREFIX):
            continue
        if status == "published" and name.startswith(TMP_PREFIX):
            continue
        _parse_chapter_path(entry, result)
    return {"chapters": result}


@router.get("/{filename}", response_model=ChapterContent)
def read_chapter(filename: str):
    """读取某个章节文件内容"""
    try:
        target, content = _read_chapter_raw(filename)
    except ChapterPathTraversalError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})
    except ChapterFileTypeError:
        raise HTTPException(400, detail={"code": "FILE_TYPE_ERROR", "message": "仅支持 .md 文件"})
    except ChapterNotFound:
        raise HTTPException(404, detail={
            "code": "FILE_NOT_FOUND",
            "message": "章节文件不存在",
            "detail": f"'{filename}' 在 {CHAPTERS_DIR} 下未找到",
            "suggestion": "请先通过 GET /api/v1/chapters 查看可用章节列表",
        })

    parts = content.split("---", 1)
    parsed = {
        "has_diary": len(parts) > 1,
        "body_length": len(parts[0].strip()),
        "diary_length": len(parts[1].strip()) if len(parts) > 1 else 0,
    }
    return ChapterContent(filename=filename, content=content, parsed=parsed)


@router.post("", status_code=201)
def create_chapter(body: ChapterCreate):
    """创建新章节文件"""
    existing = {f.name for f in CHAPTERS_DIR.glob("*.md")}

    if body.filename:
        filename = body.filename if body.filename.endswith(".md") else body.filename + ".md"
    else:
        filename = _auto_filename(body.title, existing)

    try:
        target = _safe_chapter_path(filename)
    except (ChapterPathTraversalError, ChapterFileTypeError):
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "无效的文件名"})

    if target.exists():
        raise HTTPException(409, detail={
            "code": "FILE_ALREADY_EXISTS",
            "message": f"章节文件 '{filename}' 已存在",
            "suggestion": "使用 PUT /api/v1/chapters/{filename} 覆盖写入",
        })

    content = body.content or f"# {Path(filename).stem}\n\n"
    target.write_text(content, encoding="utf-8")
    parsed = _parse_filename(filename)

    return {
        "status": "created",
        "filename": filename,
        "path": str(target.relative_to(CHAPTERS_DIR)),
        "chapter_number": parsed["chapter_number"],
        "title": parsed["title"],
    }


@router.put("/{filename}")
def update_chapter(filename: str, body: ChapterUpdate):
    """覆盖写入章节文件"""
    try:
        target = _safe_chapter_path(filename)
    except ChapterPathTraversalError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})
    except ChapterFileTypeError:
        raise HTTPException(400, detail={"code": "FILE_TYPE_ERROR", "message": "仅支持 .md 文件"})

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")

    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', body.content))
    return {
        "status": "ok",
        "filename": filename,
        "size": len(body.content.encode("utf-8")),
        "cjk_chars": cjk,
    }


@router.delete("/{filename}")
def delete_chapter(filename: str):
    """删除章节文件"""
    try:
        target = _safe_chapter_path(filename)
    except (ChapterPathTraversalError, ChapterFileTypeError):
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "无效的文件名"})

    if not target.exists():
        raise HTTPException(404, detail={
            "code": "FILE_NOT_FOUND",
            "message": f"章节文件不存在: {filename}",
        })

    target.unlink()
    return {"status": "deleted", "filename": filename}


@router.post("/{filename}/rename")
def rename_chapter(filename: str, body: ChapterRename):
    """重命名章节文件"""
    try:
        old_target = _safe_chapter_path(filename)
    except (ChapterPathTraversalError, ChapterFileTypeError):
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "原文件名无效"})

    if not old_target.exists():
        raise HTTPException(404, detail={
            "code": "FILE_NOT_FOUND",
            "message": f"原章节文件不存在: {filename}",
        })

    new_name = body.new_filename if body.new_filename.endswith(".md") else body.new_filename + ".md"
    new_target = _safe_chapter_path(new_name)

    if new_target.exists():
        raise HTTPException(409, detail={
            "code": "FILE_ALREADY_EXISTS",
            "message": f"目标文件名已存在: {new_name}",
        })

    old_target.rename(new_target)
    return {
        "status": "renamed",
        "old_filename": filename,
        "new_filename": new_name,
    }


@router.get("/{filename}/diff")
def chapter_diff(filename: str):
    """显示章节文件的 git 版本差异（如果目录是 git 仓库）"""
    try:
        target = _safe_chapter_path(filename)
    except (ChapterPathTraversalError, ChapterFileTypeError):
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "无效的文件名"})

    if not target.exists():
        raise HTTPException(404, detail={
            "code": "FILE_NOT_FOUND",
            "message": f"章节文件不存在: {filename}",
        })

    git_dir = CHAPTERS_DIR.parent
    git_path = git_dir / ".git"
    if not git_path.exists():
        return {
            "git_available": False,
            "note": "当前目录不是 Git 仓库，无法提供版本差异",
            "content": "如需启用版本追踪，请在该目录执行 git init",
        }

    try:
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--", filename],
            capture_output=True, text=True, timeout=10, cwd=git_dir,
        )
        diff_result = subprocess.run(
            ["git", "diff", "HEAD", "--", filename],
            capture_output=True, text=True, timeout=10, cwd=git_dir,
        )

        return {
            "git_available": True,
            "filename": filename,
            "recent_commits": log_result.stdout.strip().split("\n") if log_result.stdout.strip() else [],
            "diff": diff_result.stdout,
            "diff_length": len(diff_result.stdout),
        }
    except subprocess.TimeoutExpired:
        return {"git_available": True, "error": "git 命令超时"}
    except FileNotFoundError:
        return {"git_available": False, "note": "未找到 git 命令", "content": "请安装 Git"}
    except Exception as e:
        return {"git_available": True, "error": f"git 操作异常: {e}"}
