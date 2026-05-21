"""
Git 版本管理路由

GET    /git/{project_id}/log        — 查看 git log
POST   /git/{project_id}/branch     — 创建分支
POST   /git/{project_id}/checkout   — 切换分支
GET    /git/{project_id}/branches   — 列出所有分支
POST   /git/{project_id}/diff       — 比较两次 commit 差异
GET    /git/{project_id}/status     — 查看工作区状态

路径前缀 /api/v1/git

所有操作通过 subprocess 调用 git 命令，静默跳过 git 不可用的情况。
"""

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from routers.sanitize import sanitize_text
from routers.projects import _find_project, ProjectNotFound, ProjectOperationError

import shutil
_git_cmd = shutil.which("git") or "git"
router = APIRouter(prefix="/git", tags=["git"])


# ─── 安全过滤 ───

# 只允许安全的 git 引用名（分支名、tag 名）
_SAFE_REF_RE = re.compile(r"^[a-zA-Z0-9_\-\/\.]+$")

# commit hash：只允许 40 位 hex 或缩写
_SAFE_HASH_RE = re.compile(r"^[a-f0-9]{4,40}$")


def _sanitize_ref(name: str) -> str:
    """校验并净化 git 引用名"""
    name = name.strip()
    if not _SAFE_REF_RE.match(name):
        raise ValueError(f"不安全的引用名: {name}")
    if len(name) > 100:
        raise ValueError("引用名过长")
    return name


def _sanitize_hash(h: str) -> str:
    """校验 git commit hash"""
    h = h.strip()
    if not _SAFE_HASH_RE.match(h):
        raise ValueError(f"不安全的 commit hash: {h}")
    return h


# ─── Git 操作工具 ───


def _git_available(proj_dir: Path) -> bool:
    """检查目录是否在 git 仓库中"""
    try:
        r = subprocess.run(
            [_git_cmd, "rev-parse", "--is-inside-work-tree"],
            cwd=str(proj_dir),
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _git_run(args: list[str], proj_dir: Path) -> subprocess.CompletedProcess:
    """在项目目录中执行 git 命令"""
    return subprocess.run(
        ["git"] + args,
        cwd=str(proj_dir),
        capture_output=True, text=True, timeout=15,
    )


def _resolve_proj_git_dir(project_id: str) -> Path:
    """查找项目目录并确认 git 可用"""
    try:
        proj_dir = _find_project(project_id)
    except ProjectNotFound as e:
        raise HTTPException(404, detail={
            "code": "PROJECT_NOT_FOUND",
            "message": str(e),
        })
    except ProjectOperationError:
        raise HTTPException(423, detail={
            "code": "PATH_TRAVERSAL",
            "message": "路径越界",
        })

    if not _git_available(proj_dir):
        raise HTTPException(400, detail={
            "code": "GIT_NOT_AVAILABLE",
            "message": "该项目未启用 Git 版本控制",
            "suggestion": "请在项目目录中执行 git init",
        })

    return proj_dir


# ─── Pydantic 模型 ───


class BranchRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="分支名")


class CheckoutRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="分支名或 commit hash")


class DiffRequest(BaseModel):
    from_hash: str = Field("HEAD", description="起始 commit hash（默认 HEAD）")
    to_hash: str = Field("", description="终点 commit hash（默认工作区）")


class LogEntry(BaseModel):
    hash: str
    date: str
    message: str


class BranchInfo(BaseModel):
    name: str
    current: bool
    hash: str


class GitLogResponse(BaseModel):
    git_available: bool
    entries: list[LogEntry]
    count: int


class GitBranchesResponse(BaseModel):
    git_available: bool
    current: str
    branches: list[BranchInfo]
    count: int


class GitBranchResponse(BaseModel):
    status: str
    branch: str
    message: str


class GitCheckoutResponse(BaseModel):
    status: str
    reference: str
    message: str


class GitDiffResponse(BaseModel):
    git_available: bool
    diff: str
    diff_length: int
    from_hash: str
    to_hash: str


class GitStatusResponse(BaseModel):
    git_available: bool
    branch: str
    clean: bool
    changes: list[dict]


# ─── 路由 ───


@router.get("/{project_id}/log", response_model=GitLogResponse)
def git_log(
    project_id: str,
    count: int = Query(20, ge=1, le=100, description="返回 commit 数量"),
):
    """查看项目的 git 提交历史"""
    proj_dir = _resolve_proj_git_dir(project_id)

    r = _git_run(
        ["log", f"--max-count={count}",
         "--format=%H|%ai|%s", "--no-color"],
        proj_dir,
    )
    if r.returncode != 0:
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": r.stderr.strip() or "git log 失败",
        })

    entries = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 2)
        if len(parts) >= 3:
            entries.append(LogEntry(
                hash=parts[0],
                date=parts[1],
                message=parts[2],
            ))
        elif len(parts) == 2:
            entries.append(LogEntry(
                hash=parts[0],
                date=parts[1],
                message="",
            ))

    return GitLogResponse(
        git_available=True,
        entries=entries,
        count=len(entries),
    )


