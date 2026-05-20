"""
工具定义 — 所有工具的注册入口

每个工具按 MCP 格式定义：
  Tool(name, description, inputSchema, handler)

导入后在 app 启动时调用 register_all_tools() 完成注册。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from core.tools import Tool, get_registry
from core.style_engine import get_registry as get_style_registry

# ─── 路径基础 ───

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
CHAPTERS_DIR = BASE / "chapters"
KNOWLEDGE_DIR = BASE / "knowledge"
SCENES_DIR = BASE / "scenes"
PROJECTS_DIR = BASE / "projects"

for d in [DATA_DIR, CHAPTERS_DIR, KNOWLEDGE_DIR, SCENES_DIR, PROJECTS_DIR]:
    d.mkdir(exist_ok=True)

_MAX_OUTPUT = 65536
_SCRIPT_TIMEOUT = 30

# ─── 配置加载（与 routers/tools.py 一致的模式） ───


def _load_config() -> dict:
    yaml_path = BASE / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            return yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
    return {}


def _get_project_root(project: str) -> Path | None:
    cfg = _load_config()
    proj = cfg.get("projects", {}).get(project, {})
    root = proj.get("root")
    if root:
        return Path(root).expanduser().resolve()
    return None


def _get_script_path(script_name: str, project: str) -> Path | None:
    cfg = _load_config()
    if script_name == "guard.py":
        global_guard = cfg.get("global_tools", {}).get("guard")
        if global_guard:
            p = Path(global_guard).expanduser().resolve()
            if p.exists():
                return p
    proj = cfg.get("projects", {}).get(project, {})
    root = proj.get("root")
    if root:
        base = Path(root).expanduser().resolve()
        candidate = base / script_name
        if candidate.exists():
            return candidate
        candidate = base.parent / script_name
        if candidate.exists():
            return candidate
    return None


def _get_chapters_dir(project: str) -> Path | None:
    cfg = _load_config()
    proj = cfg.get("projects", {}).get(project, {})
    root = proj.get("root")
    chapters_rel = proj.get("chapters_dir", "chapters")
    if root:
        p = Path(root).expanduser().resolve() / chapters_rel
        if p.is_dir():
            return p
    return CHAPTERS_DIR if CHAPTERS_DIR.is_dir() else None


# ─── 安全校验 ───

_FILENAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff\-~/]+\.(md|txt|json)$")


def _validate_filename(name: str) -> bool:
    return bool(_FILENAME_PATTERN.match(name))


# ══════════════════════════════════════════════
# Handler 实现
# ══════════════════════════════════════════════

# ─── 1. review — 章节写作审查 ───


def _review_handler(args: dict[str, Any]) -> dict:
    """对指定章节运行 _review.py 审查脚本"""
    chapter: str = args.get("chapter", "")
    project: str = args.get("project", "tales-of-tera")

    if not chapter:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: chapter"}]}

    project_root = _get_project_root(project)
    if not project_root:
        return {"isError": True, "content": [{"type": "text", "text": f"项目 '{project}' 未在 config.yaml 中配置"}]}

    script_path = _get_script_path("_review.py", project)
    if not script_path:
        return {"isError": True, "content": [{"type": "text", "text": "_review.py 未找到，请确认脚本在项目根目录或上一级目录中"}]}

    chapters_dir = _get_chapters_dir(project)
    if not chapters_dir:
        return {"isError": True, "content": [{"type": "text", "text": "章节目录不存在"}]}

    try:
        result = subprocess.run(
            ["python", str(script_path), chapter],
            capture_output=True, text=True, timeout=_SCRIPT_TIMEOUT,
            cwd=str(project_root),
        )
        output = (result.stdout.strip() or result.stderr.strip() or "(无输出)")[:_MAX_OUTPUT]

        # 本地字数分析
        target_file = chapters_dir / chapter
        target_file = target_file.resolve()
        if target_file.exists() and str(target_file).startswith(str(chapters_dir.resolve())):
            raw = target_file.read_text(encoding="utf-8", errors="replace")
            parts = raw.split("---", 1)
            body = parts[0].strip()
            diary = parts[1].strip() if len(parts) > 1 else ""
            cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', body))
            stops = body.count("。")
            diary_cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', diary))
        else:
            cjk, stops, diary_cjk = 0, 0, 0

        return {
            "content": [{"type": "text", "text": output}],
            "meta": {
                "cjk_chars": cjk,
                "sentence_density": round(stops / cjk * 100, 2) if cjk > 0 else 0,
                "diary_length": diary_cjk,
            },
        }
    except subprocess.TimeoutExpired:
        return {"isError": True, "content": [{"type": "text", "text": f"审查超时（{_SCRIPT_TIMEOUT}秒）"}]}
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": "未找到 python 解释器"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"审查执行异常: {e}"}]}


# ─── 2. chat — AI 对话 ───


def _chat_handler(args: dict[str, Any]) -> dict:
    """AI 对话（非流式），支持 mode=chat/continue/expand/rewrite"""
    messages: list = args.get("messages", [])
    mode: str = args.get("mode", "chat")
    model: str = args.get("model", "deepseek")

    if not messages:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: messages"}]}

    # 从 key_manager 获取 API Key
    try:
        from services.key_manager import KeyManager
        km = KeyManager(storage_path=DATA_DIR / "keys.json")
    except ImportError:
        return {"isError": True, "content": [{"type": "text", "text": "key_manager 服务不可用"}]}

    api_key = km.get_key(model.lower())
    if not api_key:
        return {"isError": True, "content": [{"type": "text", "text": f"{model} 的 API Key 未配置，请通过 keys 接口设置"}]}

    # Provider 配置（与 routers/chat.py 一致）
    PROVIDERS = {
        "deepseek": {"url": "https://api.deepseek.com/v1/chat/completions", "model": "deepseek-v4-flash"},
        "openai": {"url": "https://api.openai.com/v1/chat/completions", "model": "gpt-5.4"},
        "moonshot": {"url": "https://api.moonshot.cn/v1/chat/completions", "model": "kimi-k2.6"},
        "zhipu": {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-5.1"},
        "yi": {"url": "https://api.lingyiwanwu.com/v1/chat/completions", "model": "yi-lightning"},
        "google": {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "model": "gemini-2.5-pro"},
    }
    provider = PROVIDERS.get(model.lower(), PROVIDERS["deepseek"])

    # mode 对应的系统提示
    MODE_PROMPTS = {
        "chat": "你是专业的写作助手。回答简洁、直接，不啰嗦。",
        "continue": "你正在续写一段小说。保持文风、视角和叙事节奏。不重复、不点评、不概括。直接从上一段末尾自然延续。",
        "expand": "你正在根据简短的描述展开成详细生动的段落。增加细节描写但不改变情节走向。",
        "rewrite": "你正在按要求重写一段文本。保留关键信息和情节，调整风格或表述。",
    }

    system_prompt = MODE_PROMPTS.get(mode, MODE_PROMPTS["chat"])

    # 构建请求体
    payload = {
        "model": provider["model"],
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "temperature": args.get("temperature", 0.7),
        "max_tokens": args.get("max_tokens", 4096),
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        with httpx.Client(timeout=120) as client:
            resp = client.post(provider["url"], json=payload, headers=headers)
            if resp.status_code != 200:
                return {
                    "isError": True,
                    "content": [{"type": "text", "text": f"API 返回 {resp.status_code}: {resp.text[:500]}"}],
                }
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            return {
                "content": [{"type": "text", "text": content}],
                "meta": {
                    "model": provider["model"],
                    "usage": {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                },
            }
    except ImportError:
        return {"isError": True, "content": [{"type": "text", "text": "httpx 未安装，请 pip install httpx"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"对话调用异常: {e}"}]}


# ─── 3. knowledge_list — 知识库文件清单 ───


def _knowledge_list_handler(args: dict[str, Any]) -> dict:
    """列出知识库文件"""
    # 尝试从 config.yaml 获取知识库路径
    kb_path = None
    cfg = _load_config()
    for _name, info in cfg.get("knowledge_base", {}).items():
        root = info.get("root")
        if root:
            p = Path(root).expanduser().resolve()
            if p.is_dir():
                kb_path = p
                break

    if not kb_path:
        kb_path = KNOWLEDGE_DIR

    files = []
    for entry in sorted(kb_path.rglob("*")):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
            continue
        if entry.name.startswith("_"):
            continue
        rel = entry.relative_to(kb_path)
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', entry.read_text(encoding="utf-8", errors="replace")))
        files.append({
            "name": str(rel.as_posix()),
            "size": entry.stat().st_size,
            "cjk_chars": cjk,
        })

    return {
        "content": [{"type": "text", "text": json.dumps(files, ensure_ascii=False)}],
        "meta": {"total": len(files), "base_path": str(kb_path)},
    }


# ─── 4. knowledge_read — 读取知识库文件 ───


def _knowledge_read_handler(args: dict[str, Any]) -> dict:
    """读取指定知识库文件内容"""
    path: str = args.get("path", "")
    if not path:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: path"}]}

    # 定位知识库根目录
    kb_path = None
    cfg = _load_config()
    for _name, info in cfg.get("knowledge_base", {}).items():
        root = info.get("root")
        if root:
            p = Path(root).expanduser().resolve()
            if p.is_dir():
                kb_path = p
                break
    if not kb_path:
        kb_path = KNOWLEDGE_DIR

    # 安全解析
    target = (kb_path / path).resolve()
    if not str(target).startswith(str(kb_path.resolve())):
        return {"isError": True, "content": [{"type": "text", "text": "路径越界"}]}
    if not target.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"文件不存在: {path}"}]}
    if target.suffix.lower() not in {".md", ".txt", ".json", ".yaml", ".yml"}:
        return {"isError": True, "content": [{"type": "text", "text": f"不支持的文件类型: {target.suffix}"}]}
    if target.stat().st_size > 5 * 1024 * 1024:
        return {"isError": True, "content": [{"type": "text", "text": "文件超过 5MB 传输上限"}]}

    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": [{"type": "text", "text": content}], "meta": {"path": path}}


# ─── 5. chapters_list — 章节文件清单 ───


def _chapters_list_handler(args: dict[str, Any]) -> dict:
    """列出所有章节文件"""
    project: str = args.get("project", "tales-of-tera")
    chapters_dir = _get_chapters_dir(project)
    if not chapters_dir:
        return {"isError": True, "content": [{"type": "text", "text": "章节目录不存在"}]}

    files = []
    for entry in sorted(chapters_dir.glob("*.md")):
        if not entry.is_file():
            continue
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]',
                             entry.read_text(encoding="utf-8", errors="replace")))
        files.append({
            "name": entry.name,
            "size": entry.stat().st_size,
            "cjk_chars": cjk,
        })

    return {
        "content": [{"type": "text", "text": json.dumps(files, ensure_ascii=False)}],
        "meta": {"total": len(files), "directory": str(chapters_dir)},
    }


# ─── 6. chapter_read — 读取章节文件 ───


def _chapter_read_handler(args: dict[str, Any]) -> dict:
    """读取指定章节文件内容"""
    filename: str = args.get("filename", "")
    project: str = args.get("project", "tales-of-tera")

    if not filename:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: filename"}]}

    chapters_dir = _get_chapters_dir(project)
    if not chapters_dir:
        return {"isError": True, "content": [{"type": "text", "text": "章节目录不存在"}]}

    target = (chapters_dir / filename).resolve()
    if not str(target).startswith(str(chapters_dir.resolve())):
        return {"isError": True, "content": [{"type": "text", "text": "路径越界"}]}
    if not target.exists():
        return {"isError": True, "content": [{"type": "text", "text": f"章节文件不存在: {filename}"}]}
    if target.suffix.lower() != ".md":
        return {"isError": True, "content": [{"type": "text", "text": "仅支持 .md 文件"}]}

    content = target.read_text(encoding="utf-8", errors="replace")
    return {"content": [{"type": "text", "text": content}], "meta": {"filename": filename}}


# ─── 7. scenes_list — 场景列表 ───


def _scenes_list_handler(args: dict[str, Any]) -> dict:
    """列出某章节下所有场景"""
    chapter_id: str = args.get("chapter_id", "")
    if not chapter_id:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: chapter_id"}]}

    # 防路径穿越
    safe_name = Path(chapter_id).name
    if safe_name != chapter_id:
        return {"isError": True, "content": [{"type": "text", "text": f"无效的 chapter_id: {chapter_id}"}]}

    target = (SCENES_DIR / safe_name).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(SCENES_DIR.resolve())):
        return {"isError": True, "content": [{"type": "text", "text": "路径越界"}]}

    if not target.exists():
        return {"content": [{"type": "text", "text": "[]"}], "meta": {"chapter_id": chapter_id, "count": 0}}

    try:
        scenes = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(scenes, list):
            scenes = []
    except (json.JSONDecodeError, ValueError):
        scenes = []

    return {
        "content": [{"type": "text", "text": json.dumps(scenes, ensure_ascii=False)}],
        "meta": {"chapter_id": chapter_id, "count": len(scenes)},
    }


# ─── 8. scene_create — 创建场景 ───


def _scene_create_handler(args: dict[str, Any]) -> dict:
    """在指定章节下创建新场景"""
    chapter_id: str = args.get("chapter_id", "")
    title: str = args.get("title", "新场景")
    status: str = args.get("status", "draft")

    if not chapter_id:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: chapter_id"}]}

    safe_name = Path(chapter_id).name
    if safe_name != chapter_id:
        return {"isError": True, "content": [{"type": "text", "text": f"无效的 chapter_id: {chapter_id}"}]}

    target = (SCENES_DIR / safe_name).with_suffix(".json")
    target = target.resolve()
    if not str(target).startswith(str(SCENES_DIR.resolve())):
        return {"isError": True, "content": [{"type": "text", "text": "路径越界"}]}

    scenes = []
    if target.exists():
        try:
            scenes = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(scenes, list):
                scenes = []
        except (json.JSONDecodeError, ValueError):
            scenes = []

    scene = {
        "id": f"scene_{len(scenes) + 1}",
        "title": title,
        "status": status if status in {"draft", "written", "revised", "final"} else "draft",
        "summary": args.get("summary", ""),
        "word_count": args.get("word_count", 0),
        "order": len(scenes),
    }
    scenes.append(scene)
    target.write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "content": [{"type": "text", "text": json.dumps(scene, ensure_ascii=False)}],
        "meta": {"chapter_id": chapter_id, "total": len(scenes)},
    }


# ─── 9. projects_list — 项目列表 ───


def _projects_list_handler(args: dict[str, Any]) -> dict:
    """列出所有项目"""
    results = []
    if not PROJECTS_DIR.is_dir():
        return {"content": [{"type": "text", "text": "[]"}], "meta": {"total": 0}}

    for entry in sorted(PROJECTS_DIR.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        config_path = entry / "config.json"
        if not config_path.exists():
            continue
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        results.append({
            "id": entry.name,
            "name": cfg.get("name", entry.name),
            "template": cfg.get("template", "default"),
            "description": cfg.get("description", ""),
            "created_at": cfg.get("created_at", ""),
            "updated_at": cfg.get("updated_at", ""),
        })

    return {
        "content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False)}],
        "meta": {"total": len(results)},
    }


# ─── 10. project_create — 创建项目 ───


def _project_create_handler(args: dict[str, Any]) -> dict:
    """创建新项目"""
    import uuid
    from datetime import datetime, timezone

    name: str = args.get("name", "未命名项目")
    description: str = args.get("description", "")
    template: str = args.get("template", "empty")

    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    config = {
        "name": name,
        "id": project_id,
        "template": template,
        "description": description,
        "created_at": now,
        "updated_at": now,
    }
    (project_dir / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # 创建子目录
    for subdir in ["chapters", "knowledge", "scenes"]:
        (project_dir / subdir).mkdir(exist_ok=True)

    return {
        "content": [{"type": "text", "text": json.dumps(config, ensure_ascii=False)}],
        "meta": {"id": project_id},
    }


# ─── 11. guard_scan — 内容安全检查 ───


def _guard_scan_handler(args: dict[str, Any]) -> dict:
    """对指定章节运行 guard.py scan 安全检查"""
    chapter: str = args.get("chapter", "")
    project: str = args.get("project", "tales-of-tera")

    if not chapter:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: chapter"}]}

    project_root = _get_project_root(project)
    if not project_root:
        return {"isError": True, "content": [{"type": "text", "text": f"项目 '{project}' 未在 config.yaml 中配置"}]}

    script_path = _get_script_path("guard.py", project)
    if not script_path:
        return {"isError": True, "content": [{"type": "text", "text": "guard.py 未找到"}]}

    try:
        result = subprocess.run(
            ["python", str(script_path), "scan", chapter],
            capture_output=True, text=True, timeout=_SCRIPT_TIMEOUT,
            cwd=str(project_root),
        )
        output = (result.stdout.strip() or result.stderr.strip() or "(无输出)")[:_MAX_OUTPUT]
        passed = "通过" in output or "OK" in output or "no issues" in output.lower()
        hits = [line for line in output.split("\n") if "命中" in line or "问题" in line or "issue" in line.lower()]

        return {
            "content": [{"type": "text", "text": output}],
            "meta": {"status": "passed" if passed else "issues_found", "hits": hits},
        }
    except subprocess.TimeoutExpired:
        return {"isError": True, "content": [{"type": "text", "text": f"安全检查超时（{_SCRIPT_TIMEOUT}秒）"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"安全检查异常: {e}"}]}


# ─── 12. style_list — 列出所有写法风格 ───


def _style_list_handler(args: dict[str, Any]) -> dict:
    """列出所有已注册的可复用写作风格"""
    try:
        sr = get_style_registry()
        styles = sr.list()
        result = [s.to_dict() for s in styles]
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            "meta": {"total": len(result)},
        }
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"读取风格列表失败: {e}"}]}


# ─── 13. style_analyze — 分析文本匹配风格 ───


def _style_analyze_handler(args: dict[str, Any]) -> dict:
    """分析一段文本，返回各风格的匹配度和详细特征"""
    text: str = args.get("text", "")
    if not text:
        return {"isError": True, "content": [{"type": "text", "text": "缺少必填参数: text"}]}

    try:
        sr = get_style_registry()
        results = sr.match(text)
        return {
            "content": [{"type": "text", "text": json.dumps(results, ensure_ascii=False)}],
            "meta": {
                "total_styles": len(results),
                "best_match": results[0]["style"] if results else None,
                "best_score": results[0]["score"] if results else 0,
            },
        }
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"风格分析失败: {e}"}]}


# ══════════════════════════════════════════════
# 注册函数
# ══════════════════════════════════════════════


def register_all_tools() -> None:
    """注册所有工具到全局 ToolRegistry"""
    registry = get_registry()

    # 1. review — 章节审查
    registry.register(Tool(
        name="review",
        description="对指定章节运行 _review.py 写作审查，检查字数、句式、密度等",
        inputSchema={
            "type": "object",
            "properties": {
                "chapter": {"type": "string", "description": "章节文件名，如 第40章_离开之前.md"},
                "project": {"type": "string", "description": "项目标识，默认 tales-of-tera"},
            },
            "required": ["chapter"],
        },
        handler=_review_handler,
    ))

    # 2. chat — AI 对话
    registry.register(Tool(
        name="chat",
        description="AI 写作对话，支持聊天、续写、扩写、重写四种模式",
        inputSchema={
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["system", "user", "assistant"]},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "对话消息列表",
                },
                "mode": {
                    "type": "string",
                    "enum": ["chat", "continue", "expand", "rewrite"],
                    "description": "对话模式：chat=普通聊天, continue=续写, expand=扩写, rewrite=重写",
                },
                "model": {
                    "type": "string",
                    "description": "模型标识：deepseek / openai / moonshot / zhipu / yi / google",
                },
                "temperature": {"type": "number", "description": "生成温度 0.0-2.0"},
                "max_tokens": {"type": "integer", "description": "最大生成 token 数"},
            },
            "required": ["messages"],
        },
        handler=_chat_handler,
    ))

    # 3. knowledge_list — 知识库文件清单
    registry.register(Tool(
        name="knowledge_list",
        description="列出知识库中所有文件的名称、大小和中文字数",
        inputSchema={"type": "object", "properties": {}},
        handler=_knowledge_list_handler,
    ))

    # 4. knowledge_read — 读取知识库文件
    registry.register(Tool(
        name="knowledge_read",
        description="读取指定知识库文件的完整内容",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "知识库文件路径（相对于知识库根目录）"},
            },
            "required": ["path"],
        },
        handler=_knowledge_read_handler,
    ))

    # 5. chapters_list — 章节文件清单
    registry.register(Tool(
        name="chapters_list",
        description="列出项目中所有章节文件",
        inputSchema={
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "项目标识，默认 tales-of-tera"},
            },
        },
        handler=_chapters_list_handler,
    ))

    # 6. chapter_read — 读取章节文件
    registry.register(Tool(
        name="chapter_read",
        description="读取指定章节文件的完整内容（含正文和日记）",
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "章节文件名，如 第40章_离开之前.md"},
                "project": {"type": "string", "description": "项目标识，默认 tales-of-tera"},
            },
            "required": ["filename"],
        },
        handler=_chapter_read_handler,
    ))

    # 7. scenes_list — 场景列表
    registry.register(Tool(
        name="scenes_list",
        description="列出指定章节下的所有场景",
        inputSchema={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节标识（用于查找 scenes/{chapter_id}.json）"},
            },
            "required": ["chapter_id"],
        },
        handler=_scenes_list_handler,
    ))

    # 8. scene_create — 创建场景
    registry.register(Tool(
        name="scene_create",
        description="在指定章节下创建新场景",
        inputSchema={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节标识"},
                "title": {"type": "string", "description": "场景标题"},
                "status": {"type": "string", "enum": ["draft", "written", "revised", "final"], "description": "场景状态"},
                "summary": {"type": "string", "description": "场景摘要"},
                "word_count": {"type": "integer", "description": "预估字数"},
            },
            "required": ["chapter_id"],
        },
        handler=_scene_create_handler,
    ))

    # 9. projects_list — 项目列表
    registry.register(Tool(
        name="projects_list",
        description="列出所有项目及其基本信息",
        inputSchema={"type": "object", "properties": {}},
        handler=_projects_list_handler,
    ))

    # 10. project_create — 创建项目
    registry.register(Tool(
        name="project_create",
        description="创建新写作项目（含 chapters/knowledge/scenes 子目录）",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "项目名称"},
                "description": {"type": "string", "description": "项目描述"},
                "template": {"type": "string", "description": "模板标识，默认 empty"},
            },
            "required": ["name"],
        },
        handler=_project_create_handler,
    ))

    # 11. guard_scan — 内容安全检查
    registry.register(Tool(
        name="guard_scan",
        description="对指定章节运行 guard.py 内容安全检查，检测敏感词和写作规范",
        inputSchema={
            "type": "object",
            "properties": {
                "chapter": {"type": "string", "description": "章节文件名"},
                "project": {"type": "string", "description": "项目标识，默认 tales-of-tera"},
            },
            "required": ["chapter"],
        },
        handler=_guard_scan_handler,
    ))

    # 12. style_list — 列出所有写法风格
    registry.register(Tool(
        name="style_list",
        description="列出所有已注册的可复用写作风格，含特征画像和规则定义",
        inputSchema={"type": "object", "properties": {}},
        handler=_style_list_handler,
    ))

    # 13. style_analyze — 分析文本匹配风格
    registry.register(Tool(
        name="style_analyze",
        description="分析一段文本与各写作风格的匹配度，返回评分、细节特征和禁用词命中",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要分析的文本内容（建议至少 100 字以获得稳定结果）"},
            },
            "required": ["text"],
        },
        handler=_style_analyze_handler,
    ))

    # 14. export — 导出文稿
    registry.register(Tool(
        name="export",
        description=(
            "导出文稿为指定格式文件。支持格式："
            "docx (Word 文档), txt (纯文本), pdf (PDF 文档), markdown (Markdown 压缩包)。"
            "导出后通过 REST API 端点 POST /api/v1/export/{format} 获取文件。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["docx", "txt", "pdf", "markdown"],
                    "description": "导出格式：docx / txt / pdf / markdown",
                },
                "chapters": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要导出的章节文件名列表，或传 ['all'] 表示全部",
                },
                "title": {"type": "string", "description": "导出文件标题（可选）"},
            },
            "required": ["format"],
        },
        handler=lambda args: {
            "content": [{"type": "text", "text": f"调用 POST /api/v1/export/{args.get('format', 'docx')} 导出，参数：章节={args.get('chapters', 'all')}，标题={args.get('title', '默认')}"}],
            "meta": {"endpoint": f"/api/v1/export/{args.get('format', 'docx')}"},
        },
    ))
