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

import json
import re
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import yaml
from routers.sanitize import sanitize_text
from core.enums import ChapterStatus
from core.vector_store import get_vector_store

router = APIRouter(prefix="/chapters", tags=["chapters"])
BASE = Path(__file__).resolve().parent.parent

# ─── 章节目录解析 ───


def _resolve_active_project_id() -> str:
    """从 config.yaml 读取当前活跃项目 ID，失败返回 'default'"""
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            active = cfg.get("active_project", "")
            if active:
                return active
        except Exception:
            pass  # config optional
    return "default"


def _resolve_chapters_dir() -> Path:
    """从 config.yaml 读取章节目录路径，失败则回退到本地 chapters/"""
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
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
            pass  # config optional

    local_dir = (BASE / "chapters").resolve()
    local_dir.mkdir(exist_ok=True)
    return local_dir


CHAPTERS_DIR = _resolve_chapters_dir()
ALLOWED_EXTENSIONS = {".md"}
MAX_FILE_SIZE = 5 * 1024 * 1024


# ─── Git 自动提交 ───


def _is_git_repo(proj_dir: Path) -> bool:
    """检查目录是否为 Git 仓库"""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(proj_dir),
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _auto_git_commit(action: str, filename: str):
    """自动执行 git add + commit（静默跳过不可用情况）"""
    proj_dir = CHAPTERS_DIR.parent.resolve()
    try:
        if not _is_git_repo(proj_dir):
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        subprocess.run(
            ["git", "add", "."],
            cwd=str(proj_dir),
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", f"auto: {action} {filename} - {timestamp}"],
            cwd=str(proj_dir),
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # Git not available, 静默跳过

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


# ─── Frontmatter 管理 ───


def _count_words(text: str) -> int:
    """统计中英文字数。
    CJK 字符每个计 1 字，英文按空白分词计词。
    自动跳过 YAML frontmatter 区域。
    """
    if not text:
        return 0
    # 移除 frontmatter 后再统计
    body = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', body))
    non_cjk = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', ' ', body)
    english_words = len(non_cjk.split())
    return cjk + english_words


def _extract_frontmatter(content: str) -> tuple[dict | None, str]:
    """提取 YAML frontmatter。

    返回 (fm_dict, body)，如果内容不以 '---' 开头则返回 (None, content)。
    """
    if not content.startswith('---'):
        return None, content
    parts = content.split('---', 2)
    if len(parts) < 3:
        return None, content
    try:
        fm = yaml.safe_load(parts[1])
        if isinstance(fm, dict):
            return fm, parts[2].lstrip('\n')
    except yaml.YAMLError:
        pass
    return None, content


def _build_frontmatter(
    title: str,
    content: str,
    existing_fm: dict | None = None,
    status: str | None = None,
) -> str:
    """构建 YAML frontmatter 字符串。

    参数：
      title: 章节展示标题（如 '第41章_新的开始'）
      content: 正文内容（不含 frontmatter）
      existing_fm: 已有的 frontmatter 字典（合并字段用）
      status: 章节状态（新建时指定）
    """
    words = _count_words(content)

    fm: dict = {
        "title": title,
        "scene": None,
        "timeline": None,
        "status": status or "draft",
        "words": words,
        "target": None,
        "connected_scenes": [],
    }

    if existing_fm:
        # 用户手动设置的元数据字段 → 保留
        for key in ("title", "scene", "timeline", "target"):
            if existing_fm.get(key):
                fm[key] = existing_fm[key]
        if existing_fm.get("status"):
            fm["status"] = existing_fm["status"]
        if existing_fm.get("connected_scenes"):
            fm["connected_scenes"] = existing_fm["connected_scenes"]
        # words 始终重新统计，不保留旧值
        fm["words"] = words

    # 自定义 YAML Dumper：None 值输出为空（不写 'null'）
    class _FmDumper(yaml.Dumper):
        pass
    _FmDumper.add_representer(
        type(None),
        lambda d, _: d.represent_scalar('tag:yaml.org,2002:null', ''),
    )

    return (
        "---\n"
        + yaml.dump(fm, Dumper=_FmDumper, allow_unicode=True,
                     default_flow_style=False, sort_keys=False)
        + "---\n"
    )


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
    status: ChapterStatus = ChapterStatus.DRAFT
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
    status: ChapterStatus = Field(default=ChapterStatus.DRAFT, description="章节状态")


class ChapterUpdate(BaseModel):
    content: str = Field(..., description="完整覆盖写入的 Markdown 内容")


class ChapterRename(BaseModel):
    new_filename: str = Field(..., min_length=1, description="新文件名，如 第41章_新的开始.md")


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="搜索关键词")
    scope: Literal["all"] | list[str] = Field("all", description="搜索范围：'all' 或文件名列表")