@router.post("/{project_id}/branch", response_model=GitBranchResponse)
def git_create_branch(project_id: str, body: BranchRequest):
    """基于当前 HEAD 创建新分支"""
    proj_dir = _resolve_proj_git_dir(project_id)

    try:
        branch_name = _sanitize_ref(body.name)
    except ValueError as e:
        raise HTTPException(400, detail={
            "code": "INVALID_BRANCH_NAME",
            "message": str(e),
        })

    r = _git_run(["branch", branch_name], proj_dir)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "already exists" in err:
            raise HTTPException(409, detail={
                "code": "BRANCH_EXISTS",
                "message": f"分支 '{branch_name}' 已存在",
            })
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": err or "git branch 失败",
        })

    return GitBranchResponse(
        status="created",
        branch=branch_name,
        message=f"分支 '{branch_name}' 创建成功",
    )


@router.post("/{project_id}/checkout", response_model=GitCheckoutResponse)
def git_checkout(project_id: str, body: CheckoutRequest):
    """切换到指定分支或 commit"""
    proj_dir = _resolve_proj_git_dir(project_id)

    try:
        ref = _sanitize_ref(body.name)
    except ValueError as e:
        raise HTTPException(400, detail={
            "code": "INVALID_REF",
            "message": str(e),
        })

    r = _git_run(["checkout", ref], proj_dir)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "did not match any file(s) known to git" in err or "pathspec" in err:
            raise HTTPException(404, detail={
                "code": "REF_NOT_FOUND",
                "message": f"引用不存在: {ref}",
            })
        if "local changes" in err:
            raise HTTPException(409, detail={
                "code": "UNCOMMITTED_CHANGES",
                "message": "工作区有未提交的更改，请先提交或暂存",
                "suggestion": "请先保存当前修改（将自动提交），再切换分支",
            })
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": err or f"git checkout {ref} 失败",
        })

    return GitCheckoutResponse(
        status="ok",
        reference=ref,
        message=f"已切换到 '{ref}'",
    )


@router.get("/{project_id}/branches", response_model=GitBranchesResponse)
def git_list_branches(project_id: str):
    """列出项目的所有分支"""
    proj_dir = _resolve_proj_git_dir(project_id)

    # 获取当前分支名
    r_current = _git_run(["rev-parse", "--abbrev-ref", "HEAD"], proj_dir)
    current_branch = r_current.stdout.strip() if r_current.returncode == 0 else "unknown"

    # 列出所有分支
    r = _git_run(
        ["branch", "--format=%(refname:short)|%(objectname:short)"],
        proj_dir,
    )
    if r.returncode != 0:
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": r.stderr.strip() or "git branch 失败",
        })

    branches = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 1)
        name = parts[0]
        b_hash = parts[1] if len(parts) > 1 else ""
        branches.append(BranchInfo(
            name=name,
            current=(name == current_branch),
            hash=b_hash,
        ))

    return GitBranchesResponse(
        git_available=True,
        current=current_branch,
        branches=branches,
        count=len(branches),
    )


@router.post("/{project_id}/diff", response_model=GitDiffResponse)
def git_diff(project_id: str, body: DiffRequest):
    """比较两次 commit 的差异"""
    proj_dir = _resolve_proj_git_dir(project_id)

    try:
        from_hash = body.from_hash if body.from_hash else "HEAD"
        if from_hash != "HEAD":
            from_hash = _sanitize_hash(from_hash)
        to_hash = body.to_hash if body.to_hash else ""
        if to_hash:
            to_hash = _sanitize_hash(to_hash)
    except ValueError as e:
        raise HTTPException(400, detail={
            "code": "INVALID_HASH",
            "message": str(e),
        })

    args = ["diff"]
    if to_hash:
        args.append(f"{from_hash}..{to_hash}")
    else:
        args.append(from_hash)

    r = _git_run(args, proj_dir)
    if r.returncode != 0:
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": r.stderr.strip() or "git diff 失败",
        })

    return GitDiffResponse(
        git_available=True,
        diff=r.stdout,
        diff_length=len(r.stdout),
        from_hash=from_hash,
        to_hash=to_hash or "(工作区)",
    )


@router.get("/{project_id}/status", response_model=GitStatusResponse)
def git_status(project_id: str):
    """查看项目工作区状态"""
    proj_dir = _resolve_proj_git_dir(project_id)

    # 获取当前分支
    r_current = _git_run(["rev-parse", "--abbrev-ref", "HEAD"], proj_dir)
    current_branch = r_current.stdout.strip() if r_current.returncode == 0 else "unknown"

    # 获取状态
    r = _git_run(["status", "--porcelain"], proj_dir)
    if r.returncode != 0:
        raise HTTPException(500, detail={
            "code": "GIT_ERROR",
            "message": r.stderr.strip() or "git status 失败",
        })

    changes = []
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        xy = line[:2]
        path = line[3:]
        if xy == "??":
            changes.append({"status": "untracked", "path": path})
        elif xy[0] != " ":
            changes.append({"status": "staged", "path": path, "code": xy})
        else:
            changes.append({"status": "modified", "path": path, "code": xy})

    return GitStatusResponse(
        git_available=True,
        branch=current_branch,
        clean=len(changes) == 0,
        changes=changes,
    )
