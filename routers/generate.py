"""
命名生成器路由

POST /api/v1/generate/name  — 根据类型和风格生成名字建议

架构：
  1. 检查是否有已配置的 chat API Key
  2. 有 → 调用非流式 chat API 生成名字
  3. 无 → 返回预设的中文名字列表作为降级
"""

import json
import logging
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generate", tags=["generate"])
BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"

# ─── 延迟导入 KeyManager ───

_key_manager_instance = None


def _get_key_manager():
    global _key_manager_instance
    if _key_manager_instance is not None:
        return _key_manager_instance
    try:
        from services.key_manager import KeyManager
        _key_manager_instance = KeyManager(storage_path=DATA_DIR / "keys.json")
        return _key_manager_instance
    except ImportError:
        return None


# ─── Provider 配置（精简版，仅需非流式 chat） ───

PROVIDER_CONFIGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "default_model": "gpt-5.4",
        "chat_endpoint": "/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "claude": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-20250514",
        "chat_endpoint": "/v1/messages",
        "auth_header": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
    },
}


# ─── 请求 / 响应模型 ───

NameType = Literal["character", "place", "organization"]
NameStyle = Literal["eastern", "western", "fantasy"]


class NameGenerateRequest(BaseModel):
    type: NameType = Field(
        "character",
        description="命名类型: character(角色) / place(地点) / organization(组织)",
    )
    style: NameStyle = Field(
        "eastern",
        description="风格取向: eastern(东方) / western(西方) / fantasy(奇幻)",
    )
    count: int = Field(
        5,
        ge=1,
        le=20,
        description="生成名字数量 (1-20)",
    )
    project_id: str | None = Field(
        None,
        description="关联项目 ID（可选，用于上下文增强）",
    )


class NameGenerateResponse(BaseModel):
    names: list[str]
    type: str
    style: str
    source: str = "ai"  # "ai" or "fallback"


# ─── 预设降级名字库 ───

