#!/usr/bin/env python3
"""
费曼导师笔记系统结构迁移脚本

从旧扁平结构迁移到新树形结构：

  旧：
    notes/
    ├── INDEX.md
    ├── LEARNER.md
    ├── GRAPH.md
    └── {topic}.md（全部平铺）

  新：
    notes/
    ├── INDEX.md                   （四表结构）
    ├── learner-core.md            （原 LEARNER.md）
    ├── learner-history.md         （新建）
    ├── cross-domain/{pattern}.md  （从 GRAPH.md 的"连接"章节拆出 — 导师完成）
    └── domains/{slug}/
        ├── domain.md              （从 GRAPH.md 的"领域框架"章节拆出 — 导师完成）
        └── {topic}.md             （按 frontmatter 里 domain 字段分类）

脚本只做机械迁移（备份 / 移动文件 / 重写 INDEX.md / 重命名 learner 文件）。
语义迁移（拆分 GRAPH.md、补全话题笔记的 cross-domain-patterns / related-topics 指针）
由费曼导师在下次学习时根据 .migration-pending.json 完成。

幂等：重复运行安全。已是新结构时直接退出，不动数据。

用法：
    python scripts/migrate_legacy_notes.py           # 执行迁移
    python scripts/migrate_legacy_notes.py --check   # 仅检测结构状态，不执行
    python scripts/migrate_legacy_notes.py --dry-run # 打印将要做的事，不写入
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Optional

# Windows UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


# ---------- 领域映射表 ----------
# 顺序有意义：更具体/更长的关键词放前面。
# 判据依据当前仓库里维护的新 INDEX.md 实际归类。
KEYWORD_TO_SLUG: list[tuple[str, str]] = [
    ("产品管理/产品方法论", "product-management"),
    ("AI 产品管理", "ai-product-management"),
    ("AI/深度学习", "ai-deep-learning"),
    ("AI/Agent 工程", "ai-agent-engineering"),
    ("AI/对齐与安全", "ai-agent-engineering"),
    ("游戏系统设计", "game-system-design"),
    ("游戏开发工作流", "game-system-design"),
    ("产品方法论", "product-management"),
    ("产品管理", "product-management"),
    ("深度学习", "ai-deep-learning"),
    ("Agent 工程", "ai-agent-engineering"),
    ("上下文工程", "ai-agent-engineering"),
    ("Harness", "ai-agent-engineering"),
    ("软件工程", "software-engineering"),
    ("学习科学", "learning-science"),
    ("社会心理学", "communication"),
    ("传播学", "communication"),
    ("哲学", "philosophy"),
    ("护肤", "skincare"),
    ("美妆", "skincare"),
    ("数学", "mathematics"),
    ("游戏", "game-system-design"),
]

SLUG_TO_DISPLAY_NAME: dict[str, str] = {
    "ai-deep-learning": "AI/深度学习",
    "ai-agent-engineering": "AI/Agent 工程",
    "ai-product-management": "AI 产品管理",
    "product-management": "产品管理",
    "game-system-design": "游戏系统设计",
    "software-engineering": "软件工程",
    "skincare": "护肤",
    "communication": "传播学",
    "philosophy": "哲学",
    "learning-science": "学习科学",
    "mathematics": "数学基础",
}


def classify_domain(domain_field: str) -> Optional[str]:
    """根据旧 domain 字段（自由格式中文）判断新 slug。"""
    if not domain_field:
        return None
    # 先在主领域段（× 前第一段）里找
    primary = re.split(r"\s*×\s*", domain_field.strip())[0]
    primary_clean = re.sub(r"[（(].*?[）)]", "", primary).strip()
    for keyword, slug in KEYWORD_TO_SLUG:
        if keyword in primary_clean:
            return slug
    # 退而求其次，在完整 domain_field 里找
    for keyword, slug in KEYWORD_TO_SLUG:
        if keyword in domain_field:
            return slug
    return None


# ---------- 结构检测 ----------

def detect_structure(notes_dir: Path) -> str:
    """返回 'new' | 'legacy' | 'mixed' | 'empty'."""
    if not notes_dir.exists():
        return "empty"
    has_legacy = (notes_dir / "LEARNER.md").exists() or (notes_dir / "GRAPH.md").exists()
    has_new = (notes_dir / "learner-core.md").exists() or (notes_dir / "domains").is_dir()
    if has_legacy and has_new:
        return "mixed"
    if has_legacy:
        return "legacy"
    if has_new:
        return "new"
    # 既无旧元文件也无新目录——可能是全新空仓库，或只有 .gitkeep
    md_files = list(notes_dir.glob("*.md"))
    if not md_files:
        return "empty"
    # 存在若干 .md 但没有 LEARNER/GRAPH——视作旧结构的退化情形
    return "legacy"


# ---------- frontmatter 解析 ----------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    """极简 YAML-ish frontmatter 解析。只处理 key: value 形式的顶层字段。"""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith((" ", "-", "\t")):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


# ---------- 主流程 ----------

META_FILES = {"INDEX.md", "LEARNER.md", "GRAPH.md", "learner-core.md", "learner-history.md"}


def find_legacy_topics(notes_dir: Path) -> list[Path]:
    """旧结构下，除了元文件以外根目录下的所有 .md 就是话题笔记。"""
    return sorted(
        p for p in notes_dir.glob("*.md")
        if p.name not in META_FILES and not p.name.startswith(".")
    )


def plan_migration(notes_dir: Path) -> dict:
    """生成迁移计划，不实际执行。"""
    topics = find_legacy_topics(notes_dir)
    moves: list[dict] = []
    unknown: list[dict] = []

    for topic_path in topics:
        try:
            text = topic_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            unknown.append({"file": topic_path.name, "reason": "无法以 UTF-8 解码"})
            continue
        fm = parse_frontmatter(text)
        domain_field = fm.get("domain", "")
        slug = classify_domain(domain_field)
        if slug:
            moves.append({
                "file": topic_path.name,
                "old_domain": domain_field,
                "new_slug": slug,
                "target": f"domains/{slug}/{topic_path.name}",
            })
        else:
            unknown.append({
                "file": topic_path.name,
                "reason": f"domain 字段 '{domain_field}' 无法匹配任何已知领域",
            })

    return {
        "topics_found": len(topics),
        "moves": moves,
        "unknown_topics": unknown,
        "has_learner": (notes_dir / "LEARNER.md").exists(),
        "has_graph": (notes_dir / "GRAPH.md").exists(),
        "has_index": (notes_dir / "INDEX.md").exists(),
    }


def backup_notes(notes_dir: Path, dry_run: bool = False) -> Path:
    """将 notes/ 目录整体重命名为 notes-backup-YYYYMMDD/（如果同日备份已存在则加序号）。"""
    parent = notes_dir.parent
    today = date.today().strftime("%Y%m%d")
    backup_dir = parent / f"notes-backup-{today}"
    suffix = 1
    while backup_dir.exists():
        suffix += 1
        backup_dir = parent / f"notes-backup-{today}-{suffix}"
    print(f"[备份] {notes_dir} → {backup_dir}")
    if not dry_run:
        shutil.move(str(notes_dir), str(backup_dir))
    return backup_dir


def rebuild_skeleton(notes_dir: Path, plan: dict, dry_run: bool = False) -> None:
    """创建新 notes/ 目录结构。"""
    print(f"[骨架] 创建 {notes_dir}/, domains/, cross-domain/")
    if dry_run:
        return
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "domains").mkdir(exist_ok=True)
    (notes_dir / "cross-domain").mkdir(exist_ok=True)
    # 为每个出现的 slug 预创建目录
    slugs_used = {m["new_slug"] for m in plan["moves"]}
    for slug in sorted(slugs_used):
        (notes_dir / "domains" / slug).mkdir(exist_ok=True)


def copy_learner(backup_dir: Path, notes_dir: Path, dry_run: bool = False) -> bool:
    """LEARNER.md → learner-core.md；生成空 learner-history.md 骨架。"""
    src = backup_dir / "LEARNER.md"
    if not src.exists():
        print("[学习者模型] 未发现 LEARNER.md，跳过")
        return False
    dst = notes_dir / "learner-core.md"
    print(f"[学习者模型] {src.name} → {dst.name}")
    if not dry_run:
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    history = notes_dir / "learner-history.md"
    print(f"[学习者模型] 生成 {history.name} 骨架")
    if not dry_run:
        history.write_text(
            "---\n"
            "type: learner-history\n"
            f"last_updated: {date.today().isoformat()}\n"
            "sessions_count: 0\n"
            "---\n\n"
            "# 认知成长轨迹\n\n"
            "> 按时间线记录每次学习的认知路径和标志性特征。\n"
            "> 迁移自旧结构：历史记录需要从 notes-backup 里 LEARNER.md 的学习记录手动回填，"
            "或等导师在后续学习中增量累积。\n\n",
            encoding="utf-8",
        )
    return True


def copy_topics(backup_dir: Path, notes_dir: Path, plan: dict, dry_run: bool = False) -> None:
    """按计划把话题笔记移到 domains/{slug}/。"""
    for move in plan["moves"]:
        src = backup_dir / move["file"]
        dst = notes_dir / "domains" / move["new_slug"] / move["file"]
        print(f"[话题] {move['file']}  →  domains/{move['new_slug']}/")
        if not dry_run:
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def write_index(notes_dir: Path, plan: dict, dry_run: bool = False) -> None:
    """写新的 INDEX.md —— 四表结构。"""
    # 统计每个 slug 下的话题
    slug_to_topics: dict[str, list[dict]] = {}
    for m in plan["moves"]:
        slug_to_topics.setdefault(m["new_slug"], []).append(m)

    lines: list[str] = []
    lines.append("# 费曼学习笔记索引")
    lines.append("")
    lines.append("## 元文件")
    lines.append("| 文件 | 用途 |")
    lines.append("|------|------|")
    lines.append("| learner-core.md | 学习者核心模型（认知风格、盲区、有效策略） |")
    lines.append("| learner-history.md | 认知成长轨迹（按时间线） |")
    lines.append("")

    lines.append("## 领域目录")
    lines.append("| 领域 | 路径 | 话题数 |")
    lines.append("|------|------|--------|")
    for slug in sorted(slug_to_topics.keys()):
        display = SLUG_TO_DISPLAY_NAME.get(slug, slug)
        count = len(slug_to_topics[slug])
        lines.append(f"| {display} | domains/{slug}/ | {count} |")
    lines.append("")

    lines.append("## 话题索引")
    lines.append("| 话题 | 领域 | 文件路径 |")
    lines.append("|------|------|----------|")
    for slug in sorted(slug_to_topics.keys()):
        display = SLUG_TO_DISPLAY_NAME.get(slug, slug)
        for m in slug_to_topics[slug]:
            # 从 file 名推出话题名：去掉 .md
            topic_name = m["file"].removesuffix(".md")
            # 尝试读原始 frontmatter 的 topic 字段作为显示名
            src = notes_dir / "domains" / slug / m["file"]
            display_topic = topic_name
            if src.exists():
                fm = parse_frontmatter(src.read_text(encoding="utf-8"))
                display_topic = fm.get("topic", topic_name)
            lines.append(f"| {display_topic} | {display} | domains/{slug}/{m['file']} |")
    lines.append("")

    lines.append("## 跨领域模式索引")
    lines.append("| 模式 | 类型 | 文件路径 |")
    lines.append("|------|------|----------|")
    lines.append("| _（迁移中——导师会从 GRAPH.md 拆出独立的 cross-domain 文件后填入）_ | | |")
    lines.append("")

    content = "\n".join(lines)
    target = notes_dir / "INDEX.md"
    print(f"[索引] 写入 {target.name}")
    if not dry_run:
        target.write_text(content, encoding="utf-8")


def write_pending_marker(notes_dir: Path, backup_dir: Path, plan: dict, dry_run: bool = False) -> None:
    """写 .migration-pending.json，告诉导师还有哪些语义任务要做。"""
    pending = {
        "migrated_at": date.today().isoformat(),
        "backup_dir": backup_dir.name,
        "tasks": {
            "extract_cross_domain_patterns": {
                "status": "pending",
                "source": f"{backup_dir.name}/GRAPH.md",
                "source_section": "一、连接",
                "target_dir": "cross-domain/",
                "instruction": (
                    "读 GRAPH.md 的「一、连接」章节，按"
                    "【结构类比 / 共同模式 / 认知迁移 / 张力·矛盾】四类拆成独立文件。"
                    "每个模式一个 cross-domain/{中文模式名}.md，"
                    "保留原文全部内容 + 加 frontmatter（type / category / related-domains / related-topics）。"
                ),
            },
            "extract_domain_frameworks": {
                "status": "pending",
                "source": f"{backup_dir.name}/GRAPH.md",
                "source_section": "二、领域框架",
                "target_pattern": "domains/{slug}/domain.md",
                "instruction": (
                    "读 GRAPH.md 的「二、领域框架」章节，按领域标题"
                    "（AI/深度学习、AI/Agent 工程、软件工程…）拆到对应的 domains/{slug}/domain.md。"
                    "每个 domain.md 加 frontmatter（type: domain / domain: {slug} / topic-count: N）。"
                    "若 GRAPH.md 的「三、前沿」有关联条目，也归入主要领域的 domain.md 底部。"
                ),
            },
            "backfill_topic_pointers": {
                "status": "pending",
                "strategy": "lazy",
                "instruction": (
                    "不做一次性批量补全。每当用户下次学习某个话题、导师加载该话题笔记时，"
                    "若发现 frontmatter 缺 cross-domain-patterns 或 related-topics 字段，"
                    "扫描 backup GRAPH.md 中提到该话题的连接条目，"
                    "在本次笔记保存阶段顺手补上指针。"
                ),
                "topics_needing_pointers": [m["file"].removesuffix(".md") for m in plan["moves"]],
            },
            "rewrite_index_cross_domain_table": {
                "status": "pending",
                "instruction": (
                    "extract_cross_domain_patterns 完成后，"
                    "把生成的每个 cross-domain/*.md 追加到 INDEX.md 的「跨领域模式索引」表。"
                ),
            },
        },
        "unknown_topics": plan["unknown_topics"],
    }
    target = notes_dir / ".migration-pending.json"
    print(f"[标记] 写入 {target.name}")
    if not dry_run:
        target.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")


def run_migration(notes_dir: Path, dry_run: bool = False) -> int:
    state = detect_structure(notes_dir)
    if state == "new":
        print("[OK] 笔记已是新结构，无需迁移。")
        return 0
    if state == "empty":
        print("[OK] 笔记目录为空——首次使用，无需迁移（导师会按新结构累积）。")
        return 0
    if state == "mixed":
        print("[错误] 检测到混合状态：LEARNER.md/GRAPH.md 与 learner-core.md/domains 同时存在。")
        print("      为避免覆盖数据，脚本拒绝自动处理。请手动清理后再跑。")
        return 2

    # state == "legacy"
    print(f"[检测] 发现旧结构笔记于 {notes_dir}")
    plan = plan_migration(notes_dir)
    print(f"       话题笔记 {plan['topics_found']} 个")
    print(f"       可分类 {len(plan['moves'])} 个，无法分类 {len(plan['unknown_topics'])} 个")
    if plan["unknown_topics"]:
        print("       无法分类的（将留在 backup，.migration-pending.json 会记录）：")
        for u in plan["unknown_topics"]:
            print(f"         - {u['file']}：{u['reason']}")

    if dry_run:
        print("\n[dry-run] 以上为计划，未写入任何文件。")
        return 0

    print()
    backup_dir = backup_notes(notes_dir, dry_run=False)
    rebuild_skeleton(notes_dir, plan, dry_run=False)
    copy_learner(backup_dir, notes_dir, dry_run=False)
    copy_topics(backup_dir, notes_dir, plan, dry_run=False)
    write_index(notes_dir, plan, dry_run=False)
    write_pending_marker(notes_dir, backup_dir, plan, dry_run=False)

    print()
    print("=" * 60)
    print("机械迁移完成。")
    print(f"  原始笔记备份在：{backup_dir}")
    print(f"  新结构在：      {notes_dir}")
    print(f"  剩余语义任务记录在：{notes_dir}/.migration-pending.json")
    print()
    print("下次调用费曼导师（feynman-tutor）时，导师会：")
    print("  1. 检测 .migration-pending.json 存在 → 执行 GRAPH.md 的语义拆分")
    print("  2. 把「一、连接」里的模式拆到 cross-domain/*.md")
    print("  3. 把「二、领域框架」里的各领域 checklist 拆到 domains/{slug}/domain.md")
    print("  4. 话题笔记的跨域指针会在下次学到该话题时惰性补全")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--notes-dir",
        type=Path,
        default=None,
        help="笔记目录路径。默认自动定位为脚本所在仓库的 notes/",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写任何文件")
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检测结构状态，退出码：0=新结构 / 1=旧结构 / 2=混合 / 3=空",
    )
    args = parser.parse_args()

    # 定位 notes/：默认是脚本所在目录的上一级下的 notes/
    if args.notes_dir:
        notes_dir = args.notes_dir.resolve()
    else:
        notes_dir = (Path(__file__).resolve().parent.parent / "notes").resolve()

    if args.check:
        state = detect_structure(notes_dir)
        print(f"结构状态：{state}（路径：{notes_dir}）")
        return {"new": 0, "legacy": 1, "mixed": 2, "empty": 3}[state]

    return run_migration(notes_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
