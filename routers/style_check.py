"""
写作风格检查路由（基于 WritingRule 插件系统）

POST /api/v1/style/check  — 对文本执行写作风格检查
GET  /api/v1/style/rules  — 列出所有可用的检查规则

路径前缀 /api/v1/style
"""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.writing_rules import WritingIssue, registry

router = APIRouter(prefix="/style", tags=["style"])


class StyleCheckBody(BaseModel):
    text: str = Field(..., min_length=1, description="要检查的文本内容")
    rules: list[str] | None = Field(
        None,
        description="要启用的规则列表，不传或 null 表示全部启用。"
        "可选值见 GET /api/v1/style/rules",
    )


def _issue_to_old_format(issue: WritingIssue) -> dict:
    """将 WritingIssue 转换为旧版 CheckResult 格式以保持接口不变"""
    d = asdict(issue)
    d["rule"] = d.pop("rule_name")
    return d


@router.post("/check")
def style_check(body: StyleCheckBody):
    """对文本执行写作风格检查"""
    if not body.text.strip():
        raise HTTPException(400, detail={
            "code": "EMPTY_TEXT",
            "message": "检查文本不能为空",
        })

    # 校验规则名称
    valid_rules = {r["name"] for r in registry.list()}
    if body.rules is not None:
        invalid = set(body.rules) - valid_rules
        if invalid:
            raise HTTPException(400, detail={
                "code": "INVALID_RULES",
                "message": f"未知的规则名称: {', '.join(sorted(invalid))}",
                "valid_rules": sorted(valid_rules),
            })

    issues = registry.check_all(text=body.text, rule_names=body.rules)
    results = [_issue_to_old_format(issue) for issue in issues]

    return {
        "status": "ok",
        "total_issues": len(results),
        "rules_applied": body.rules or sorted(valid_rules),
        "results": results,
    }


@router.get("/rules")
def list_rules():
    """列出所有可用的检查规则"""
    return {
        "status": "ok",
        "rules": registry.list(),
    }
