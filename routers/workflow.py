"""
工作流状态追踪路由 — 9 阶段写作流程

GET    /workflow                     — 获取当前项目工作流状态
PUT    /workflow                     — 更新工作流阶段
POST   /workflow/checklist/{stage}   — 更新某阶段的检查项完成状态
GET    /workflow/history             — 查看近期工作流变更记录

路径前缀 /api/v1/workflow

阶段枚举：
  0 未开始 → 1 写前分析 → 2 写作 → 3 自检清单 → 3.3 自动审查
  → 3.5 文笔润色 → 4 修订 → 5 章末元数据 → 6 知识库同步 → 7 交付
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/workflow", tags=["workflow"])
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / "workflow_state.json"
HISTORY_FILE = DATA_DIR / "workflow_history.json"

# ─── 阶段定义 ───

STAGES = {
    0: {"name": "未开始", "blocking": False, "has_checklist": False},
    1: {"name": "写前分析", "blocking": False, "has_checklist": False},
    2: {"name": "写作", "blocking": False, "has_checklist": False},
    3: {"name": "自检清单", "blocking": True, "has_checklist": True},
    3.3: {"name": "自动审查", "blocking": False, "has_checklist": False},
    3.5: {"name": "文笔润色", "blocking": False, "has_checklist": False},
    4: {"name": "修订", "blocking": False, "has_checklist": False},
    5: {"name": "章末元数据", "blocking": False, "has_checklist": False},
    6: {"name": "知识库同步", "blocking": False, "has_checklist": True},
    7: {"name": "交付", "blocking": False, "has_checklist": False},
}

# 自检清单项目
CHECKLIST_ITEMS = [
    "场景首尾测试",
    "展示不告诉测试",
    "\"他心想\"压强测试",
    "字数2000+",
    "密度≤6",
    "\"不是A是B\"≤2",
    "\"他\"≤15/千字",
]

# 知识库同步项
SYNC_ITEMS = [
    "伏笔与线索追踪表",
    "时间线表",
    "人物档案与关系网",
    "物品列表",
    "情节脉络",
    "全卷章节细纲",
]

# 升序阶段键列表（用于自动推进）
STAGE_KEYS = sorted(STAGES.keys())

# ─── 默认状态 ───


def _default_stages_dict() -> dict:
    """生成默认的 stages 字典"""
    stages = {}
    for sid, info in STAGES.items():
        entry = {
            "name": info["name"],
            "completed": False,
            "completed_at": None,
        }
        if info["has_checklist"]:
            if sid == 3:
                entry["checklist"] = {item: False for item in CHECKLIST_ITEMS}
            elif sid == 6:
                entry["checklist"] = {item: False for item in SYNC_ITEMS}
        stages[str(sid)] = entry
    return stages


def _default_state() -> dict:
    return {
        "project": "tales-of-tera",
        "active_chapter": None,
        "current_stage": 0,
        "current_stage_name": "未开始",
        "stages": _default_stages_dict(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ─── 持久化 ───


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            # 确保所有阶段都存在（可能比默认少）
            stages = _default_stages_dict()
            stages.update(data.get("stages", {}))
            data["stages"] = stages
            return data
        except (json.JSONDecodeError, IOError):
            pass
    state = _default_state()
    _save_state(state)
    return state


def _save_state(state: dict):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_history(history: list):
    # 保留最近 100 条
    if len(history) > 100:
        history = history[-100:]
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _append_history(entry: dict):
    history = _load_history()
    history.append(entry)
    _save_history(history)


# ─── 阶段推进逻辑 ───


def _get_stage_index(stage_id: float) -> int:
    """获取阶段在有序列表中的索引"""
    for i, key in enumerate(STAGE_KEYS):
        if key == stage_id:
            return i
    raise ValueError(f"无效的阶段: {stage_id}")


def _can_advance_to(state: dict, target_stage: float) -> tuple[bool, str | None]:
    """检查是否能推进到目标阶段，返回 (允许, 阻塞原因)"""
    target_idx = _get_stage_index(target_stage)
    current_idx = _get_stage_index(state["current_stage"])

    # 不能后退
    if target_idx < current_idx:
        return False, f"不能从阶段 {state['current_stage']} 回退到 {target_stage}"

    # 可以前进到下一个相邻阶段
    if target_idx > current_idx + 1:
        return False, f"不能跨阶段前进：当前 {state['current_stage']}，目标 {target_stage}，需先经过中间阶段"

    # 如果进入的是阻塞阶段，检查前置条件
    prev_key = STAGE_KEYS[current_idx] if current_idx > 0 else None
    if target_stage == 3:
        # 进入自检清单：写作阶段必须标记为已完成
        stage_2 = state["stages"].get("2", {})
        if not stage_2.get("completed", False):
            return False, "写作阶段尚未完成，无法进入自检清单"
    elif target_stage == 4:
        # 进入修订：自检清单（含审查和润色）必须完成
        stage_3 = state["stages"].get("3", {})
        stage_33 = state["stages"].get("3.3", {})
        stage_35 = state["stages"].get("3.5", {})
        if not (stage_3.get("completed", False) and stage_33.get("completed", False) and stage_35.get("completed", False)):
            return False, "自检阶段（自检清单/自动审查/文笔润色）未全部完成"

    return True, None


# ─── Pydantic 模型 ───


class StageInfo(BaseModel):
    name: str
    completed: bool
    completed_at: str | None = None
    checklist: dict[str, bool] | None = None


class WorkflowStateResponse(BaseModel):
    project: str
    active_chapter: str | None
    current_stage: int | float
    current_stage_name: str
    stages: dict[str, StageInfo]
    created_at: str
    updated_at: str


class WorkflowUpdate(BaseModel):
    current_stage: int | float | None = Field(None, description="目标阶段编号")
    active_chapter: str | None = Field(None, description="当前处理的章节文件名")
    completed_stage: int | float | None = Field(None, description="标记某个阶段为已完成")


class ChecklistUpdate(BaseModel):
    item: str = Field(..., description="检查项名称")
    completed: bool = Field(..., description="是否通过")


class HistoryEntry(BaseModel):
    action: str
    stage: int | float | None = None
    stage_name: str | None = None
    detail: str | None = None
    timestamp: str


# ─── 路由 ───


def _serialize_stages(stages: dict) -> dict[str, StageInfo]:
    """序列化 stages 字典为 Pydantic 模型"""
    result = {}
    for sid, info in stages.items():
        # 转换 checklists 格式
        cl = info.get("checklist") if info.get("checklist") else None
        result[sid] = StageInfo(
            name=info["name"],
            completed=info.get("completed", False),
            completed_at=info.get("completed_at"),
            checklist=cl,
        )
    return result


@router.get("", response_model=WorkflowStateResponse)
def get_workflow():
    """获取当前项目的工作流状态"""
    state = _load_state()
    stages = _serialize_stages(state["stages"])
    return WorkflowStateResponse(
        project=state["project"],
        active_chapter=state.get("active_chapter"),
        current_stage=state["current_stage"],
        current_stage_name=state["current_stage_name"],
        stages=stages,
        created_at=state["created_at"],
        updated_at=state["updated_at"],
    )


@router.put("")
def update_workflow(body: WorkflowUpdate):
    """更新工作流阶段"""
    state = _load_state()
    now = datetime.now(timezone.utc).isoformat()
    changes = []

    # 更新 active_chapter
    if body.active_chapter is not None:
        old = state.get("active_chapter")
        state["active_chapter"] = body.active_chapter
        if old != body.active_chapter:
            changes.append(f"当前章节: {old} → {body.active_chapter}")

    # 推进阶段
    if body.current_stage is not None:
        target = float(body.current_stage)
        if target not in STAGES:
            raise HTTPException(400, detail={
                "code": "INVALID_STAGE",
                "message": f"无效的阶段编号: {target}",
                "detail": f"可用阶段: {list(STAGES.keys())}",
            })

        # 如果是回退，检查是否允许
        allowed, reason = _can_advance_to(state, target)
        if not allowed:
            raise HTTPException(400, detail={
                "code": "STAGE_BLOCKED",
                "message": f"无法推进到阶段 {target}",
                "detail": reason,
            })

        old_stage = state["current_stage"]
        state["current_stage"] = target
        state["current_stage_name"] = STAGES[target]["name"]
        changes.append(f"阶段: {old_stage} → {target} ({STAGES[target]['name']})")

    # 标记阶段完成
    if body.completed_stage is not None:
        cs = str(body.completed_stage)
        if cs in state["stages"]:
            if not state["stages"][cs].get("completed", False):
                state["stages"][cs]["completed"] = True
                state["stages"][cs]["completed_at"] = now
                changes.append(f"阶段 {cs} ({STAGES.get(float(cs), {}).get('name', '?')}) 标记为已完成")

                # 自动推进到下一阶段（如果是非阻塞阶段）
                current_idx = _get_stage_index(float(cs))
                if current_idx + 1 < len(STAGE_KEYS):
                    next_key = STAGE_KEYS[current_idx + 1]
                    if not STAGES[next_key]["blocking"]:
                        state["current_stage"] = next_key
                        state["current_stage_name"] = STAGES[next_key]["name"]
                        changes.append(f"自动推进到阶段 {next_key} ({STAGES[next_key]['name']})")

    if not changes:
        return {"status": "ok", "message": "无变更", "changes": []}

    state["updated_at"] = now
    _save_state(state)

    # 记录历史
    _append_history({
        "action": "update",
        "stage": state["current_stage"],
        "stage_name": state["current_stage_name"],
        "detail": "; ".join(changes),
        "timestamp": now,
    })

    return {
        "status": "ok",
        "current_stage": state["current_stage"],
        "current_stage_name": state["current_stage_name"],
        "changes": changes,
    }


@router.post("/checklist/{stage}")
def update_checklist(stage: str, body: ChecklistUpdate):
    """更新某阶段的检查项完成状态"""
    state = _load_state()
    now = datetime.now(timezone.utc).isoformat()

    # 校验阶段
    stage_f = float(stage)
    if stage_f not in STAGES:
        raise HTTPException(400, detail={
            "code": "INVALID_STAGE",
            "message": f"无效的阶段编号: {stage}",
        })

    stage_key = str(stage_f)
    stage_data = state["stages"].get(stage_key)
    if not stage_data:
        raise HTTPException(404, detail={
            "code": "STAGE_NOT_FOUND",
            "message": f"阶段 {stage} 状态数据不存在",
        })

    checklist = stage_data.get("checklist")
    if checklist is None:
        raise HTTPException(400, detail={
            "code": "NO_CHECKLIST",
            "message": f"阶段 {stage} ({STAGES[stage_f]['name']}) 没有检查清单",
        })

    if body.item not in checklist:
        # 检查阶段 3 的自检清单
        if stage_f == 3 and body.item not in CHECKLIST_ITEMS:
            raise HTTPException(400, detail={
                "code": "INVALID_CHECKLIST_ITEM",
                "message": f"无效的检查项: '{body.item}'",
                "detail": f"自检清单项目: {CHECKLIST_ITEMS}",
            })
        # 检查阶段 6 的同步项
        if stage_f == 6 and body.item not in SYNC_ITEMS:
            raise HTTPException(400, detail={
                "code": "INVALID_CHECKLIST_ITEM",
                "message": f"无效的同步项: '{body.item}'",
                "detail": f"同步项: {SYNC_ITEMS}",
            })
        # 如果是新项目，允许添加
        checklist[body.item] = body.completed
    else:
        checklist[body.item] = body.completed

    # 检查是否所有 checklist 项都完成了
    all_done = all(checklist.values())
    if all_done and not stage_data.get("completed", False):
        stage_data["completed"] = True
        stage_data["completed_at"] = now

        # 自动推进（如果非阻塞）
        if not STAGES[stage_f]["blocking"]:
            current_idx = _get_stage_index(stage_f)
            if current_idx + 1 < len(STAGE_KEYS):
                next_key = STAGE_KEYS[current_idx + 1]
                state["current_stage"] = next_key
                state["current_stage_name"] = STAGES[next_key]["name"]
        else:
            # 阻塞阶段（自检清单）完成后不自动推进，等待用户手动
            pass
    elif not all_done and stage_data.get("completed", False):
        # 如果取消了一个完成项，移除阶段完成标记
        stage_data["completed"] = False
        stage_data["completed_at"] = None

    state["stages"][stage_key] = stage_data
    _save_state(state)

    _append_history({
        "action": "checklist_update",
        "stage": stage_f,
        "stage_name": STAGES[stage_f]["name"],
        "detail": f"{body.item}: {'✅' if body.completed else '⬜'}",
        "timestamp": now,
    })

    return {
        "status": "ok",
        "stage": stage_f,
        "item": body.item,
        "completed": body.completed,
        "all_checklist_done": all_done,
        "stage_completed": stage_data.get("completed", False),
    }


@router.get("/history")
def get_workflow_history():
    """查看近期工作流变更记录"""
    history = _load_history()
    state = _load_state()
    return {
        "history": history,
        "count": len(history),
        "current_stage": state["current_stage"],
        "current_stage_name": state["current_stage_name"],
    }
