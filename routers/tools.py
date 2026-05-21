"""
工具脚本执行路由 — subprocess 白名单安全运行

POST   /tools/review         — 对指定章节运行 _review.py
POST   /tools/guard-scan     — 对指定章节运行 guard.py scan
POST   /tools/guard-filter   — 对指定目录运行 guard.py filter
GET    /tools/list           — 列出可用工具脚本

路径前缀 /api/v1/tools

安全约束：
- 白名单脚本列表
- 参数格式白名单（正则匹配）
- 30 秒超时
- 输出截断 64KB
- 路径穿越防护
"""

import re
import subprocess
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tools", tags=["tools"])
BASE = Path(__file__).resolve().parent.parent

# ─── 脚本白名单 ───

ALLOWED_SCRIPTS = {
    "_review.py",
    "guard.py",
    "chapter_review.py",
}

ALLOWED_ARGS_PATTERNS = [
    re.compile(r"^第\d+[-_~]\d+章_.+\.md$"),
    re.compile(r"^第\d+章_.+\.md$"),
    re.compile(r"^_tmp_.+\.md$"),
    re.compile(r"^(filter|scan|clean)$"),
    re.compile(r"^chapters$"),
    re.compile(r"^--\w+.*$"),
]

TIMEOUT = 30
MAX_OUTPUT = 65536

# ─── 异常定义 ───

class ScriptNotFound(Exception):
    pass
class ScriptTimeout(Exception):
    pass
class ScriptExecutionError(Exception):
    pass
class ArgNotAllowed(Exception):
    pass

# ─── 配置加载 ───


def _load_project_config() -> dict:
    """从 config.yaml 加载项目配置"""
    yaml_path = BASE / "config.yaml"
    cfg = {}
    if yaml_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            pass  # Config file optional
    return cfg


def _get_project_root(project: str) -> Path | None:
    """获取项目根目录"""
    cfg = _load_project_config()
    proj = cfg.get("projects", {}).get(project, {})
    root = proj.get("root")
    if root:
        return Path(root).expanduser().resolve()
    return None


def _get_script_path(script_name: str, project: str) -> Path | None:
    """获取脚本的完整路径"""
    cfg = _load_project_config()

    # guard.py 可能有全局路径
    if script_name == "guard.py":
        global_guard = cfg.get("global_tools", {}).get("guard")
        if global_guard:
            p = Path(global_guard).expanduser().resolve()
            if p.exists():
                return p

    # 项目级脚本
    proj = cfg.get("projects", {}).get(project, {})
    root = proj.get("root")
    if root:
        base = Path(root).expanduser().resolve()
        # 检查项目根目录下的脚本
        candidate = base / script_name
        if candidate.exists():
            return candidate
        # 检查 _tools/ 目录下的脚本
        candidate = base.parent / script_name
        if candidate.exists():
            return candidate

    return None


# ─── 参数校验 ───


def _validate_arg(arg: str):
    """校验参数是否符合白名单模式"""
    for pattern in ALLOWED_ARGS_PATTERNS:
        if pattern.match(arg):
            return
    raise ArgNotAllowed(f"参数 '{arg}' 不在白名单中")


def _validate_args(args: list[str]):
    for arg in args:
        _validate_arg(arg)


# ─── 输出解析 ───


def _parse_review_output(output: str, chapter: str) -> dict:
    """解析 _review.py 的输出，提取 issues 和 metrics"""
    cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', output))
    stops = output.count("。")
    issues = []

    # 检查"OK"关键字
    is_ok = bool(re.search(r'\bOK\b', output))

    # 检查常见问题模式
    wc_match = re.search(r'字数[约]?(\d+)', output)
    if wc_match:
        wc = int(wc_match.group(1))
        if wc < 2000:
            issues.append({
                "type": "word_count",
                "severity": "warning",
                "detail": f"字数{wc} (基线2500±300)",
            })

    density_match = re.search(r'句号[约]?(\d+\.?\d*)/百字', output)
    if density_match:
        density_val = float(density_match.group(1))
        if density_val > 6:
            issues.append({
                "type": "sentence_density",
                "severity": "warning",
                "detail": f"句号密度{density_val}/百字 (建议≤6)",
            })

    bs_match = re.findall(r'不是[^。，；！？\n]{2,30}是[^。，；！？\n]{2,30}', output)
    if len(bs_match) >= 2:
        issues.append({
            "type": "sentence_pattern",
            "severity": "warning",
            "detail": f'"不是...是"句式重复{len(bs_match)}次',
        })

    hao_match = re.findall(r'[。]好的[，,]', output)
    if hao_match:
        issues.append({
            "type": "transition_word",
            "severity": "info",
            "detail": f'"好的"过渡{len(hao_match)}处',
        })

    metrics = {
        "cjk_chars": cjk,
        "sentence_density": round(stops / cjk * 100, 2) if cjk > 0 else 0,
        "issues_count": len(issues),
    }

    status = "ok" if (is_ok and not issues) else "issues_found"

    return {
        "status": status,
        "output": output.strip(),
        "issues": issues,
        "metrics": metrics,
    }


