"""
自主写作 Agent 路由 — Agentic Writing Workflow

POST /api/v1/agent/write  — 运行写作 Agent

请求体：
  {
    "task": "帮我写下一章，关于沈默进入龙门",
    "project_id": "xxx",
    "provider": "deepseek"  // 可选
  }

响应：
  {
    "plan": [{"action": "read_chapter", "params": {...}}, ...],
    "result": "生成的章节内容",
    "changes": ["已读取参考章节", "初稿完成", ...],
    "duration_ms": 12345,
    "filename": "第31章_新的开始.md",
    "steps_detail": [...]
  }

路径前缀 /api/v1/agent
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])


class WriteRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=1000, description="用户写作需求描述")
    project_id: str = Field(..., min_length=1, description="项目 ID")
    provider: str = Field(default="deepseek", description="AI provider: deepseek / openai / claude")


class AgentStepInfo(BaseModel):
    action: str
    params: dict = Field(default_factory=dict)


class StepDetail(BaseModel):
    action: str
    status: str
    result_summary: str | None = None
    error: str | None = None


class WriteResponse(BaseModel):
    plan: list[AgentStepInfo]
    result: str
    changes: list[str]
    duration_ms: int
    filename: str | None = None
    steps_detail: list[StepDetail] = Field(default_factory=list)


@router.post("/write", response_model=WriteResponse)
async def agent_write(body: WriteRequest):
    """运行写作 Agent，根据用户需求自动完成章节写作"""
    try:
        from core.writing_agent import WritingAgent

        agent = WritingAgent(
            project_id=body.project_id,
            provider=body.provider,
        )
        result = await agent.run(body.task)

        return WriteResponse(
            plan=[AgentStepInfo(**s) for s in result["plan"]],
            result=result["result"],
            changes=result["changes"],
            duration_ms=result["duration_ms"],
            filename=result.get("filename"),
            steps_detail=[StepDetail(**s) for s in result.get("steps_detail", [])],
        )

    except FileNotFoundError as e:
        raise HTTPException(404, detail={
            "code": "PROJECT_NOT_FOUND",
            "message": str(e),
        })
    except ValueError as e:
        raise HTTPException(400, detail={
            "code": "INVALID_PARAMETER",
            "message": str(e),
        })
    except RuntimeError as e:
        raise HTTPException(503, detail={
            "code": "AGENT_ERROR",
            "message": str(e),
        })
    except Exception as e:
        raise HTTPException(500, detail={
            "code": "INTERNAL_ERROR",
            "message": f"Agent 执行异常: {type(e).__name__}: {str(e)[:200]}",
        })