FALLBACK_NAMES: dict[str, dict[str, list[dict[str, str]]]] = {
    "character": {
        "eastern": [
            {"name": "沈默", "note": "沉默寡言，却有雷霆手段"},
            {"name": "林渊", "note": "如林之深，如渊之静"},
            {"name": "江澈", "note": "江水清澈，心性通透"},
            {"name": "叶知秋", "note": "一叶知秋，见微知著"},
            {"name": "陆沉舟", "note": "沉舟侧畔，破浪前行"},
            {"name": "白露", "note": "露水般清冷，转瞬即逝的存在"},
            {"name": "谢云鹤", "note": "云中白鹤，超然物外"},
            {"name": "苏幕遮", "note": "遮蔽即守护，面冷心热"},
        ],
        "western": [
            {"name": "Aldric Vance", "note": "古老血统的继承者，理智而冷酷"},
            {"name": "Seraphina Cole", "note": "燃烧的智慧，烈火般的热情"},
            {"name": "Orion Blackwood", "note": "行走于黑暗，却为光明而战"},
            {"name": "Ivy Rosethorn", "note": "带刺的玫瑰，温柔下的锋芒"},
            {"name": "Draven Ashford", "note": "灰烬中重生，不败的战士"},
            {"name": "Celeste Moonshadow", "note": "月影下的预言者"},
            {"name": "Magnus Ironheart", "note": "钢铁之心，不可动摇的意志"},
            {"name": "Elara Swiftwind", "note": "如风般迅捷，自由的灵魂"},
        ],
        "fantasy": [
            {"name": "雾凇", "note": "冰雾凝结之形，虚幻而致命"},
            {"name": "烬羽", "note": "灰烬中燃起的羽毛，不死鸟的眷族"},
            {"name": "霜瞳", "note": "被远古寒冰祝福的见证者"},
            {"name": "织梦者·诺恩", "note": "编织现实与梦境的存在"},
            {"name": "墨鳞", "note": "深渊之鳞，沉默的守护者"},
            {"name": "弦月", "note": "残缺即完美，弯月下的流浪者"},
            {"name": "赤脊", "note": "背负烈焰烙印的战士"},
            {"name": "风吟", "note": "风之低语者，无人知其来历"},
        ],
    },
    "place": {
        "eastern": [
            {"name": "云深不知处", "note": "云雾缭绕的隐秘之地"},
            {"name": "听雨轩", "note": "檐下听雨，专为旅人而设"},
            {"name": "落星谷", "note": "星辰坠落之处，灵力充沛"},
            {"name": "青石板街", "note": "蜿蜒的老街，藏着无数故事"},
            {"name": "暮雪山庄", "note": "终年积雪的避世之所"},
        ],
        "western": [
            {"name": "Silverpine Haven", "note": "银松环绕的避风港"},
            {"name": "Crimson Dunes", "note": "血色沙丘，古战场的遗迹"},
            {"name": "Whisperwind Harbor", "note": "风语港，商船与秘密的集散地"},
            {"name": "Ironforge Gate", "note": "铁炉堡之门，坚不可摧的要塞"},
            {"name": "Thornwall Abbey", "note": "荆棘墙修道院，知识的孤岛"},
        ],
        "fantasy": [
            {"name": "浮空岛·辰辉", "note": "漂浮于云海之上的魔法岛屿"},
            {"name": "幽暗裂隙", "note": "大地裂开的伤疤，通向未知"},
            {"name": "星辉图书馆", "note": "收藏着世界所有记忆的场所"},
            {"name": "龙骨荒漠", "note": "远古巨龙的葬身之地"},
            {"name": "镜湖", "note": "倒映的不是天空，而是另一个世界"},
        ],
    },
    "organization": {
        "eastern": [
            {"name": "碧落阁", "note": "以天道为榜，以秩序为剑"},
            {"name": "听风楼", "note": "天下情报，尽在耳中"},
            {"name": "墨守轩", "note": "守旧派学者的堡垒"},
            {"name": "赤焰营", "note": "烈火般的战团"},
            {"name": "青鸾卫", "note": "皇室暗中培植的精英卫队"},
        ],
        "western": [
            {"name": "The Obsidian Circle", "note": "黑曜石之环，操纵阴影的秘会"},
            {"name": "Order of the Gilded Hand", "note": "镀金之手，商人与贵族的联盟"},
            {"name": "Silver Quill Society", "note": "银羽笔会，学者与抄写员的公会"},
            {"name": "The Crimson Accord", "note": "血色盟约，佣兵与自由战士的联合"},
            {"name": "Solaris Consortium", "note": "索拉里斯财团，光明背后的金主"},
        ],
        "fantasy": [
            {"name": "星痕议会", "note": "以星辰为印记的法师结社"},
            {"name": "灰烬兄弟会", "note": "从毁灭中重生的秘密组织"},
            {"name": "永夜守望", "note": "守护世界免于永夜降临的古老同盟"},
            {"name": "织法者协会", "note": "编织与解构魔法的研究者"},
            {"name": "渊底之声", "note": "来自深渊的崇拜者集会"},
        ],
    },
}


# ─── 提示词模板 ───

def _build_prompt(
    type_name: str,
    style: str,
    count: int,
    project_id: str | None = None,
) -> str:
    """构建 AI 提示词"""
    type_labels = {
        "character": "角色",
        "place": "地点",
        "organization": "组织",
    }
    style_labels = {
        "eastern": "东方古典",
        "western": "西方",
        "fantasy": "奇幻",
    }

    cn_type = type_labels.get(type_name, type_name)
    cn_style = style_labels.get(style, style)

    prompt = (
        f"生成{count}个{cn_style}风格的{cn_type}名字，"
        f"每个名字后跟一句简短说明。"
        f"用JSON格式返回，格式为："
        f'{{"names":[{{"name":"名字","note":"说明"}}]}}'
    )

    if project_id:
        prompt += f"\n参考项目上下文: {project_id}"

    return prompt


# ─── 非流式 chat API 调用 ───

