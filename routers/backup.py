"""
项目备份与恢复路由

GET    /api/v1/projects/{id}/backup   — 下载项目完整备份（zip）
POST   /api/v1/projects/{id}/restore  — 从 zip 恢复项目

前缀 /api/v1/projects（由 main.py 注册时附加）
"""

import json, uuid, zipfile
from io import BytesIO
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

router = APIRouter(prefix="/projects", tags=["backup"])
BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"
EXPORT_DIR = BASE / "export"

EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# 备份包含的子目录（仅实际存在的才打包）
BACKUP_SUBDIRS = [
    "chapters",
    "knowledge",
    "scenes",
    "characters",
    "foreshadowing",
    "goals",
    "snapshots",
]


def _project_path(project_id: str) -> Path:
    """返回项目目录，不存在则抛出 404"""
    p = PROJECTS_DIR / project_id
    if not p.is_dir() or not (p / "config.json").is_file():
        raise HTTPException(status_code=404, detail="项目不存在")
    return p


# ─── 备份 ───

@router.get("/{project_id}/backup")
def backup_project(project_id: str):
    """将项目目录打包为 zip 并返回下载链接"""
    proj_dir = _project_path(project_id)

    zip_filename = f"backup_{project_id}_{uuid.uuid4().hex[:8]}.zip"
    zip_path = EXPORT_DIR / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 打包 config.json（必须存在）
        config_path = proj_dir / "config.json"
        if config_path.is_file():
            zf.write(config_path, config_path.relative_to(proj_dir))

        # 打包各子目录（跳过不存在的）
        for subdir in BACKUP_SUBDIRS:
            src = proj_dir / subdir
            if not src.is_dir():
                continue
            for filepath in sorted(src.rglob("*")):
                if filepath.is_file():
                    arcname = filepath.relative_to(proj_dir)
                    zf.write(filepath, arcname)

    return {
        "status": "ok",
        "project_id": project_id,
        "filename": zip_filename,
        "file_size": zip_path.stat().st_size,
        "download_url": f"/export/{zip_filename}",
    }


# ─── 恢复 ───

@router.post("/{project_id}/restore")
async def restore_project(project_id: str, file: UploadFile = File(...)):
    """上传 zip 备份，解压后覆盖项目目录"""
    proj_dir = _project_path(project_id)

    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 文件")

    # 读取上传的 zip
    raw = await file.read()
    restored_files = []

    try:
        with zipfile.ZipFile(BytesIO(raw), "r") as zf:
            for info in zf.infolist():
                # 跳过目录条目
                if info.filename.endswith("/"):
                    continue

                # 路径安全检查：防止 zip slip
                dest = (proj_dir / info.filename).resolve()
                if not str(dest).startswith(str(proj_dir.resolve())):
                    raise HTTPException(
                        status_code=400,
                        detail=f"非法的路径条目: {info.filename}",
                    )

                # 创建父目录并写入
                dest.parent.mkdir(parents=True, exist_ok=True)
                zf.extract(info, proj_dir)
                restored_files.append(info.filename)

    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="无效的 zip 文件")

    return {
        "status": "ok",
        "project_id": project_id,
        "restored_count": len(restored_files),
        "restored_files": restored_files,
    }
