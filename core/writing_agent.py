"""
自主写作 Agent — Agentic Writing Workflow

WritingAgent 管理从「用户需求」到「完成章节」的完整写作流水线：
  plan → read_chapter → draft → review → revise → output

用法：
    agent = WritingAgent(project_id="xxx")
    result = await agent.run("帮我写下一章，沈默进入龙门")
    # result = { "plan": [...], "result": "...", "changes": [...], "duration_ms": 1234 }
"""

from __future__ import annotations

import json
import re
import time
import httpx
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"


# ─── 数据结构 ───


@dataclass
class AgentStep:
    """Agent 执行计划中的一个步骤"""
    action: str  # "read_chapter" | "draft" | "review" | "revise" | "save"
    params: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # "pending" | "running" | "done" | "failed"
    result: Any = None


@dataclass
class AgentResult:
    """Agent 执行结果"""
    plan: list[dict]
    result: str
    changes: list[str]
    duration_ms: int
    filename: str | None = None
    steps_detail: list[dict] = field(default_factory=list)


# ─── Provider 配置（同 routers/chat.py） ───

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
        "auth_header": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    },
}


# ─── WritingAgent ───


class WritingAgent:
    """自主写作 Agent"""

    def __init__(self, project_id: str, provider: str = "deepseek", temperature: float = 0.7):
        self.project_id = project_id
        self.provider = provider.lower()
        self.temperature = temperature
        self._project_dir: Path | None = None
        self._api_key: str | None = None
        self._provider_cfg: dict | None = None

    # ─── 基础设施 ───

    def _resolve_project(self) -> Path:
        if self._project_dir:
            return self._project_dir
        proj_dir = (PROJECTS_DIR / self.project_id).resolve()
        if not str(proj_dir).startswith(str(PROJECTS_DIR.resolve())):
            raise ValueError(f"项目路径越界: {self.project_id}")
        if not proj_dir.is_dir():
            raise FileNotFoundError(f"项目不存在: {self.project_id}")
        self._project_dir = proj_dir
        return proj_dir

    def _load_config(self) -> dict:
        cfg_path = self._resolve_project() / "config.json"
        if cfg_path.exists():
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        return {}

    def _load_writing_guide(self) -> str:
        """读取写作规范，返回格式化文本"""
        guide_file = self._resolve_project() / "writing-guide.json"
        if not guide_file.exists():
            return ""
        try:
            data = json.loads(guide_file.read_text(encoding="utf-8"))
            parts = []
            if data.get("style"):
                parts.append(f"写作风格：{data['style']}")
            if data.get("tone"):
                parts.append(f"语调：{data['tone']}")
            if data.get("description"):
                parts.append(f"描述：{data['description']}")
            forbidden = data.get("forbidden_words", [])
            if forbidden:
                parts.append(f"禁用词：{'、'.join(forbidden)}")
            names = data.get("character_names", [])
            if names:
                parts.append(f"角色名：{'、'.join(names)}")
            places = data.get("place_names", [])
            if places:
                parts.append(f"地名：{'、'.join(places)}")
            if data.get("max_sentence_length"):
                parts.append(f"最大句子长度：{data['max_sentence_length']} 字")
            return "。".join(parts)
        except (json.JSONDecodeError, OSError):
            return ""

    def _list_chapters(self) -> list[dict]:
        """列出项目下的所有章节文件"""
        chapters_dir = self._resolve_project() / "chapters"
        if not chapters_dir.is_dir():
            return []

        result = []
        for entry in sorted(chapters_dir.glob("*.md"), key=lambda p: p.stat().st_mtime):
            content = entry.read_text(encoding="utf-8", errors="replace")
            # 统计字数
            cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', content))
            result.append({
                "filename": entry.name,
                "title": entry.stem,
                "cjk_chars": cjk,
                "modified": entry.stat().st_mtime,
            })
        # 按文件名排序（章节编号）
        result.sort(key=lambda x: x["filename"])
        return result

    def _read_chapter(self, filename: str, max_chars: int = 8000) -> str:
        """读取某个章节的内容（截断到 max_chars）"""
        chapters_dir = self._resolve_project() / "chapters"
        target = (chapters_dir / filename).resolve()
        if not str(target).startswith(str(chapters_dir.resolve())):
            raise ValueError(f"路径越界: {filename}")
        if not target.exists():
            raise FileNotFoundError(f"章节文件不存在: {filename}")
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + "\n\n...（截断）"
        return content

    def _get_last_chapter(self) -> str | None:
        """获取最后一章的内容作为风格参考"""
        chapters = self._list_chapters()
        if not chapters:
            return None
        last = chapters[-1]["filename"]
        return self._read_chapter(last, max_chars=4000)

    def _read_outline(self) -> str:
        """读取项目中的大纲资料（knowledge 目录下的 outline/大纲 相关文件）"""
        proj_dir = self._resolve_project()
        knowledge_dir = proj_dir / "knowledge"
        if not knowledge_dir.is_dir():
            return ""
        parts = []
        for f in sorted(knowledge_dir.glob("*outline*")) + sorted(knowledge_dir.glob("*大纲*")):
            if f.suffix.lower() in {".md", ".txt"} and f.stat().st_size < 1024 * 100:
                parts.append(f"--- {f.stem} ---\n{f.read_text(encoding='utf-8', errors='replace')[:3000]}")
        return "\n\n".join(parts)

    # ─── AI 调用 ───

    def _ensure_api(self):
        """初始化 API Key 和 provider 配置"""
        if self._api_key and self._provider_cfg:
            return

        try:
            from services.key_manager import get_key
        except ImportError:
            raise RuntimeError("key_manager 服务未实现")

        config = PROVIDER_CONFIGS.get(self.provider)
        if not config:
            raise ValueError(f"不支持的 provider: {self.provider}")

        key = get_key(self.provider)
        if not key:
            raise RuntimeError(f"{self.provider} 的 API Key 未配置，请先通过设置页面配置")

        self._api_key = key
        self._provider_cfg = config

    async def _call_llm(self, messages: list[dict], max_tokens: int = 4096) -> str:
        """调用 LLM 获取非流式响应"""
        self._ensure_api()
        cfg = self._provider_cfg
        url = cfg["base_url"].rstrip("/") + cfg["chat_endpoint"]
        headers = cfg["auth_header"](self._api_key)
        headers["Content-Type"] = "application/json"

        is_anthropic = "x-api-key" in headers

        if is_anthropic:
            # Claude 格式
            system_text = None
            claude_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_text = m["content"]
                else:
                    claude_messages.append({"role": m["role"], "content": m["content"]})
            payload = {
                "model": cfg["default_model"],
                "max_tokens": max_tokens,
                "messages": claude_messages,
                "stream": False,
            }
            if system_text:
                payload["system"] = system_text
            if self.temperature:
                payload["temperature"] = self.temperature
        else:
            payload = {
                "model": cfg["default_model"],
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"API 返回 {resp.status_code}: {resp.text[:500]}")

            data = resp.json()

        if is_anthropic:
            content = data.get("content", [{}])[0].get("text", "")
        else:
            content = data["choices"][0]["message"]["content"]

        return content

    # ─── 执行步骤 ───

    async def plan(self, task: str) -> list[dict]:
        """分析用户需求，生成写作计划"""
        guide = self._load_writing_guide()
        chapters = self._list_chapters()
        outline = self._read_outline()

        # 格式化章节列表
        chapters_text = "\n".join(
            [f"  {c['filename']} ({c['cjk_chars']}字)" for c in chapters]
        ) if chapters else "（项目暂无章节）"

        # 构建系统提示
        sys_prompt = """你是一个专业的写作助理，负责制定章节写作计划。

分析用户的需求，结合项目的写作规范和现有章节，制定一个清晰的写作计划。

计划应为步骤列表，每个步骤包含：
  - action: 以下之一
    - read_chapter: 读取某个已有章节作为参考（params: {filename}）
    - draft: 起草新章节（params: {task_description}）
    - review: 对草稿执行风格自检
    - revise: 根据自检结果修订
    - save: 保存最终结果（params: {filename}）

注意事项：
1. 第一步总是 read_chapter，读取最后一章
2. 如果已有章节很少（<3章），可以读所有章节
3. draft 步骤的 task_description 要具体，指明章节内容走向
4. 最后一步总是 save
5. 输出格式为纯 JSON 数组"""

        # 构建用户提示
        user_prompt = f"""项目写作规范：
{guide if guide else "（未设置）"}

已有章节：
{chapters_text}

大纲资料：
{outline if outline else "（无）"}

用户需求：{task}

请制定写作计划。只输出 JSON 数组，不要包含其他内容。"""

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self._call_llm(messages, max_tokens=2048)

        # 提取 JSON（处理可能的包裹文本）
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if json_match:
            try:
                plan = json.loads(json_match.group())
            except json.JSONDecodeError:
                plan = self._fallback_plan(task)
        else:
            plan = self._fallback_plan(task)

        return plan

    def _fallback_plan(self, task: str) -> list[dict]:
        """当 LLM 无法返回有效计划时的降级方案"""
        chapters = self._list_chapters()
        last_filename = chapters[-1]["filename"] if chapters else None

        plan = []
        if last_filename:
            plan.append({"action": "read_chapter", "params": {"filename": last_filename}})
        plan.append({"action": "draft", "params": {"task_description": task}})
        plan.append({"action": "review", "params": {}})
        plan.append({"action": "revise", "params": {}})
        plan.append({"action": "save", "params": {"filename": "auto"}})
        return plan

    async def execute_step(self, step: AgentStep, context: dict) -> Any:
        """执行单个步骤"""
        step.status = "running"

        try:
            action = step.params.get("action") if isinstance(step.params, dict) else step.action

            if step.action == "read_chapter":
                filename = step.params.get("filename")
                if filename:
                    content = self._read_chapter(filename)
                else:
                    # 读前一章fallback
                    content = self._get_last_chapter() or "（无参考章节）"
                step.result = content
                step.status = "done"

            elif step.action == "draft":
                task_desc = step.params.get("task_description", "继续写作")
                prev_chapter = context.get("prev_chapter", "")
                guide = self._load_writing_guide()

                sys_prompt = """你是专业小说作家。根据写作计划和参考内容起草章节。

写作要求：
1. 保持与已有章节一致的文风和叙事节奏
2. 使用展示而非告诉的方式
3. 对话自然，符合角色性格
4. 段落之间有合理的节奏变化
5. 每一段都推进情节、塑造角色或营造氛围
6. 不要在章节结尾总结或点评
7. 直接输出正文，不要加"以下为章节正文"之类的说明"""

                messages = [{"role": "system", "content": sys_prompt}]

                # 注入写作规范
                if guide:
                    messages.append({"role": "system", "content": f"写作规范：{guide}"})

                # 注入前一章内容作为风格参考
                if prev_chapter:
                    # 去掉 frontmatter 以节省 token
                    clean_prev = re.sub(r'^---.*?---\n', '', prev_chapter, flags=re.DOTALL)
                    messages.append({"role": "user", "content": f"请参考以下已有章节的风格和内容来续写：\n\n{clean_prev[:3000]}"})
                    messages.append({"role": "assistant", "content": "已了解风格。请告诉我需要写什么内容。"})

                messages.append({"role": "user", "content": task_desc})

                draft = await self._call_llm(messages, max_tokens=8192)

                # 清理可能的包裹文本
                draft = re.sub(r'^---\n.*?\n---\n', '', draft, flags=re.DOTALL)
                for prefix in ["以下为章节正文", "以下是", "好的，", "这是"]:
                    if draft.startswith(prefix):
                        draft = re.sub(r'^.*?：\n*', '', draft, count=1)

                step.result = draft.strip()
                step.status = "done"

            elif step.action == "review":
                draft_text = context.get("draft", step.params.get("text", ""))
                if not draft_text:
                    raise ValueError("自检缺少待检查文本")

                # 调用已有的风格检查服务（模拟 HTTP 调用来保持解耦）
                review_results = await self._run_style_check(draft_text)
                if not isinstance(review_results, str):
                    # 格式化结果
                    if review_results.get("total_issues", 0) == 0:
                        step.result = "✅ 未发现问题"
                    else:
                        lines = [f"共发现 {review_results['total_issues']} 个问题："]
                        for r in review_results.get("results", []):
                            lines.append(f"  - [{r['rule']}] 行{r['line']}: {r['content'][:40]} → {r['suggestion'][:60]}")
                        step.result = "\n".join(lines)
                else:
                    step.result = review_results
                step.status = "done"

            elif step.action == "revise":
                draft_text = context.get("draft", "")
                review_text = context.get("review", step.params.get("review_result", ""))

                if not draft_text:
                    raise ValueError("修订缺少原文")

                sys_prompt = """你根据以下审查结果对章节进行修订。

修订原则：
1. 保留原文的核心内容和叙事节奏
2. 只修改被指出的问题（填充词、弱词、长句等）
3. 不要重新组织文章结构或改变情节
4. 不要添加原本没有的内容
5. 输出完整的修订后正文"""

                messages = [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"原文：\n\n{draft_text}\n\n审查结果：\n\n{review_text}\n\n请根据审查结果修订原文。"},
                ]

                revised = await self._call_llm(messages, max_tokens=8192)
                revised = re.sub(r'^---\n.*?\n---\n', '', revised, flags=re.DOTALL)
                step.result = revised.strip()
                step.status = "done"

            elif step.action == "save":
                draft_text = context.get("draft", "")
                filename = step.params.get("filename", "auto")

                if not draft_text:
                    raise ValueError("保存缺少内容")

                # 自动生成文件名
                if filename == "auto":
                    chapters = self._list_chapters()
                    next_num = 1
                    for c in chapters:
                        m = re.match(r"第(\d+)章", c["filename"])
                        if m:
                            n = int(m.group(1))
                            if n >= next_num:
                                next_num = n + 1
                    filename = f"第{next_num}章_新章节.md"

                # 安全写入
                chapters_dir = self._resolve_project() / "chapters"
                chapters_dir.mkdir(parents=True, exist_ok=True)
                target = (chapters_dir / filename).resolve()
                if not str(target).startswith(str(chapters_dir.resolve())):
                    raise ValueError(f"路径越界: {filename}")
                if target.exists():
                    # 重名时加后缀
                    stem = target.stem
                    suffix = target.suffix
                    counter = 1
                    while target.exists():
                        target = chapters_dir / f"{stem}_{counter}{suffix}"
                        target = target.resolve()
                        counter += 1
                    filename = target.name

                # 写入前添加 frontmatter
                fm = self._build_frontmatter(target.stem, draft_text)
                target.write_text(fm + draft_text, encoding="utf-8")

                step.result = {"filename": filename, "path": str(target)}
                step.status = "done"

            else:
                raise ValueError(f"未知动作: {step.action}")

        except Exception as e:
            step.status = "failed"
            step.result = f"错误: {type(e).__name__}: {e}"
            raise

        return step.result

    def _build_frontmatter(self, title: str, content: str) -> str:
        """为章节构建 YAML frontmatter"""
        cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', content))
        import yaml
        fm = {
            "title": title,
            "status": "draft",
            "words": cjk,
            "generated_by": "writing_agent",
        }
        return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False) + "---\n"

    async def _run_style_check(self, text: str) -> dict | str:
        """通过内部模块直接执行风格检查（避免 HTTP 循环调用）"""
        try:
            from core.writing_rules import registry

            issues = registry.check_all(text=text)
            results = []
            for iss in issues:
                results.append({
                    "rule": iss.rule_name,
                    "line": iss.line,
                    "content": iss.content,
                    "suggestion": iss.suggestion,
                })
            return {
                "total_issues": len(results),
                "results": results,
            }
        except ImportError:
            return "（风格检查插件未加载）"
        except Exception as e:
            return f"（风格检查异常: {e}）"

    # ─── 完整运行 ───

    async def run(self, task: str) -> dict:
        """完整执行：分析 → 按计划执行步骤 → 输出结果"""
        start_time = time.time()
        changes: list[str] = []
        context: dict[str, Any] = {}
        steps_detail: list[dict] = []

        # 1. 生成计划
        plan_raw = await self.plan(task)
        plan_steps = [AgentStep(action=s["action"], params=s.get("params", {})) for s in plan_raw]

        # 2. 按计划执行
        step_idx = 0
        while step_idx < len(plan_steps):
            step = plan_steps[step_idx]
            try:
                result = await self.execute_step(step, context)
                step.status = "done"

                step_record = {
                    "action": step.action,
                    "status": "done",
                    "result_summary": self._summarize_result(step.action, result),
                }
                steps_detail.append(step_record)

                # 更新 context
                if step.action == "read_chapter":
                    context["prev_chapter"] = result
                    changes.append(f"已读取参考章节")
                elif step.action == "draft":
                    context["draft"] = result
                    changes.append("初稿完成")
                elif step.action == "review":
                    context["review"] = result
                    changes.append("已完成风格自检")
                elif step.action == "revise":
                    context["draft"] = result
                    changes.append("已修订")
                elif step.action == "save":
                    if isinstance(result, dict):
                        context["saved_filename"] = result.get("filename", "")
                        changes.append(f"已保存为 {result.get('filename', '')}")

            except Exception as e:
                step.status = "failed"
                steps_detail.append({
                    "action": step.action,
                    "status": "failed",
                    "error": str(e),
                })
                changes.append(f"[出错] {step.action}: {str(e)[:60]}")
                # 失败时继续下一轮

            step_idx += 1

        duration_ms = int((time.time() - start_time) * 1000)

        # 最终结果
        final_text = context.get("draft", "（未生成内容）")
        saved_filename = context.get("saved_filename")

        # 格式化计划输出
        plan_output = []
        for s in plan_raw:
            plan_output.append({
                "action": s["action"],
                "params": s.get("params", {}),
            })

        return {
            "plan": plan_output,
            "result": final_text,
            "changes": changes,
            "duration_ms": duration_ms,
            "filename": saved_filename,
            "steps_detail": steps_detail,
        }

    def _summarize_result(self, action: str, result: Any) -> str:
        """生成执行结果的简短摘要"""
        if action == "read_chapter":
            if isinstance(result, str):
                return f"已读取 ({len(result)} 字符)"
            return "已读取"
        elif action == "draft":
            if isinstance(result, str):
                cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', result))
                return f"生成 {cjk} 字"
            return "已生成"
        elif action == "review":
            if isinstance(result, dict):
                return f"发现 {result.get('total_issues', 0)} 个问题"
            if isinstance(result, str):
                return result[:60]
            return "已完成"
        elif action == "revise":
            if isinstance(result, str):
                cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', result))
                return f"修订后 {cjk} 字"
            return "已修订"
        elif action == "save":
            if isinstance(result, dict):
                return f"保存为 {result.get('filename', '')}"
            return "已保存"
        return str(result)[:60]