# ─── Pydantic 模型 ───


class ToolRunRequest(BaseModel):
    chapter: str = Field(..., description="章节文件名，如 第40章_离开之前.md")
    project: str = Field("tales-of-tera", description="项目标识")


class FilterRequest(BaseModel):
    directory: str = Field("chapters", description="要过滤的目录（相对于项目根）")
    pattern: str = Field("第*章_*.md", description="过滤模式，如 glob pattern")
    project: str = Field("tales-of-tera", description="项目标识")


class ToolIssue(BaseModel):
    type: str
    severity: str
    detail: str


class ToolMetrics(BaseModel):
    cjk_chars: int
    sentence_density: float
    issues_count: int = 0
    diary_length: int | None = None


class ToolReviewResponse(BaseModel):
    status: str
    output: str
    issues: list[ToolIssue]
    metrics: ToolMetrics


class ToolListResponse(BaseModel):
    scripts: list[dict]


# ─── 路由 ───


@router.post("/review", response_model=ToolReviewResponse)
def run_review(body: ToolRunRequest):
    """对指定章节运行 _review.py 审查脚本"""
    chapter = body.chapter
    project = body.project

    # 1. 定位项目目录
    project_root = _get_project_root(project)
    if not project_root:
        raise HTTPException(404, detail={
            "code": "PROJECT_NOT_FOUND",
            "message": f"项目 '{project}' 未在 config.yaml 中配置",
        })

    # 2. 定位脚本
    script_path = _get_script_path("_review.py", project)
    if not script_path:
        raise HTTPException(404, detail={
            "code": "SCRIPT_NOT_FOUND",
            "message": "_review.py 未找到",
            "detail": "请确保 _review.py 在项目根目录或上一级目录中",
        })

    # 3. 校验参数
    try:
        _validate_args([chapter])
    except ArgNotAllowed as e:
        raise HTTPException(400, detail={
            "code": "INVALID_ARGUMENT",
            "message": str(e),
            "suggestion": "章节文件名应符合 第X章_标题.md 或 _tmp_ 前缀格式",
        })

    # 4. 校验章节文件路径安全
    chapters_dir = project_root / "chapters"
    if not chapters_dir.is_dir():
        # 尝试从配置中读取 chapters_dir
        cfg = _load_project_config()
        chapters_rel = cfg.get("projects", {}).get(project, {}).get("chapters_dir", "chapters")
        chapters_dir = project_root / chapters_rel

    target_file = (chapters_dir / chapter).resolve()
    if not str(target_file).startswith(str(chapters_dir.resolve())):
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "路径越界"})
    if not target_file.exists():
        raise HTTPException(404, detail={
            "code": "FILE_NOT_FOUND",
            "message": f"章节文件 {chapter} 不存在",
            "detail": f"在 {chapters_dir} 下未找到",
        })

    # 5. 执行 subprocess
    try:
        result = subprocess.run(
            ["python", str(script_path), chapter],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=str(project_root),
        )
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            output = "(无输出)"
    except subprocess.TimeoutExpired:
        raise HTTPException(424, detail={
            "code": "SCRIPT_TIMEOUT",
            "message": f"脚本执行超时（{TIMEOUT}秒）",
        })
    except FileNotFoundError:
        raise HTTPException(500, detail={
            "code": "SCRIPT_ERROR",
            "message": "未找到 python 解释器",
        })
    except Exception as e:
        raise HTTPException(424, detail={
            "code": "SCRIPT_ERROR",
            "message": f"脚本执行异常: {e}",
        })

    # 6. 同时运行本地审查（字数、句号密度等）
    if target_file.exists() and chapters_dir:
        chapter_text = target_file.read_text(encoding="utf-8", errors="replace")
        parts = chapter_text.split("---", 1)
        body_text = parts[0].strip()
        diary_text = parts[1].strip() if len(parts) > 1 else ""

        cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', body_text))
        stops_count = body_text.count("。")
        density = round(stops_count / cjk_count * 100, 2) if cjk_count > 0 else 0
        diary_cjk = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', diary_text))
    else:
        cjk_count = 0
        density = 0
        diary_cjk = 0

    # 7. 解析 + 组合结果
    parsed = _parse_review_output(output, chapter)
    parsed["status"] = "issues_found" if parsed.get("issues") else "ok"
    parsed["metrics"] = ToolMetrics(
        cjk_chars=cjk_count,
        sentence_density=density,
        issues_count=len(parsed.get("issues", [])),
        diary_length=diary_cjk,
    )

    return ToolReviewResponse(**parsed)


