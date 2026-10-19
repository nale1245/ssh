#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
spider_ranking.py —— 软科中国大学排名（主榜）原始数据采集

项目：全国大学数据分析大屏（设计文档 v2 / F01 / 阶段 1）
目标：采集 2021-2026 共 6 年软科中国大学排名主榜（bcur_type=11）数据，
      输出 data/rankings_raw.csv（UTF-8-SIG，英文表头，一行 = 一所学校一年的记录）。

数据来源（公开接口，页面同源）：
    https://www.shanghairanking.cn/api/pub/v1/bcur?bcur_type=11&year=<YYYY>

字段说明见 README 或运行 --help；本脚本只做"采集 + 字段展开"，
不做去重、缺失值填充、类型清洗（那属于阶段 2 load_data.py 的职责）。

用法：
    python spider_ranking.py                     # 采集 2021-2026，默认请求间隔 1.2s
    python spider_ranking.py --years 2024-2026   # 只采集部分年份
    python spider_ranking.py --from-cache        # 不联网，用本地 JSON 缓存重建 CSV
    python spider_ranking.py --no-cache          # 强制联网并覆盖缓存

输出：
    data/rankings_raw.csv     主交付物
    data/raw_json/*.json      每年接口原始响应（可复现，便于排错）
    data/crawl_meta.json      本次采集的元信息与字段完整率
    logs/spider_ranking.log   运行日志
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# --------------------------------------------------------------------------- #
# 常量配置
# --------------------------------------------------------------------------- #
BASE_URL = "https://www.shanghairanking.cn"
API_URL = BASE_URL + "/api/pub/v1/bcur"
BCUR_TYPE_MAIN = 11  # 11 = 中国大学排名主榜

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_JSON_DIR = DATA_DIR / "raw_json"
LOG_DIR = PROJECT_ROOT / "logs"
CSV_PATH = DATA_DIR / "rankings_raw.csv"
META_PATH = DATA_DIR / "crawl_meta.json"

# CSV 表头（英文，便于 pandas / MySQL 读取；顺序即列顺序）
CSV_FIELDS = [
    "year",            # 年份
    "rank",            # 当年排名（原始值，可能为 "500+"）
    "univ_name",       # 学校名（中文）
    "univ_name_en",    # 学校名（英文）
    "univ_slug",       # 学校唯一标识（软科 univUp，用于跨年关联）
    "province",        # 省份
    "city",            # 城市（软科不提供，阶段 2 补充，本阶段留空）
    "univ_type",       # 类型（综合/理工/师范/农业/林业）
    "level",           # 层次标签（985/211/双一流，多个用 / 连接）
    "is_985",          # 是否 985（0/1）
    "is_211",          # 是否 211（0/1）
    "is_double",       # 是否双一流（0/1）
    "score_total",     # 总分
    "score_research",  # 科研得分（科学研究）
    "score_talent",    # 人才培养得分
    "score_social",    # 社会服务得分（服务社会）
    "stars",           # 星级 1-5（软科未发布，按排名分段映射，规则见 stars_for_rank）
]

# 指标中文名 -> CSV 字段名
INDICATOR_FIELDS = {
    "科学研究": "score_research",
    "人才培养": "score_talent",
    "服务社会": "score_social",
}

# level 标签的输出顺序
TAG_ORDER = ["985", "211", "双一流"]

logger = logging.getLogger("spider_ranking")


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    """控制台 + 文件双写日志。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.FileHandler(
        LOG_DIR / "spider_ranking.log", mode="a", encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)


def parse_years(spec: str) -> list[int]:
    """解析 --years 参数：支持 '2021-2026'、'2021,2024'、'2023' 及其组合。"""
    years: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start, end = chunk.split("-", 1)
            a, b = int(start), int(end)
            if a > b:
                a, b = b, a
            years.extend(range(a, b + 1))
        else:
            years.append(int(chunk))
    if not years:
        raise ValueError("未解析到任何年份：%r" % spec)
    return sorted(set(years))


def to_float(value) -> float | None:
    """把接口返回的字符串数值转为 float；空串/None/非法值返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def stars_for_rank(rank_raw: str) -> int:
    """
    软科主榜不发布星级，这里按排名分段映射为 1-5 星（仅用于本项目展示维度）：
        第 1-10 名 -> 5 星
        第 11-50 名 -> 4 星
        第 51-200 名 -> 3 星
        第 201-500 名 -> 2 星
        500+ / 无排名 -> 1 星
    说明：该列属于派生字段，不是软科官方数据。
    """
    text = str(rank_raw or "").strip()
    if not text:
        return 1
    if text.endswith("+"):
        return 1
    try:
        n = int(text)
    except ValueError:
        return 1
    if n <= 10:
        return 5
    if n <= 50:
        return 4
    if n <= 200:
        return 3
    if n <= 500:
        return 2
    return 1


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
    )
    return session


# --------------------------------------------------------------------------- #
# 采集
# --------------------------------------------------------------------------- #
def fetch_year(session: requests.Session, year: int, delay: float, retries: int = 3) -> dict:
    """请求某一年榜单接口，返回完整 JSON（含 data/rankings 等）。"""
    params = {"bcur_type": BCUR_TYPE_MAIN, "year": year}
    headers = {"Referer": BASE_URL + "/rankings/bcur/%d" % year}

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(API_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 200:
                raise RuntimeError(
                    "接口返回异常 code=%r msg=%r" % (payload.get("code"), payload.get("msg"))
                )
            rankings = (payload.get("data") or {}).get("rankings") or []
            if not rankings:
                raise RuntimeError("接口返回 rankings 为空")
            return payload
        except Exception as exc:  # noqa: BLE001 - 网络异常统一重试
            last_error = exc
            logger.warning("年份 %d 第 %d/%d 次请求失败：%s", year, attempt, retries, exc)
            if attempt < retries:
                time.sleep(delay * attempt + random.uniform(0, 1.0))

    raise RuntimeError("年份 %d 采集失败，已重试 %d 次：%s" % (year, retries, last_error))


def load_or_fetch(
    session: requests.Session, year: int, use_cache: bool, delay: float, retries: int
) -> dict:
    """优先读本地缓存（unless 强制刷新），否则联网采集并落盘。"""
    cache_file = RAW_JSON_DIR / ("bcur_%d.json" % year)
    if use_cache and cache_file.exists():
        logger.info("年份 %d：命中本地缓存 %s", year, cache_file.relative_to(PROJECT_ROOT))
        with cache_file.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    logger.info("年份 %d：请求接口 ...", year)
    payload = fetch_year(session, year, delay, retries)
    RAW_JSON_DIR.mkdir(parents=True, exist_ok=True)
    with cache_file.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    logger.info(
        "年份 %d：采集 %d 条，已缓存 %s",
        year,
        len(payload["data"]["rankings"]),
        cache_file.relative_to(PROJECT_ROOT),
    )
    return payload


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #
def indicator_code_map(payload: dict) -> dict[str, str]:
    """从 inds 元数据中取「指标中文名 -> 指标 code」映射（每年 code 不同，不能写死）。"""
    mapping: dict[str, str] = {}
    for item in (payload.get("data") or {}).get("inds") or []:
        name = item.get("nameCn")
        code = item.get("code")
        if name and code:
            mapping[name] = str(code)
    return mapping


def parse_year(payload: dict, year: int) -> list[dict]:
    """把一年接口响应展开为 CSV 行。"""
    data = payload.get("data") or {}
    ind_map = indicator_code_map(payload)
    unknown = [name for name in INDICATOR_FIELDS if name not in ind_map]
    if unknown:
        logger.warning("年份 %d：指标元数据缺失 %s，对应得分列将为空", year, unknown)

    rows: list[dict] = []
    for item in data.get("rankings") or []:
        tags = [str(t) for t in (item.get("univTags") or [])]
        level = "/".join([t for t in TAG_ORDER if t in tags])
        ind_data = item.get("indData") or {}

        row = {
            "year": year,
            "rank": str(item.get("ranking") or "").strip(),
            "univ_name": (item.get("univNameCn") or "").strip(),
            "univ_name_en": (item.get("univNameEn") or "").strip(),
            "univ_slug": (item.get("univUp") or "").strip(),
            "province": (item.get("province") or "").strip(),
            "city": "",  # 软科接口/详情页均不提供城市，阶段 2 统一补充
            "univ_type": (item.get("univCategory") or "").strip(),
            "level": level,
            "is_985": int("985" in tags),
            "is_211": int("211" in tags),
            "is_double": int("双一流" in tags),
            "score_total": to_float(item.get("score")),
            "stars": stars_for_rank(item.get("ranking")),
        }
        for name, field in INDICATOR_FIELDS.items():
            code = ind_map.get(name)
            row[field] = to_float(ind_data.get(code)) if code else None
        rows.append(row)

    # 排序：名次升序，500+ 排最后，同名次按校名
    def sort_key(r: dict):
        raw = r["rank"]
        if raw.isdigit():
            return (0, int(raw), r["univ_name"])
        return (1, 10**9, r["univ_name"])

    rows.sort(key=sort_key)
    return rows


# --------------------------------------------------------------------------- #
# 输出与校验
# --------------------------------------------------------------------------- #
def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig：带 BOM，Excel 直接双击打开不乱码；pandas 需 encoding="utf-8-sig"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def completeness_report(rows: list[dict]) -> dict:
    """统计每个字段的非空率，用于自检与写元信息。"""
    total = len(rows) or 1
    report = {}
    for field in CSV_FIELDS:
        filled = sum(
            1
            for r in rows
            if r.get(field) not in (None, "", "None")
        )
        report[field] = round(filled / total, 4)
    return report


def verify(rows: list[dict], years: list[int]) -> bool:
    """
    阶段 1 验收自检。

    检查口径（重要，避免误报）：
      - 必需字段 year/rank/univ_name/univ_slug/province/univ_type：要求 100% 非空；
      - 总分 score_total：只在「有具体名次」的学校上要求 100%（软科对 500+ 学校不发布分数）；
      - 科研/人才培养/社会服务：软科只发布前 100 名的分项，覆盖率仅作提示，不计失败；
      - 城市 city：软科接口与详情页均不提供，本阶段留空，作为已知缺口提示。
    """
    logger.info("=" * 62)
    logger.info("自检开始")
    ok = True

    # 1) 行数
    if len(rows) >= 2500:
        logger.info("✅ 总行数 %d（要求 >= 2500）", len(rows))
    else:
        logger.error("❌ 总行数 %d（要求 >= 2500）", len(rows))
        ok = False

    # 2) 年份覆盖
    counts: dict[int, int] = {}
    for r in rows:
        counts[r["year"]] = counts.get(r["year"], 0) + 1
    for year in years:
        n = counts.get(year, 0)
        if n >= 500:
            logger.info("✅ %d 年 %d 条（要求 >= 500）", year, n)
        else:
            logger.error("❌ %d 年 %d 条（要求 >= 500）", year, n)
            ok = False

    # 3) 必需字段非空
    completeness = completeness_report(rows)
    for field in ["year", "rank", "univ_name", "univ_slug", "province", "univ_type"]:
        rate = completeness[field]
        if rate >= 0.999:
            logger.info("✅ 字段 %-12s 非空率 %.2f%%", field, rate * 100)
        else:
            logger.error("❌ 字段 %-12s 非空率 %.2f%%（要求 100%%）", field, rate * 100)
            ok = False

    # 4) 总分：只在有名次的记录上要求完整
    ranked = [r for r in rows if str(r.get("rank", "")).isdigit()]
    ranked_filled = sum(1 for r in ranked if r.get("score_total") is not None)
    ranked_rate = ranked_filled / len(ranked) if ranked else 0
    if ranked_rate >= 0.999:
        logger.info("✅ 有名次记录总分完整率 %.2f%%（%d/%d）", ranked_rate * 100, ranked_filled, len(ranked))
    else:
        logger.error("❌ 有名次记录总分完整率 %.2f%%（%d/%d）", ranked_rate * 100, ranked_filled, len(ranked))
        ok = False

    # 5) 分项得分覆盖率（数据源只发布前 100 名，仅提示）
    for field in ("score_research", "score_talent", "score_social"):
        logger.info("ℹ️  字段 %-14s 覆盖率 %.2f%%（软科仅发布前 100 名分项，正常）",
                    field, completeness[field] * 100)

    # 6) 城市：软科不提供，已知缺口
    logger.info("⚠️  字段 city         非空率 %.2f%%（软科无城市字段，阶段 2 补充）",
                completeness["city"] * 100)

    # 7) 中文乱码检测（UTF-8 解码失败的替换字符）
    bad = [r for r in rows if "\ufffd" in str(r.get("univ_name", ""))]
    if bad:
        logger.error("❌ 检测到 %d 条疑似乱码记录", len(bad))
        ok = False
    else:
        logger.info("✅ 无乱码（未发现 U+FFFD 替换字符）")

    # 5) 主键唯一性提示（同一学校同一年不应重复）
    seen: set[tuple[str, int]] = set()
    dup = 0
    for r in rows:
        key = (r["univ_slug"] or r["univ_name"], r["year"])
        if key in seen:
            dup += 1
        seen.add(key)
    if dup:
        logger.warning("⚠️  发现 %d 条 (学校, 年份) 重复记录，阶段 2 清洗时去重", dup)
    else:
        logger.info("✅ (学校, 年份) 无重复")

    logger.info("自检结论：%s", "通过" if ok else "未通过")
    logger.info("=" * 62)
    return ok


def save_meta(rows: list[dict], years: list[int], elapsed: float, path: Path) -> None:
    per_year: dict[int, int] = {}
    for r in rows:
        per_year[r["year"]] = per_year.get(r["year"], 0) + 1
    meta = {
        "source": API_URL + "?bcur_type=%d" % BCUR_TYPE_MAIN,
        "crawled_at": datetime.now().isoformat(timespec="seconds"),
        "years": years,
        "total_rows": len(rows),
        "rows_per_year": {str(k): v for k, v in sorted(per_year.items())},
        "unique_schools": len({r["univ_slug"] or r["univ_name"] for r in rows}),
        "elapsed_seconds": round(elapsed, 2),
        "field_completeness": completeness_report(rows),
        "notes": {
            "city": "软科排名接口与学校详情页均不提供城市，本阶段留空，阶段 2 统一补全",
            "stars": "软科主榜不发布星级，按排名分段映射（1-10=>5, 11-50=>4, 51-200=>3, 201-500=>2, 500+=>1）",
            "rank": "保留原始值，含 '500+' 这种区间写法，阶段 2 清洗为整数",
            "sub_scores": "科研/人才培养/社会服务分项软科仅发布前 100 名，排名 100 之后的学校该三列为空",
            "score_total": "排名 500+ 的学校软科不发布总分，score_total 为空",
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)


def print_sample(rows: list[dict], n: int = 5) -> None:
    logger.info("抽样 %d 行：", n)
    for r in rows[:n]:
        logger.info(
            "  %s | %-3s | %-12s | %-4s | %-4s | %-5s | 总分 %-7s | 科研 %-6s | 人才 %-6s | 社会 %-6s | %s星",
            r["year"], r["rank"], r["univ_name"], r["province"], r["univ_type"],
            r["level"] or "-", r["score_total"], r["score_research"],
            r["score_talent"], r["score_social"], r["stars"],
        )


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="采集软科中国大学排名主榜（2021-2026）原始数据 -> data/rankings_raw.csv"
    )
    parser.add_argument("--years", default="2021-2026", help="年份，如 2021-2026 或 2024,2025")
    parser.add_argument("--delay", type=float, default=1.2, help="两次请求间隔秒数（1-2 秒防封）")
    parser.add_argument("--retries", type=int, default=3, help="单年请求失败重试次数")
    parser.add_argument("--from-cache", action="store_true", help="只用本地 JSON 缓存，不联网")
    parser.add_argument("--no-cache", action="store_true", help="强制联网并覆盖 JSON 缓存")
    parser.add_argument("--out", default=str(CSV_PATH), help="CSV 输出路径")
    args = parser.parse_args(argv)

    setup_logging()
    started = time.time()
    try:
        years = parse_years(args.years)
    except ValueError as exc:
        logger.error("参数错误：%s", exc)
        return 2

    logger.info("开始采集软科排名：年份 %s，请求间隔 %.1fs", years, args.delay)

    session = build_session()
    use_cache = not args.no_cache
    if args.from_cache:
        use_cache = True

    rows: list[dict] = []
    failed_years: list[int] = []
    for index, year in enumerate(years):
        if index > 0 and not use_cache:
            time.sleep(args.delay + random.uniform(0, 0.6))
        try:
            payload = load_or_fetch(session, year, use_cache, args.delay, args.retries)
        except Exception as exc:  # noqa: BLE001
            logger.error("年份 %d 采集失败，跳过：%s", year, exc)
            failed_years.append(year)
            continue
        year_rows = parse_year(payload, year)
        logger.info("年份 %d：解析 %d 条", year, len(year_rows))
        rows.extend(year_rows)

    if not rows:
        logger.error("没有任何数据，退出（请检查网络/缓存）")
        return 1

    write_csv(rows, Path(args.out))
    logger.info("已写出 CSV：%s（%d 行）", Path(args.out), len(rows))

    ok = verify(rows, [y for y in years if y not in failed_years])
    save_meta(rows, years, time.time() - started, META_PATH)
    print_sample(rows)

    if failed_years:
        logger.error("以下年份采集失败：%s", failed_years)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
