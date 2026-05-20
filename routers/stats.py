"""
写作统计路由

GET /stats/{project_id} — 返回项目写作统计

统计内容：
  - 总章节数、总字数
  - 角色数、场景数、伏笔数
  - 每日写作量（基于章节文件 mtime）
  - 平均每章字数、最长/最短章节
  - 连续写作天数

路径前缀 /api/v1/stats
"""

import json
import re
from pathlib import Path
from datetime import datetime, date, timezone, timedelta
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/stats", tags=["stats"])
BASE = Path(__file__).resolve().parent.parent
PROJECTS_DIR = BASE / "projects"

# ─── 字数统计 ───

def _count_words(text: str) -> int:
    """统计中英文字数。
    - 中文字符（CJK统一表意文字等）每个计 1 字
    - 英文单词按空白分割计词
    """
    if not text:
        return 0
    # 移除 frontmatter (--- 之间的 YAML)
    text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)
    # CJK 字符范围
    cjk = re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text)
    # 英文单词（去掉中文字符后按空白分割）
    non_cjk = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', ' ', text)
    english_words = non_cjk.split()
    return len(cjk) + len(english_words)


def _load_json_safe(path: Path) -> dict | list | None:
    """安全加载 JSON 文件，失败返回 None"""
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


# ─── 连续天数计算 ───

def _compute_streak(daily_dates: set[date]) -> int:
    """从活跃日期集合中计算连续写作天数（截至今天）"""
    if not daily_dates:
        return 0
    today = date.today()
    streak = 0
    check = today
    while check in daily_dates:
        streak += 1
        check -= timedelta(days=1)
    return streak


# ─── 主统计路由 ───

@router.get("/{project_id}")
async def get_project_stats(project_id: str):
    proj_dir = (PROJECTS_DIR / project_id).resolve()

    # 安全校验：防止路径穿越
    if not str(proj_dir).startswith(str(PROJECTS_DIR.resolve())):
        raise HTTPException(400, detail={"code": "INVALID_PROJECT", "message": "无效的项目 ID"})
    if not proj_dir.is_dir():
        raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND", "message": f"项目 '{project_id}' 不存在"})

    # ─── 章节统计 ───
    chapters_dir = proj_dir / "chapters"
    chapter_files = []
    if chapters_dir.is_dir():
        chapter_files = sorted(
            [f for f in chapters_dir.iterdir() if f.suffix.lower() in {".md", ".mdx"} and f.is_file()],
            key=lambda p: p.name
        )

    total_chapters = len(chapter_files)
    total_words = 0
    chapter_word_counts: list[dict] = []
    daily_map: dict[str, dict] = {}  # date -> {"words": int, "chapters": set}

    for cf in chapter_files:
        try:
            content = cf.read_text(encoding="utf-8")
            wc = _count_words(content)
            total_words += wc
            chapter_word_counts.append({
                "name": cf.name,
                "words": wc
            })

            # mtime -> 日期统计
            mtime = cf.stat().st_mtime
            dt = datetime.fromtimestamp(mtime, tz=timezone.utc).astimezone()
            day_key = dt.strftime("%Y-%m-%d")
            if day_key not in daily_map:
                daily_map[day_key] = {"words_written": 0, "chapters_modified": set()}
            daily_map[day_key]["words_written"] += wc
            daily_map[day_key]["chapters_modified"].add(cf.name)
        except (OSError, UnicodeDecodeError):
            continue

    # 每日统计列表（按日期倒序）
    daily_stats = [
        {
            "date": d,
            "words_written": info["words_written"],
            "chapters_modified": len(info["chapters_modified"])
        }
        for d, info in sorted(daily_map.items(), reverse=True)
    ]

    # 最长/最短章节
    longest_chapter = None
    shortest_chapter = None
    if chapter_word_counts:
        longest = max(chapter_word_counts, key=lambda x: x["words"])
        shortest = min(chapter_word_counts, key=lambda x: x["words"])
        longest_chapter = {"name": longest["name"], "words": longest["words"]}
        shortest_chapter = {"name": shortest["name"], "words": shortest["words"]}

    # 平均每章字数
    average_words_per_chapter = round(total_words / total_chapters) if total_chapters > 0 else 0

    # ─── 角色统计 ───
    characters_data = _load_json_safe(BASE / "characters" / f"{project_id}.json")
    total_characters = 0
    if isinstance(characters_data, dict):
        total_characters = len(characters_data.get("characters", []))

    # ─── 场景统计 ───
    scenes_dir = BASE / "scenes"
    total_scenes = 0
    if scenes_dir.is_dir():
        for sf in scenes_dir.iterdir():
            if sf.suffix.lower() == ".json" and sf.is_file():
                scenes_data = _load_json_safe(sf)
                if isinstance(scenes_data, list):
                    total_scenes += len(scenes_data)

    # ─── 伏笔统计 ───
    foreshadow_data = _load_json_safe(BASE / "foreshadowing" / f"{project_id}.json")
    total_foreshadowing = 0
    if isinstance(foreshadow_data, list):
        total_foreshadowing = len(foreshadow_data)

    # ─── 连续写作天数 ───
    daily_dates = set()
    for d in daily_map:
        daily_dates.add(datetime.strptime(d, "%Y-%m-%d").date())
    streak_days = _compute_streak(daily_dates)

    return {
        "total_chapters": total_chapters,
        "total_words": total_words,
        "total_characters": total_characters,
        "total_scenes": total_scenes,
        "total_foreshadowing": total_foreshadowing,
        "daily_stats": daily_stats,
        "average_words_per_chapter": average_words_per_chapter,
        "longest_chapter": longest_chapter,
        "shortest_chapter": shortest_chapter,
        "streak_days": streak_days
    }
