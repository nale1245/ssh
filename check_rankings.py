#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_rankings.py —— 阶段 1 数据验收自检（独立于爬虫，可反复执行）

用法：
    python check_rankings.py
    python check_rankings.py --csv data/rankings_raw.csv

逐项打印验收结论，并以退出码表示是否通过（0 通过 / 1 不通过），
便于阶段交付时直接贴结果、也便于后续人工复核。
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "rankings_raw.csv"

EXPECTED_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]
REQUIRED_FIELDS = ["year", "rank", "univ_name", "univ_slug", "province", "univ_type"]
TEXT_FIELDS = ["univ_name", "univ_name_en", "province", "univ_type", "level"]
OPTIONAL_FIELDS = {"score_research", "score_talent", "score_social", "level",
                   "score_total"}  # score_total 对 500+ 学校天然为空，行级完整性单列检查
REPLACEMENT_CHAR = "\ufffd"


def load_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or [])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="阶段 1 数据验收自检")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="待检查的 CSV 路径")
    parser.add_argument("--min-rows", type=int, default=2500, help="最少行数")
    args = parser.parse_args(argv)

    path = Path(args.csv)
    print("=" * 70)
    print("阶段 1 验收自检：%s" % path)
    print("=" * 70)

    if not path.exists():
        print("❌ 文件不存在")
        return 1

    rows, fields = load_rows(path)
    ok = True
    print("文件大小：%.1f KB" % (path.stat().st_size / 1024))
    print("表头（%d 列）：%s" % (len(fields), ", ".join(fields)))
    print("数据行数：%d" % len(rows))
    print()

    # 1) 行数
    if len(rows) >= args.min_rows:
        print("✅ [行数] %d >= %d" % (len(rows), args.min_rows))
    else:
        print("❌ [行数] %d < %d" % (len(rows), args.min_rows))
        ok = False

    # 2) 表头完整性
    missing_cols = [c for c in REQUIRED_FIELDS if c not in fields]
    if missing_cols:
        print("❌ [表头] 缺少字段：%s" % missing_cols)
        ok = False
    else:
        print("✅ [表头] 必需字段齐全（%s）" % ", ".join(REQUIRED_FIELDS))

    # 3) 年份覆盖
    per_year = Counter(r["year"] for r in rows)
    for year in EXPECTED_YEARS:
        n = per_year.get(str(year), 0)
        flag = "✅" if n >= 500 else "❌"
        print("%s [年份] %d：%d 条" % (flag, year, n))
        ok = ok and n >= 500

    # 4) 关键字段非空率
    total = len(rows) or 1
    print()
    print("字段非空率：")
    for field in fields:
        filled = sum(1 for r in rows if (r.get(field) or "").strip())
        rate = filled / total
        if rate >= 0.999:
            mark = "✅"
        elif field in OPTIONAL_FIELDS:
            mark = "⚠️ "
        else:
            mark = "❌"
            ok = False
        print("  %s %-14s %6.2f%%  (%d/%d)" % (mark, field, rate * 100, filled, total))

    # 5) 有名次记录的总分完整性
    ranked = [r for r in rows if r["rank"].isdigit()]
    ranked_ok = sum(1 for r in ranked if (r.get("score_total") or "").strip())
    if ranked and ranked_ok == len(ranked):
        print()
        print("✅ [总分] 有名次记录 100%% 有分数（%d/%d）" % (ranked_ok, len(ranked)))
    else:
        print()
        print("❌ [总分] 有名次记录分数缺失：%d/%d" % (ranked_ok, len(ranked)))
        ok = False

    # 6) 乱码检测
    bad = [r for r in rows if REPLACEMENT_CHAR in "".join((r.get(f) or "") for f in TEXT_FIELDS)]
    if bad:
        print("❌ [乱码] 发现 %d 条疑似乱码" % len(bad))
        ok = False
    else:
        print("✅ [乱码] 未发现 U+FFFD 替换字符")

    # 7) 重复检测
    seen = set()
    dup = 0
    for r in rows:
        key = (r.get("univ_slug") or r.get("univ_name"), r.get("year"))
        if key in seen:
            dup += 1
        seen.add(key)
    if dup:
        print("⚠️  [重复] (学校, 年份) 重复 %d 条（阶段 2 去重）" % dup)
    else:
        print("✅ [重复] (学校, 年份) 无重复")

    print()
    print("统计：%d 所学校 / %d 个年份 / %d 条记录"
          % (len({r.get("univ_slug") for r in rows}), len(per_year), len(rows)))

    header = ["year", "rank", "univ_name", "province", "univ_type", "level",
              "score_total", "score_research", "stars"]
    print()
    print("抽样 5 行：")
    print("  " + " | ".join(header))
    for r in rows[:5]:
        print("  " + " | ".join((r.get(h) or "-") for h in header))

    print()
    print("=" * 70)
    if ok:
        print("结论：✅ 通过验收（行数 / 表头 / 年份 / 关键字段 / 乱码 全部达标）")
    else:
        print("结论：❌ 未通过，请查看上面标红的项")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
