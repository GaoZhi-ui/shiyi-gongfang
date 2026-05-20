"""
版本快照路由

POST /api/v1/snapshots                   — 创建快照（保存当前所有章节状态）
GET  /api/v1/snapshots                   — 列出快照
POST /api/v1/snapshots/{id}/restore      — 恢复到指定快照

数据存储: snapshots/{project_id}.json
每个项目一个文件，内含该项目的所有快照记录。
路径前缀 /api/v1/snapshots
"""

import json, re, shutil
import difflib
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/snapshots", tags=["snapshots"])
BASE = Path(__file__).resolve().parent.parent
SNAPSHOTS_DIR = BASE / "snapshots"

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


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
            pass
    local_dir = (BASE / "chapters").resolve()
    local_dir.mkdir(exist_ok=True)
    return local_dir


def _resolve_project_id() -> str:
    """返回当前活跃项目 ID（用于快照文件命名）"""
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            active = cfg.get("active_project", "default")
            return active
        except Exception:
            pass
    return "default"


CHAPTERS_DIR = _resolve_chapters_dir()

# ─── 快照文件名处理 ───

ALLOWED_EXTENSIONS = {".md"}


def _snapshots_file(project_id: str) -> Path:
    """获取快照存储文件路径"""
    name = re.sub(r'[^a-zA-Z0-9_\-]', '_', project_id)
    return SNAPSHOTS_DIR / f"{name}.json"


