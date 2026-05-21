"""
知识库路由

GET  /knowledge              — 列出知识库文件清单
GET  /knowledge/{filepath}   — 读取某个知识库文件内容
POST /knowledge/{filepath}   — 写入/覆盖某个知识库文件

路径前缀 /api/v1/knowledge
{filepath} 使用 FastAPI path 转换器，支持 UTF-8 文件名、点号与子目录斜杠。
"""

import re
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
BASE = Path(__file__).resolve().parent.parent

# ─── 异常定义 ───

class KnowledgePathTraversalError(Exception):
    """路径穿越检测拦截"""
class KnowledgeFileTypeError(Exception):
    """不支持的文件扩展名"""
class KnowledgeFileNotFound(Exception):
    """文件不存在"""
class KnowledgeFileTooLargeError(Exception):
    """文件超过大小限制"""

# ─── 安全文件操作（匹配 api-design.md §3.2 伪码） ───

ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def safe_resolve(base_dir: Path, relative_path: str) -> Path:
    """解析相对路径，校验越界、扩展名、文件大小"""
    target = (base_dir / relative_path).resolve()
    # 校验：必须在 base_dir 下
    if not str(target).startswith(str(base_dir.resolve())):
        raise KnowledgePathTraversalError(f"路径越界: {relative_path}")
    # 校验：扩展名白名单
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise KnowledgeFileTypeError(f"不支持的文件类型: {target.suffix}")
    # 校验：文件存在
    if not target.exists():
        raise KnowledgeFileNotFound(f"文件不存在: {relative_path}")
    # 校验：文件大小
    if target.stat().st_size > MAX_FILE_SIZE:
        raise KnowledgeFileTooLargeError(f"文件过大: {target.stat().st_size} bytes")
    return target


def safe_read(base_dir: Path, relative_path: str) -> str:
    """安全读取文件内容"""
    target = safe_resolve(base_dir, relative_path)
    return target.read_text(encoding="utf-8")


def safe_write(base_dir: Path, relative_path: str, content: str):
    """安全写入文件内容"""
    # 校验路径
    target = (base_dir / relative_path).resolve()
    if not str(target).startswith(str(base_dir.resolve())):
        raise KnowledgePathTraversalError(f"路径越界: {relative_path}")
    if target.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise KnowledgeFileTypeError(f"不支持的文件类型: {target.suffix}")
    # 确保父目录存在
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def list_files(base_dir: Path) -> list[dict]:
    """列出目录下所有符合条件的文件"""
    results = []
    for entry in sorted(base_dir.rglob("*"), key=lambda p: p.name):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if entry.name.startswith("_"):
            continue
        rel = entry.relative_to(base_dir)
        mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat()
        text = entry.read_text(encoding="utf-8", errors="replace")
        results.append({
            "name": str(rel.as_posix()),
            "title": entry.stem,
            "size": entry.stat().st_size,
            "modified": mtime,
            "cjk_chars": len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text)),
        })
    return results


# ─── 知识库根目录解析 ───

def _resolve_knowledge_base() -> Path:
    """从 config.yaml 读取知识库路径，失败时依次回退"""
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            for _name, info in cfg.get("knowledge_base", {}).items():
                root = info.get("root")
                if root:
                    p = Path(root).expanduser().resolve()
                    if p.is_dir():
                        return p
        except Exception:
            pass

    # 回退链
    candidates = [
        BASE / "knowledge",
        Path("knowledge"),
        BASE / "knowledge",
    ]
    for d in candidates:
        p = d.resolve()
        if p.is_dir():
            return p

    (BASE / "knowledge").mkdir(exist_ok=True)
    return (BASE / "knowledge").resolve()


KNOWLEDGE_BASE = _resolve_knowledge_base()

# ─── Pydantic 模型 ───

class FileInfo(BaseModel):
    name: str
    title: str
    size: int
    modified: str
    cjk_chars: int

class FileListResponse(BaseModel):
    files: list[FileInfo]
    base_path: str

class FileContent(BaseModel):
    name: str
    content: str

class FileUpdate(BaseModel):
    content: str = Field(..., description="文件新内容（完整覆盖写入）")

# ─── 路由 ───