async def _call_name_api(
    prompt: str,
    count: int,
    type_name: str,
    style: str,
) -> NameGenerateResponse:
    """调用已配置的 chat API 生成名字，失败则降级"""
    km = _get_key_manager()
    if km is None:
        return _fallback_names(type_name, style, count)

    # 尝试每个已配置的 provider
    providers = km.list_providers()
    if not providers:
        return _fallback_names(type_name, style, count)

    # 优先用 deepseek, 其次用第一个可用 provider
    preferred_order = ["deepseek", "openai", "claude"]
    chosen_provider = None
    for name in preferred_order:
        if name in providers:
            chosen_provider = name
            break
    if not chosen_provider:
        chosen_provider = list(providers.keys())[0]

    try:
        api_key = km.get_key(chosen_provider)
        cfg = km.get_config(chosen_provider) or {}
        provider_cfg = PROVIDER_CONFIGS.get(chosen_provider)

        if not api_key or not provider_cfg:
            return _fallback_names(type_name, style, count)

        base_url = cfg.get("endpoint") or provider_cfg["base_url"]
        model = cfg.get("model") or provider_cfg["default_model"]
        endpoint = provider_cfg["chat_endpoint"]
        headers = provider_cfg["auth_header"](api_key)
        headers["Content-Type"] = "application/json"

        url = base_url.rstrip("/") + endpoint

        # 构建 payload
        if "x-api-key" in headers:
            # Anthropic 格式
            payload = {
                "model": model,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            # OpenAI 兼容格式
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的命名顾问。生成名字时考虑文化背景、音韵美感和寓意。只返回JSON，不输出其他内容。",
                    },
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1024,
                "temperature": 0.8,
            }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            logger.warning(
                f"Name API call failed: {resp.status_code} - {resp.text[:200]}"
            )
            return _fallback_names(type_name, style, count)

        data = resp.json()

        # 解析响应
        if "x-api-key" in headers:
            # Anthropic 格式
            content = data.get("content", [{}])[0].get("text", "")
        else:
            content = data["choices"][0]["message"]["content"]

        # 尝试从 JSON 中提取
        names = _parse_name_json(content, count)
        if names:
            return NameGenerateResponse(
                names=names,
                type=type_name,
                style=style,
                source="ai",
            )

        # JSON 解析失败，用行解析
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        parsed = []
        for line in lines[:count]:
            # 去掉序号和可能的引号
            clean = line.lstrip("0123456789.、- \t\"'")
            # 取第一个词或中文字符串
            name = clean.split("：")[0].split(":")[0].split("，")[0].split(",")[0].strip()
            if name and name not in parsed:
                parsed.append(name)

        if parsed:
            return NameGenerateResponse(
                names=parsed,
                type=type_name,
                style=style,
                source="ai",
            )

        return _fallback_names(type_name, style, count)

    except Exception as e:
        logger.warning(f"Name API exception: {type(e).__name__}: {e}")
        return _fallback_names(type_name, style, count)


def _parse_name_json(content: str, count: int) -> list[str] | None:
    """从 AI 响应中解析 JSON 格式的名字列表"""
    # 尝试提取 ```json ... ``` 包裹的内容
    import re
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if json_match:
        content = json_match.group(1)

    # 尝试直接解析 JSON
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            items = data.get("names", data.get("items", data.get("result", [])))
            if isinstance(items, list):
                names = []
                for item in items:
                    if isinstance(item, dict):
                        n = item.get("name", item.get("text", ""))
                    elif isinstance(item, str):
                        n = item
                    else:
                        continue
                    if n:
                        names.append(n)
                return names[:count] if names else None
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _fallback_names(
    type_name: str,
    style: str,
    count: int,
) -> NameGenerateResponse:
    """返回预设名字库作为降级方案"""
    pool = FALLBACK_NAMES.get(type_name, {}).get(style, [])
    # 取前 count 个
    selected = pool[:count]
    names = [item["name"] for item in selected]

    # 如果不够，循环取
    while len(names) < count and pool:
        for item in pool:
            if len(names) >= count:
                break
            if item["name"] not in names:
                names.append(item["name"])

    return NameGenerateResponse(
        names=names,
        type=type_name,
        style=style,
        source="fallback",
    )


# ─── 路由 ───


@router.post("/name", status_code=200)
async def generate_name(body: NameGenerateRequest):
    """根据类型和风格生成名字建议

    优先通过已配置的 AI 服务生成，未配置 Key 时使用预设库降级。
    """
    if body.count < 1 or body.count > 20:
        raise HTTPException(400, detail={
            "code": "INVALID_PARAMETER",
            "message": "count 必须在 1-20 之间",
        })

    result = await _call_name_api(
        prompt=_build_prompt(body.type, body.style, body.count, body.project_id),
        count=body.count,
        type_name=body.type,
        style=body.style,
    )

    return result
