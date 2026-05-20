"""
统一工具路由 — 参照 MCP 协议实现

三个端点（路径前缀 /api/v1/tools）：
  GET    /api/v1/tools              — 列出所有工具（name+description+inputSchema+context_hint）
  POST   /api/v1/tools/{name}/call  — 调用指定工具（args 参数）
  GET    /api/v1/tools/{name}       — 获取单个工具详情

Harness 增强：
  - 调用前参数预检（Pydantic schema 验证）
  - 调用后结果验证
  - 失败时自动重试 1 次再报错
  - 响应中附加 harness 元数据
  - 运行时统计记录（对接 harness_report）

与 routers/tools.py 共存，后者保持原有 subprocess 白名单路由不变。
"""

from __future__ import annotations

import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from core.tools import get_registry
from core.tool_definitions import register_all_tools
from routers.harness_report import record_call

router = APIRouter(prefix="/tools", tags=["tools-mcp"])


# ─── 启动时注册工具 ───

try:
    register_all_tools()
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"工具注册失败（main 启动后会重试）: {e}")


# ─── Pydantic 模型 ───


class ToolCallRequest(BaseModel):
    args: dict = Field(default_factory=dict, description="工具参数（JSON 对象）")


class ToolSchema(BaseModel):
    name: str
    description: str
    inputSchema: dict
    context_hint: str | None = None


class ToolListResponse(BaseModel):
    tools: list[ToolSchema]
    total: int


class HarnessMeta(BaseModel):
    """Harness 执行元数据"""
    pre_validation: str = Field(..., description="参数预检结果: ok/fail")
    post_validation: str = Field(..., description="结果验证结果: ok/fail")
    retry_count: int = Field(..., description="重试次数: 0/1")
    execution_time_ms: float = Field(..., description="执行耗时（毫秒）")


class ToolCallResponse(BaseModel):
    content: list[dict]
    isError: bool = False
    meta: dict | None = None


# ─── 参数预检 ───


def _validate_against_schema(args: dict, schema: dict) -> tuple[bool, str]:
    """对照 JSON Schema 校验参数

    检查：
      - 必填字段缺失
      - 字段类型（string / number / integer / array / object）
      - enum 枚举取值
    不检查深层嵌套，不做 format 验证。

    Returns:
        (ok, error_msg)  — ok=True 表示校验通过
    """
    if not schema or schema.get("type") != "object":
        return True, ""

    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # 1. 检查必填字段
    for field in required:
        if field not in args:
            return False, f"缺少必填参数: {field}"

    # 2. 检查字段类型和枚举
    for field, value in args.items():
        if field not in properties:
            continue
        prop = properties[field]
        prop_type = prop.get("type", "")

        if prop_type == "string":
            if not isinstance(value, str):
                return False, f"参数 '{field}' 应为字符串，收到 {type(value).__name__}"
        elif prop_type == "number":
            if not isinstance(value, (int, float)):
                return False, f"参数 '{field}' 应为数字，收到 {type(value).__name__}"
        elif prop_type == "integer":
            if not isinstance(value, int):
                return False, f"参数 '{field}' 应为整数，收到 {type(value).__name__}"
        elif prop_type == "boolean":
            if not isinstance(value, bool):
                return False, f"参数 '{field}' 应为布尔值，收到 {type(value).__name__}"
        elif prop_type == "array":
            if not isinstance(value, list):
                return False, f"参数 '{field}' 应为数组，收到 {type(value).__name__}"
            # 数组项类型检查（仅基本类型）
            items_schema = prop.get("items", {})
            items_type = items_schema.get("type", "")
            if items_type and value:
                expected_types = {
                    "string": str,
                    "number": (int, float),
                    "integer": int,
                    "object": dict,
                }
                expected = expected_types.get(items_type)
                if expected:
                    for i, item in enumerate(value):
                        if not isinstance(item, expected):
                            return False, f"参数 '{field}[{i}]' 应为 {items_type}，收到 {type(item).__name__}"
        elif prop_type == "object":
            if not isinstance(value, dict):
                return False, f"参数 '{field}' 应为对象，收到 {type(value).__name__}"

        # 3. 检查 enum
        enum_values = prop.get("enum")
        if enum_values is not None and value not in enum_values:
            return False, f"参数 '{field}' 取值无效，允许值: {', '.join(str(e) for e in enum_values)}"

    return True, ""


# ─── 结果验证 ───