@router.post("/guard-scan")
def run_guard_scan(body: ToolRunRequest):
    """对指定章节运行 guard.py scan"""
    chapter = body.chapter
    project = body.project

    project_root = _get_project_root(project)
    if not project_root:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": f"项目 '{project}' 未配置"})

    script_path = _get_script_path("guard.py", project)
    if not script_path:
        raise HTTPException(404, detail={"code": "SCRIPT_NOT_FOUND", "message": "guard.py 未找到"})

    try:
        _validate_args(["scan", chapter])
    except ArgNotAllowed as e:
        raise HTTPException(400, detail={"code": "INVALID_ARGUMENT", "message": str(e)})

    try:
        result = subprocess.run(
            ["python", str(script_path), "scan", chapter],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=str(project_root),
        )
        raw_stdout = result.stdout.strip() or result.stderr.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        raise HTTPException(424, detail={"code": "SCRIPT_TIMEOUT", "message": f"guard.py 超时（{TIMEOUT}秒）"})
    except FileNotFoundError:
        raise HTTPException(500, detail={"code": "SCRIPT_ERROR", "message": "未找到 python 解释器"})
    except Exception as e:
        raise HTTPException(424, detail={"code": "SCRIPT_ERROR", "message": f"异常: {e}"})

    # 解析输出：判断是否通过
    passed = "通过" in raw_stdout or "OK" in raw_stdout or "no issues" in raw_stdout.lower()
    hits = re.findall(r'(?:命中|问题|issue)[:：]\s*(.+)', raw_stdout, re.IGNORECASE)

    return {
        "status": "passed" if passed else "issues_found",
        "output": raw_stdout[:MAX_OUTPUT],
        "hits": hits,
        "script": "guard.py scan",
    }


@router.post("/guard-filter")
def run_guard_filter(body: FilterRequest):
    """对指定目录运行 guard.py filter"""
    project = body.project
    directory = body.directory
    pattern = body.pattern

    project_root = _get_project_root(project)
    if not project_root:
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": f"项目 '{project}' 未配置"})

    script_path = _get_script_path("guard.py", project)
    if not script_path:
        raise HTTPException(404, detail={"code": "SCRIPT_NOT_FOUND", "message": "guard.py 未找到"})

    try:
        _validate_args([directory, pattern])
    except ArgNotAllowed as e:
        raise HTTPException(400, detail={"code": "INVALID_ARGUMENT", "message": str(e)})

    target_dir = (project_root / directory).resolve()
    if not str(target_dir).startswith(str(project_root.resolve())):
        raise HTTPException(423, detail={"code": "PATH_TRAVERSAL", "message": "目录越界"})

    try:
        result = subprocess.run(
            ["python", str(script_path), "filter", directory, pattern],
            capture_output=True, text=True, timeout=TIMEOUT, cwd=str(project_root),
        )
        raw_stdout = result.stdout.strip() or result.stderr.strip() or "(无输出)"
    except subprocess.TimeoutExpired:
        raise HTTPException(424, detail={"code": "SCRIPT_TIMEOUT", "message": f"guard.py filter 超时（{TIMEOUT}秒）"})
    except Exception as e:
        raise HTTPException(424, detail={"code": "SCRIPT_ERROR", "message": f"异常: {e}"})

    files = [line.strip() for line in raw_stdout.split("\n") if line.strip() and ".md" in line]

    return {
        "status": "ok",
        "output": raw_stdout[:MAX_OUTPUT],
        "files": files,
        "count": len(files),
    }


@router.get("/list", response_model=ToolListResponse)
def list_tools():
    """列出可用工具脚本及其路径"""
    cfg = _load_project_config()
    scripts = []

    # 全局工具
    global_tools = cfg.get("global_tools", {})
    for name, path_str in global_tools.items():
        p = Path(path_str).expanduser().resolve() if path_str else None
        scripts.append({
            "name": name,
            "type": "global",
            "path": str(p) if p else None,
            "exists": p.exists() if p else False,
        })

    # 项目级工具
    for proj_name, proj_cfg in cfg.get("projects", {}).items():
        root = proj_cfg.get("root")
        if not root:
            continue
        base = Path(root).expanduser().resolve()
        for script_name in ALLOWED_SCRIPTS:
            candidates = [
                base / script_name,
                base.parent / script_name,
            ]
            for c in candidates:
                if c.exists():
                    scripts.append({
                        "name": script_name,
                        "type": "project",
                        "project": proj_name,
                        "path": str(c),
                        "exists": True,
                    })
                    break

    # 去重
    seen = set()
    unique = []
    for s in scripts:
        key = (s["name"], s.get("project", ""))
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return ToolListResponse(scripts=unique)