@router.get("", response_model=FileListResponse)
def list_knowledge():
    """列出知识库文件清单（含文件名、标题、大小、修改时间、中文字数）"""
    return FileListResponse(
        files=[FileInfo(**f) for f in list_files(KNOWLEDGE_BASE)],
        base_path=str(KNOWLEDGE_BASE),
    )


@router.get("/{filepath:path}", response_model=FileContent)
def read_knowledge(filepath: str):
    """读取某个知识库文件内容"""
    if not filepath:
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "文件路径不能为空"})
    try:
        content = safe_read(KNOWLEDGE_BASE, filepath)
    except KnowledgePathTraversalError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界",
            "detail": f"'{filepath}' 解析后不在知识库根目录下", "suggestion": "请确认路径在知识库范围内"})
    except KnowledgeFileTypeError:
        raise HTTPException(400, detail={"code": "FILE_TYPE_ERROR", "message": "不支持的文件类型",
            "detail": f"仅支持 {ALLOWED_EXTENSIONS}", "suggestion": "仅支持 .md .txt .json 文件"})
    except KnowledgeFileNotFound:
        raise HTTPException(404, detail={"code": "FILE_NOT_FOUND", "message": "知识库文件不存在",
            "detail": f"'{filepath}' 在 {KNOWLEDGE_BASE} 下未找到",
            "suggestion": "请先通过 GET /api/v1/knowledge 查看可用文件列表"})
    except KnowledgeFileTooLargeError:
        raise HTTPException(413, detail={"code": "FILE_TOO_LARGE", "message": "文件过大",
            "detail": "超过 5MB 传输上限", "suggestion": "分割文件或直接通过文件系统访问"})
    return FileContent(name=filepath, content=content)


@router.post("/{filepath:path}", status_code=200)
def update_knowledge(filepath: str, body: FileUpdate):
    """写入/覆盖某个知识库文件"""
    if not filepath:
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "文件路径不能为空"})
    try:
        safe_write(KNOWLEDGE_BASE, filepath, body.content)
    except KnowledgePathTraversalError:
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})
    except KnowledgeFileTypeError:
        raise HTTPException(400, detail={"code": "FILE_TYPE_ERROR", "message": "不支持的文件类型"})

    # 自动向量化知识库文件
    try:
        from core.vector_store import get_vector_store
        # 读取 config.yaml 确定 project_id
        yaml_path = BASE / "config.yaml"
        project_id = "default"
        if yaml_path.exists():
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            active = cfg.get("active_project", "")
            if active:
                project_id = active
        get_vector_store().add_knowledge(project_id, filepath, body.content)
    except Exception as e:
        import logging as _lg
        _lg.getLogger("knowledge").warning(f"知识库文件向量化失败 [{filepath}]: {e}")

    return {"status": "ok", "path": filepath, "size": len(body.content.encode("utf-8"))}


class SearchQueryParams(BaseModel):
    q: str = Field(..., min_length=1, description="搜索关键词")
    project_id: str = Field("default", description="项目标识符")
    top_k: int = Field(5, ge=1, le=20, description="返回结果数量")


@router.get("/search")
def search_knowledge(
    q: str = Query("", description="搜索关键词"),
    project_id: str = Query("default", description="项目标识符"),
    top_k: int = Query(5, ge=1, le=20, description="返回结果数量"),
):
    """
    向量搜索知识库（语义搜索）。

    使用 sentence-transformers 将查询文本嵌入，在 ChromaDB 中检索最相关的章节/知识片段。

    参数:
      q: 搜索关键词
      project_id: 项目标识符（默认 "default"）
      top_k: 返回结果数量（1-20，默认5）
    """
    if not q:
        raise HTTPException(400, detail={"code": "INVALID_PARAMETER", "message": "搜索关键词不能为空"})

    try:
        from core.vector_store import get_vector_store
        vs = get_vector_store()
        results = vs.search(query=q, project_id=project_id, top_k=top_k)
    except Exception as e:
        raise HTTPException(500, detail={"code": "SEARCH_ERROR", "message": f"搜索失败: {e}"})

    return {
        "query": q,
        "project_id": project_id,
        "results": results,
        "total": len(results),
    }