def _validate_result(result: dict) -> tuple[bool, str]:
    """验证工具执行结果的结构完整性

    检查：
      - 结果为 dict
      - 含 content 字段（list）
      - content 非空，每项含 type 和 text

    Returns:
        (ok, error_msg)  — ok=True 表示校验通过
    """
    if not isinstance(result, dict):
        return False, "工具返回值必须是字典"
    if "content" not in result:
        return False, "工具返回值缺少 content 字段"
    content = result["content"]
    if not isinstance(content, list):
        return False, "content 必须是列表"
    if len(content) == 0:
        return False, "content 列表为空"
    for idx, item in enumerate(content):
        if not isinstance(item, dict):
            return False, f"content[{idx}] 必须是字典"
        if "type" not in item:
            return False, f"content[{idx}] 缺少 type 字段"
        if "text" not in item:
            return False, f"content[{idx}] 缺少 text 字段"
        if not isinstance(item["text"], str):
            return False, f"content[{idx}].text 必须是字符串"
    return True, ""


# ─── 执行（含重试） ───


def _execute_with_harness(tool_name: str, args: dict) -> tuple[dict, dict]:
    """执行工具，含预检、执行、后验、重试

    Returns:
        (result, harness_meta)
    """
    registry = get_registry()
    tool = registry.get(tool_name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TOOL_NOT_FOUND",
                "message": f"工具 '{tool_name}' 不存在",
                "suggestion": f"可用工具: {[t.name for t in registry.list_all()]}",
            },
        )

    harness_meta = {
        "pre_validation": "ok",
        "post_validation": "ok",
        "retry_count": 0,
        "execution_time_ms": 0.0,
    }

    # ── 1. 参数预检 ──
    pre_ok, pre_msg = _validate_against_schema(args, tool.inputSchema)
    if not pre_ok:
        harness_meta["pre_validation"] = "fail"
        record_call(tool_name, 0.0, is_error=True)
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PARAM_VALIDATION_ERROR",
                "message": pre_msg,
                "tool": tool_name,
                "harness": harness_meta,
            },
        )

    # ── 2. 首次执行 ──
    start = time.time()
    result = registry.call(tool_name, args)
    elapsed = (time.time() - start) * 1000

    is_error = result.get("isError", False)
    post_ok, post_msg = _validate_result(result)

    # ── 3. 后验失败或执行出错 → 重试 1 次 ──
    if is_error or not post_ok:
        harness_meta["retry_count"] = 1
        start = time.time()
        result = registry.call(tool_name, args)
        elapsed = (time.time() - start) * 1000

        is_error = result.get("isError", False)
        post_ok, post_msg = _validate_result(result)
        if not post_ok:
            harness_meta["post_validation"] = "fail"
        else:
            harness_meta["post_validation"] = "ok"

    # ── 4. 记录统计 ──
    harness_meta["execution_time_ms"] = round(elapsed, 2)
    record_call(tool_name, elapsed, is_error=is_error)

    return result, harness_meta


# ─── 路由 ───


@router.get("", response_model=ToolListResponse)
def list_tools():
    """列出所有已注册工具（name + description + inputSchema + context_hint）"""
    registry = get_registry()
    tools = []
    for t in registry.list_all():
        tdict = t.to_dict()
        tools.append(ToolSchema(
            name=tdict["name"],
            description=tdict["description"],
            inputSchema=tdict["inputSchema"],
            context_hint=tdict.get("context_hint"),
        ))
    return ToolListResponse(tools=tools, total=len(tools))


@router.get("/{name}", response_model=ToolSchema)
def get_tool(name: str):
    """获取单个工具的完整信息"""
    registry = get_registry()
    tool = registry.get(name)
    if tool is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TOOL_NOT_FOUND",
                "message": f"工具 '{name}' 不存在",
                "suggestion": f"可用工具: {[t.name for t in registry.list_all()]}",
            },
        )
    tdict = tool.to_dict()
    return ToolSchema(
        name=tdict["name"],
        description=tdict["description"],
        inputSchema=tdict["inputSchema"],
        context_hint=tdict.get("context_hint"),
    )


@router.post("/{name}/call", response_model=ToolCallResponse)
def call_tool(name: str, body: ToolCallRequest):
    """调用指定工具并返回结果

    Harness 增强：
      - 参数预检 → pre_validation
      - 结果后验 → post_validation
      - 失败重试 1 次 → retry_count
      - 执行耗时 → execution_time_ms
      以上均写入 meta.harness 字段。
    """
    result, harness_meta = _execute_with_harness(name, body.args)

    is_error = result.get("isError", False)
    content = result.get("content", [])
    tool_meta = result.get("meta")

    # 构建最终 meta（工具自身 meta + harness 信息）
    final_meta: dict = {}
    if tool_meta:
        final_meta.update(tool_meta)
    final_meta["harness"] = harness_meta

    if is_error:
        error_text = content[0]["text"] if content else "未知错误"
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TOOL_EXECUTION_ERROR",
                "message": error_text,
                "tool": name,
                "harness": harness_meta,
            },
        )

    return ToolCallResponse(content=content, isError=False, meta=final_meta)