def _load_snapshots(project_id: str) -> list[dict]:
    """加载某个项目的全部快照"""
    path = _snapshots_file(project_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_snapshots(project_id: str, snapshots: list[dict]):
    """持久化某个项目的全部快照"""
    path = _snapshots_file(project_id)
    path.write_text(
        json.dumps(snapshots, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _collect_chapter_snapshot() -> dict[str, str]:
    """收集当前所有章节文件的内容快照"""
    snapshot: dict[str, str] = {}
    for entry in sorted(CHAPTERS_DIR.glob("*.md")):
        name = entry.name
        if entry.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        snapshot[name] = entry.read_text(encoding="utf-8", errors="replace")
    return snapshot


def _generate_id() -> str:
    """生成时间戳快照 ID"""
    now = datetime.now(timezone.utc).astimezone()
    return f"snap_{now.strftime('%Y%m%d_%H%M%S')}"


# ─── 模型 ───


class SnapshotCreate(BaseModel):
    label: str = Field("", description="快照标签（可选，用于标识）")


class SnapshotInfo(BaseModel):
    id: str
    label: str
    created_at: str
    file_count: int
    total_size: int


# ─── 路由 ───


@router.post("", status_code=201)
def create_snapshot(body: SnapshotCreate = SnapshotCreate()):
    """创建当前所有章节的快照"""
    project_id = _resolve_project_id()
    chapters = _collect_chapter_snapshot()

    if not chapters:
        raise HTTPException(400, detail={
            "code": "NO_CHAPTERS",
            "message": "当前项目没有章节文件，无法创建快照",
        })

    now = datetime.now(timezone.utc).astimezone()
    snapshot_id = _generate_id()

    total_size = sum(len(v.encode("utf-8")) for v in chapters.values())

    entry = {
        "id": snapshot_id,
        "project_id": project_id,
        "label": body.label or f"快照 {now.strftime('%Y-%m-%d %H:%M')}",
        "created_at": now.isoformat(),
        "chapters": chapters,
        "file_count": len(chapters),
        "total_size": total_size,
    }

    snapshots = _load_snapshots(project_id)
    snapshots.append(entry)
    _save_snapshots(project_id, snapshots)

    return {
        "status": "created",
        "snapshot": SnapshotInfo(
            id=snapshot_id,
            label=entry["label"],
            created_at=entry["created_at"],
            file_count=entry["file_count"],
            total_size=entry["total_size"],
        ),
    }


@router.get("")
def list_snapshots():
    """列出当前项目的所有快照"""
    project_id = _resolve_project_id()
    snapshots = _load_snapshots(project_id)

    return {
        "project_id": project_id,
        "count": len(snapshots),
        "snapshots": [
            SnapshotInfo(
                id=s["id"],
                label=s.get("label", ""),
                created_at=s.get("created_at", ""),
                file_count=s.get("file_count", 0),
                total_size=s.get("total_size", 0),
            )
            for s in reversed(snapshots)
        ],
    }


# ─── 差异分析模型 ───


class DiffParagraph(BaseModel):
    type: str  # same | added | removed | modified
    content: str
    old_content: str | None = None


class ChapterDiff(BaseModel):
    filename: str
    paragraphs: list[DiffParagraph]
    has_changes: bool


class DiffResponse(BaseModel):
    compare_from: str
    compare_to: str
    chapters: list[ChapterDiff]
    total_changes: int


@router.get("/{snapshot_id}/diff")
def snapshot_diff(
    snapshot_id: str,
    compare_to: str = Query("current", description="对比目标：快照 ID 或 'current'"),
):
    """比较两个快照之间（或快照与当前文件之间）的段落级差异"""
    project_id = _resolve_project_id()
    snapshots = _load_snapshots(project_id)

    # 查找源快照
    source = None
    for s in snapshots:
        if s["id"] == snapshot_id:
            source = s
            break
    if source is None:
        raise HTTPException(404, detail={
            "code": "SNAPSHOT_NOT_FOUND",
            "message": f"快照 {snapshot_id} 不存在",
        })

    source_chapters: dict[str, str] = source.get("chapters", {})

    # 获取目标内容
    if compare_to == "current":
        target_chapters = _collect_chapter_snapshot()
        target_label = "当前版本"
    else:
        target = None
        for s in snapshots:
            if s["id"] == compare_to:
                target = s
                break
        if target is None:
            raise HTTPException(404, detail={
                "code": "TARGET_NOT_FOUND",
                "message": f"对比目标快照 {compare_to} 不存在",
            })
        target_chapters = target.get("chapters", {})
        target_label = target.get("label", compare_to)

    # 合并所有文件名
    all_filenames = sorted(set(list(source_chapters.keys()) + list(target_chapters.keys())))

    chapter_diffs = []
    total_changes = 0

    for filename in all_filenames:
        src_text = source_chapters.get(filename, "")
        tgt_text = target_chapters.get(filename, "")

        paragraphs = _compute_paragraph_diff(src_text, tgt_text)
        has_changes = any(p.type != "same" for p in paragraphs)
        if has_changes:
            total_changes += 1

        chapter_diffs.append(ChapterDiff(
            filename=filename,
            paragraphs=paragraphs,
            has_changes=has_changes,
        ))

    return DiffResponse(
        compare_from=source.get("label", snapshot_id),
        compare_to=target_label,
        chapters=chapter_diffs,
        total_changes=total_changes,
    )


def _compute_paragraph_diff(src: str, tgt: str) -> list[DiffParagraph]:
    """使用 difflib 比较两段文本的段落级差异"""
    src_paras = [p.strip() for p in src.split("\n") if p.strip()]
    tgt_paras = [p.strip() for p in tgt.split("\n") if p.strip()]

    matcher = difflib.SequenceMatcher(None, src_paras, tgt_paras)
    result = []

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            for idx in range(i1, i2):
                result.append(DiffParagraph(type="same", content=src_paras[idx]))
        elif op == "replace":
            for idx in range(i1, i2):
                result.append(DiffParagraph(
                    type="modified",
                    content=tgt_paras[j1 + (idx - i1)] if (j1 + (idx - i1)) < j2 else "",
                    old_content=src_paras[idx],
                ))
            for idx in range(j1 + (i2 - i1), j2):
                result.append(DiffParagraph(type="added", content=tgt_paras[idx]))
        elif op == "delete":
            for idx in range(i1, i2):
                result.append(DiffParagraph(type="removed", content=src_paras[idx]))
        elif op == "insert":
            for idx in range(j1, j2):
                result.append(DiffParagraph(type="added", content=tgt_paras[idx]))

    return result


@router.post("/{snapshot_id}/restore")
def restore_snapshot(snapshot_id: str):
    """恢复到指定的快照版本（覆盖当前章节文件）"""
    project_id = _resolve_project_id()
    snapshots = _load_snapshots(project_id)

    target = None
    for s in snapshots:
        if s["id"] == snapshot_id:
            target = s
            break

    if target is None:
        raise HTTPException(404, detail={
            "code": "SNAPSHOT_NOT_FOUND",
            "message": f"快照 {snapshot_id} 不存在",
            "hint": "请先通过 GET /api/v1/snapshots 查看可用快照列表",
        })

    chapters: dict[str, str] = target.get("chapters", {})
    if not chapters:
        raise HTTPException(400, detail={
            "code": "EMPTY_SNAPSHOT",
            "message": "该快照不包含章节数据，无法恢复",
        })

    restored = []
    skipped = []

    for filename, content in chapters.items():
        target_path = (CHAPTERS_DIR / filename).resolve()
        # 路径穿越防护
        if not str(target_path).startswith(str(CHAPTERS_DIR.resolve())):
            skipped.append(filename)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")
        restored.append(filename)

    return {
        "status": "restored",
        "snapshot_id": snapshot_id,
        "label": target.get("label", ""),
        "restored_count": len(restored),
        "restored_files": restored,
        "skipped_files": skipped if skipped else None,
    }
