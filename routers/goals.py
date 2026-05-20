"""
写作目标追踪 API

管理每个项目的写作目标，包括每日打卡和进度追踪。

GET    /goals                  — 获取项目目标列表（?project_id=xxx）
POST   /goals                  — 创建目标
PUT    /goals/{id}             — 更新目标进度（?project_id=xxx）
GET    /goals/stats            — 每日统计（?project_id=xxx）

数据存储：goals/{project_id}.json
"""

import uuid
import json
from pathlib import Path
from datetime import datetime, date, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from core.enums import GoalStatus

router = APIRouter(prefix="/goals", tags=["goals"])
BASE = Path(__file__).resolve().parent.parent
GOALS_DIR = BASE / "goals"
GOALS_DIR.mkdir(exist_ok=True)

ALLOWED_STATUSES = {s.value for s in GoalStatus}


# ─── 路径安全 ───


class GoalPathError(Exception):
    pass


def _goals_file(project_id: str) -> Path:
    safe = Path(project_id).name
    if safe != project_id:
        raise GoalPathError(f"无效的 project_id: {project_id}")
    target = (GOALS_DIR / safe).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(GOALS_DIR.resolve())):
        raise GoalPathError("路径越界")
    return target


def _load_goals(project_id: str) -> list[dict]:
    target = _goals_file(project_id)
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def _save_goals(project_id: str, goals: list[dict]):
    target = _goals_file(project_id)
    target.write_text(json.dumps(goals, ensure_ascii=False, indent=2), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


# ─── Pydantic 模型 ───


class GoalCreate(BaseModel):
    project_id: str = Field(..., min_length=1, description="项目 ID")
    title: str = Field(..., min_length=1, max_length=200, description="目标标题")
    target_word_count: int = Field(..., gt=0, description="目标字数")
    deadline: str = Field(..., description="截止日期 (YYYY-MM-DD)")

    @field_validator("deadline")
    @classmethod
    def validate_deadline(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("deadline 格式必须为 YYYY-MM-DD")
        return v


class GoalUpdate(BaseModel):
    current_word_count: int | None = Field(default=None, ge=0, description="当前已写字数")
    status: GoalStatus | None = Field(default=None, description="目标状态")
    check_in: bool = Field(default=False, description="今日打卡")


class GoalResponse(BaseModel):
    id: str
    title: str
    target_word_count: int
    deadline: str
    current_word_count: int = 0
    status: GoalStatus = GoalStatus.ACTIVE
    check_ins: list[str] = []
    progress_pct: float = 0.0
    created_at: str = ""
    updated_at: str = ""


class GoalStatsResponse(BaseModel):
    total_goals: int = 0
    active_goals: int = 0
    completed_goals: int = 0
    total_target_words: int = 0
    total_current_words: int = 0
    today_check_in: bool = False
    consecutive_days: int = 0
    days_until_deadline: int = 0


# ─── 帮助函数 ───


def _build_response(goal: dict) -> dict:
    total = goal.get("target_word_count", 1)
    current = goal.get("current_word_count", 0)
    pct = round(min(current / total * 100, 100), 1)
    return {
        "id": goal["id"],
        "title": goal["title"],
        "target_word_count": goal["target_word_count"],
        "deadline": goal["deadline"],
        "current_word_count": current,
        "status": goal.get("status", "active"),
        "check_ins": goal.get("check_ins", []),
        "progress_pct": pct,
        "created_at": goal.get("created_at", ""),
        "updated_at": goal.get("updated_at", ""),
    }


def _compute_consecutive_days(check_ins: list[str]) -> int:
    """从 check_ins 列表中计算连续打卡天数"""
    if not check_ins:
        return 0
    sorted_days = sorted(set(check_ins), reverse=True)
    if sorted_days[0] != _today():
        return 0
    count = 1
    for i in range(1, len(sorted_days)):
        prev = datetime.strptime(sorted_days[i - 1], "%Y-%m-%d")
        curr = datetime.strptime(sorted_days[i], "%Y-%m-%d")
        if (prev - curr).days == 1:
            count += 1
        else:
            break
    return count


# ─── API 端点 ───


@router.get("", response_model=list[GoalResponse])
async def list_goals(project_id: str = Query(..., description="项目 ID")):
    """获取当前项目所有写作目标"""
    goals = _load_goals(project_id)
    return [_build_response(g) for g in goals]


@router.post("", response_model=GoalResponse, status_code=201)
async def create_goal(body: GoalCreate):
    """创建新写作目标"""
    goals = _load_goals(body.project_id)
    new_goal = {
        "id": uuid.uuid4().hex[:12],
        "title": body.title,
        "target_word_count": body.target_word_count,
        "deadline": body.deadline,
        "current_word_count": 0,
        "status": "active",
        "check_ins": [],
        "created_at": _now(),
        "updated_at": _now(),
    }
    goals.append(new_goal)
    _save_goals(body.project_id, goals)
    return _build_response(new_goal)


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: str, body: GoalUpdate,
                       project_id: str = Query(..., description="项目 ID")):
    """更新写作目标进度"""
    goals = _load_goals(project_id)
    idx = next((i for i, g in enumerate(goals) if g["id"] == goal_id), -1)
    if idx == -1:
        raise HTTPException(status_code=404, detail=f"目标 '{goal_id}' 不存在")

    goal = goals[idx]

    if body.current_word_count is not None:
        goal["current_word_count"] = body.current_word_count
    if body.status is not None:
        goal["status"] = body.status
    if body.check_in:
        today = _today()
        check_ins = goal.setdefault("check_ins", [])
        if today not in check_ins:
            check_ins.append(today)

    goal["updated_at"] = _now()
    goals[idx] = goal
    _save_goals(project_id, goals)
    return _build_response(goal)


@router.get("/stats", response_model=GoalStatsResponse)
async def goal_stats(project_id: str = Query(..., description="项目 ID")):
    """获取每日统计摘要"""
    goals = _load_goals(project_id)
    today = _today()

    all_check_ins: list[str] = []
    total_target = 0
    total_current = 0
    active = 0
    completed = 0

    for g in goals:
        total_target += g.get("target_word_count", 0)
        total_current += g.get("current_word_count", 0)
        all_check_ins.extend(g.get("check_ins", []))
        status = g.get("status", "active")
        if status == "active":
            active += 1
        elif status == "completed":
            completed += 1

    today_checked = today in all_check_ins
    consecutive = _compute_consecutive_days(all_check_ins)

    # 取最近目标的最早 deadline 计算剩余天数
    active_goals = [g for g in goals if g.get("status") == "active"]
    earliest_deadline = None
    days_left = 0
    if active_goals:
        deadlines = sorted(g["deadline"] for g in active_goals if "deadline" in g)
        if deadlines:
            earliest_deadline = deadlines[0]
            dl = datetime.strptime(earliest_deadline, "%Y-%m-%d").date()
            days_left = max((dl - date.today()).days, 0)

    return GoalStatsResponse(
        total_goals=len(goals),
        active_goals=active,
        completed_goals=completed,
        total_target_words=total_target,
        total_current_words=total_current,
        today_check_in=today_checked,
        consecutive_days=consecutive,
        days_until_deadline=days_left,
    )