class MatchItem(BaseModel):
    line: int
    content: str
    index: int


class SearchResultItem(BaseModel):
    filename: str
    title: str
    matches: list[MatchItem]
    match_count: int


# ─── 标签树构建 ───


def _build_tag_tree(tags: dict) -> dict:
    """
    将扁平标签字典构建为嵌套标签树。

    使用 Notable 风格的 split('/') + reduce 模式：
      标签 "卷壹/龙门" → 顶层 "卷壹" → 子层 "龙门"
      旧标签 "对话"    → 根层级 "对话"

    返回结构：
      {
        "卷壹": {"count": 5, "children": {
          "龙门": {"count": 3, "children": {}},
          "荒野": {"count": 2, "children": {}}
        }},
        "对话": {"count": 4, "children": {}}
      }
    """
    tree: dict = {}

    # 第一遍：精确计数每层
    for _filename, tag_list in tags.items():
        for tag in tag_list:
            parts = tag.split("/")
            current = tree
            for i, part in enumerate(parts):
                if part not in current:
                    current[part] = {"count": 0, "children": {}}
                # 仅在此路径节点上计数（父节点总计数后续合并）
                current[part]["count"] += 1
                if i < len(parts) - 1:
                    current = current[part]["children"]

    # 不向上合并——每个节点只计直接命中的章节数
    # 理由："卷壹" 的计数只统计标签正好是 "卷壹" 的章节
    # 用户看树形结构时可以根据子节点自行推算
    return tree


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
    status: ChapterStatus | None = Query(None, description="按章节状态过滤"),
):
    """列出所有章节文件，支持状态过滤。

    - draft: 草稿状态
    - reviewing: 审阅中
    - final: 定稿
    - 不传: 全部
    """
    result = []
    for entry in sorted(CHAPTERS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        name = entry.name
        if status and not name.startswith(TMP_PREFIX):
            # _tmp_ 前缀自动对应 DRAFT，无前缀的章节可由用户自行设置状态
            continue
        if status == ChapterStatus.DRAFT and not name.startswith(TMP_PREFIX):
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

    # 自动写入 frontmatter
    stem = Path(filename).stem
    if stem.startswith(TMP_PREFIX):
        display_title = stem[len(TMP_PREFIX):]
    else:
        display_title = stem
    fm_text = _build_frontmatter(
        title=display_title,
        content=content,
        existing_fm=None,
        status=body.status.value if isinstance(body.status, ChapterStatus) else str(body.status),
    )
    target.write_text(fm_text + content, encoding="utf-8")

    _auto_git_commit("create", filename)

    # 自动向量化
    try:
        project_id = _resolve_active_project_id()
        get_vector_store().add_chapter(project_id, filename, display_title, content)  # non-blocking on timeout
    except Exception as e:
        logger = __import__("logging").getLogger("chapters")
        logger.warning(f"章节向量化失败 [{filename}]: {e}")

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
    """覆盖写入章节文件（自动管理 YAML frontmatter）"""
    try:
        target = _safe_chapter_path(filename)
    except ChapterPathTraversalError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})
    except ChapterFileTypeError:
        raise HTTPException(400, detail={"code": "FILE_TYPE_ERROR", "message": "仅支持 .md 文件"})

    target.parent.mkdir(parents=True, exist_ok=True)

    # 从请求内容中提取 frontmatter（如果前端传回了含 frontmatter 的全文）
    req_fm, clean_content = _extract_frontmatter(body.content)

    # 如果请求中没有携带 frontmatter，尝试从磁盘上已有文件获取
    existing_fm = req_fm
    if existing_fm is None and target.exists():
        disk_content = target.read_text(encoding="utf-8")
        disk_fm, _ = _extract_frontmatter(disk_content)
        existing_fm = disk_fm

    # 从前端传的正文中或者文件名中提取标题
    if req_fm and req_fm.get("title"):
        title = req_fm["title"]
    else:
        stem = Path(filename).stem
        if stem.startswith(TMP_PREFIX):
            title = stem[len(TMP_PREFIX):]
        else:
            title = stem

    fm_text = _build_frontmatter(
        title=title,
        content=clean_content,
        existing_fm=existing_fm,
    )

    final_content = fm_text + clean_content
    target.write_text(final_content, encoding="utf-8")

    _auto_git_commit("update", filename)

    # 自动向量化（更新）
    try:
        project_id = _resolve_active_project_id()
        get_vector_store().add_chapter(project_id, filename, title, clean_content)  # non-blocking on timeout
    except Exception as e:
        logger = __import__("logging").getLogger("chapters")
        logger.warning(f"章节向量化更新失败 [{filename}]: {e}")

    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', clean_content))
    return {
        "status": "ok",
        "filename": filename,
        "size": len(final_content.encode("utf-8")),
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

    # 删除向量
    try:
        project_id = _resolve_active_project_id()
        get_vector_store().delete_chapter(project_id, filename)  # non-blocking on timeout
    except Exception as e:
        logger = __import__("logging").getLogger("chapters")
        logger.warning(f"章节向量删除失败 [{filename}]: {e}")

    target.unlink()
    _auto_git_commit("delete", filename)
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


# ─── 搜索 ───


@router.post("/search")
def search_chapters(body: SearchRequest):
    """全局搜索章节内容"""
    query_lower = body.query.lower()

    # 确定搜索范围
    if body.scope == "all":
        files = sorted(CHAPTERS_DIR.glob("*.md"))
    else:
        files = []
        for name in body.scope:
            try:
                p = _safe_chapter_path(name)
                if p.exists():
                    files.append(p)
            except (ChapterPathTraversalError, ChapterFileTypeError):
                continue

    results: list[dict] = []

    for filepath in files:
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        lines = text.split("\n")
        matches: list[dict] = []

        for line_no, line in enumerate(lines, 1):
            idx = line.lower().find(query_lower)
            if idx == -1:
                continue
            # 收集该行所有匹配位置
            search_from = 0
            while True:
                pos = line.lower().find(query_lower, search_from)
                if pos == -1:
                    break
                matches.append({
                    "line": line_no,
                    "content": line.strip(),
                    "index": pos,
                })
                search_from = pos + len(query_lower)

        if not matches:
            continue

        parsed = _parse_filename(filepath.name)
        results.append({
            "filename": filepath.name,
            "title": parsed["title"],
            "matches": matches,
            "match_count": len(matches),
        })

    return {"results": results, "total": len(results)}


# ─── 批量操作请求体 ───


class BatchDeleteBody(BaseModel):
    chapter_ids: list[str] = Field(..., min_length=1, description="要删除的章节文件名列表")


class BatchExportBody(BaseModel):
    chapter_ids: list[str] = Field(..., min_length=1, description="要导出的章节文件名列表")
    format: Literal["docx", "txt", "markdown"] = Field("markdown", description="导出格式")


class BatchTagBody(BaseModel):
    chapter_ids: list[str] = Field(..., min_length=1, description="要打标签的章节文件名列表")
    tag: str = Field(..., min_length=1, max_length=50, description="标签名")


# ─── 标签存储 ───


TAGS_FILE = BASE / "data" / "chapter_tags.json"


def _load_tags() -> dict:
    if TAGS_FILE.exists():
        return json.loads(TAGS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_tags(tags: dict):
    TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TAGS_FILE.write_text(
        json.dumps(tags, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _cleanup_tags(filenames: list[str]):
    """删除指定文件名的标签记录"""
    tags = _load_tags()
    changed = False
    for fn in filenames:
        if fn in tags:
            del tags[fn]
            changed = True
    if changed:
        _save_tags(tags)


# ─── 批量操作路由 ───


@router.post("/batch/delete")
def batch_delete_chapters(body: BatchDeleteBody):
    """批量删除章节文件"""
    deleted: list[str] = []
    errors: list[dict] = []

    for filename in body.chapter_ids:
        try:
            target = _safe_chapter_path(filename)
            if not target.exists():
                errors.append({"filename": filename, "reason": "not_found"})
                continue
            target.unlink()
            deleted.append(filename)
        except (ChapterPathTraversalError, ChapterFileTypeError) as e:
            errors.append({"filename": filename, "reason": str(e)})

    # 清理被删除章节的标签记录
    _cleanup_tags(deleted)

    return {
        "status": "ok" if not errors else "partial",
        "deleted": deleted,
        "deleted_count": len(deleted),
        "errors": errors,
        "error_count": len(errors),
    }


@router.post("/batch/export", status_code=201)
def batch_export_chapters(body: BatchExportBody):
    """批量导出章节，返回下载链接"""
    # 延迟导入避免循环引用
    from routers.export import (
        _collect_chapters as _export_collect,
        _export_docx,
        _export_txt,
        _export_markdown_zip,
        _export_title,
    )

    chapters = _export_collect(body.chapter_ids)
    title = _export_title(body.chapter_ids, None)

    if body.format == "docx":
        filepath = _export_docx(chapters, title)
    elif body.format == "txt":
        filepath = _export_txt(chapters, title)
    else:
        filepath = _export_markdown_zip(chapters, title)

    return {
        "status": "ok",
        "format": body.format,
        "filename": filepath.name,
        "chapter_count": len(chapters),
        "download_url": f"/export/{filepath.name}",
    }


# ─── 标签树路由 ───


class TagTreeNode(BaseModel):
    count: int
    children: dict[str, "TagTreeNode"]


TagTreeNode.model_rebuild()


@router.get("/tags/tree")
def get_tag_tree():
    """获取嵌套标签树"""
    tags = _load_tags()
    return _build_tag_tree(tags)


@router.post("/batch/tag")
def batch_tag_chapters(body: BatchTagBody):
    """批量给章节打标签（支持层级标签，用 / 分隔路径）"""
    clean_tag = sanitize_text(body.tag)
    tags = _load_tags()
    tagged: list[str] = []
    errors: list[dict] = []

    for filename in body.chapter_ids:
        try:
            target = _safe_chapter_path(filename)
            if not target.exists():
                errors.append({"filename": filename, "reason": "not_found"})
                continue

            if filename not in tags:
                tags[filename] = []
            if clean_tag not in tags[filename]:
                tags[filename].append(clean_tag)
            tagged.append(filename)
        except (ChapterPathTraversalError, ChapterFileTypeError) as e:
            errors.append({"filename": filename, "reason": str(e)})

    _save_tags(tags)

    return {
        "status": "ok" if not errors else "partial",
        "tag": body.tag,
        "tagged": tagged,
        "tagged_count": len(tagged),
        "errors": errors,
        "error_count": len(errors),
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
