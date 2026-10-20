#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
spider_admission.py —— 阶段 5：掌上高考招生计划采集（F06 / P1）

数据源：掌上高考公开 JSON 接口（无需登录/签名）
    https://api.zjzw.cn/web/api/?school_id=140&local_province_id=41
        &local_type_id=1&year=2024&page=1&size=20&uri=apidata/api/gkv3/plan/school

输出：data/admission_raw.csv（UTF-8-SIG）
    univ_slug, univ_name, school_id, year, province, local_type, major, batch, count, tuition

策略：
    - 学校名单来自 data/clean_rankings.csv（按 2021 名次顺序取前 N 所）
    - 招生省份默认 河南/四川/北京/山东（接口覆盖较好的 4 个）
    - 年份默认 2021-2024（2025/2026 接口无数据）
    - 非新高考省份取理科（local_type_id=1），新高考省份取综合（3）
    - size=20 分页，最多 10 页；请求间隔 0.8s；失败重试 1 次
    - 增量写 CSV + 断点续跑：已采过的 (学校, 年份, 省份, 类型) 自动跳过

用法：
    python spider_admission.py                     # 默认 20 校 x 4 省 x 4 年
    python spider_admission.py --limit 30 --min-rows 3000
    python spider_admission.py --provinces 41,51,11,37 --years 2023,2024
    python spider_admission.py --resume            # 中断后续跑
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RANK_CSV = DATA_DIR / "clean_rankings.csv"
OUT_CSV = DATA_DIR / "admission_raw.csv"
MAP_JSON = DATA_DIR / "admission_school_map.json"
LOG_DIR = PROJECT_ROOT / "logs"

API = "https://api.zjzw.cn/web/api/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.gaokao.cn/",
    "Accept": "application/json, text/plain, */*",
}

PROVINCE_NAME = {
    "11": "北京", "12": "天津", "13": "河北", "14": "山西", "15": "内蒙古",
    "21": "辽宁", "22": "吉林", "23": "黑龙江", "31": "上海", "32": "江苏",
    "33": "浙江", "34": "安徽", "35": "福建", "36": "江西", "37": "山东",
    "41": "河南", "42": "湖北", "43": "湖南", "44": "广东", "45": "广西",
    "46": "海南", "50": "重庆", "51": "四川", "52": "贵州", "53": "云南",
    "54": "西藏", "61": "陕西", "62": "甘肃", "63": "青海", "64": "宁夏", "65": "新疆",
}
NEW_GAOKAO = {"11", "12", "31", "33", "37", "46"}

CSV_FIELDS = ["univ_slug", "univ_name", "school_id", "year", "province",
              "local_type", "major", "batch", "count", "tuition"]

logger = logging.getLogger("spider_admission")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    fh = logging.FileHandler(LOG_DIR / "spider_admission.log", mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)


def get_json(params: dict, retries: int = 1):
    last = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(API, params=params, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries:
                time.sleep(2)
    logger.warning("请求失败：%s（%s）", params.get("uri"), last)
    return None


def load_schools(limit: int) -> list[tuple[str, str]]:
    if not RANK_CSV.exists():
        raise SystemExit("❌ 找不到 %s，请先执行 python load_data.py" % RANK_CSV)
    schools, seen = [], set()
    with RANK_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = row.get("univ_name", "").strip()
            slug = row.get("univ_slug", "").strip()
            if name and name not in seen:
                seen.add(name)
                schools.append((slug, name))
    return schools[:limit]


def find_school_id(name: str, cache: dict, rate: float) -> int | None:
    if name in cache:
        return cache[name]
    data = get_json({"keyword": name, "page": 1, "size": 10, "request_type": 1,
                     "uri": "apidata/api/gk/school/lists"})
    sid = None
    for item in (data or {}).get("data", {}).get("item", []) or []:
        if item.get("name") == name:
            sid = int(item["school_id"])
            break
    cache[name] = sid
    time.sleep(rate)
    return sid


def fetch_plan(school_id: int, province: str, type_id: int, year: int,
               rate: float, max_pages: int = 10) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        data = get_json({
            "school_id": school_id, "local_province_id": province,
            "local_type_id": type_id, "year": year, "page": page,
            "size": 20, "uri": "apidata/api/gkv3/plan/school",
        })
        payload = (data or {}).get("data") or {}
        items = payload.get("item") or []
        if (data or {}).get("code") != "0000" or not items:
            break
        rows.extend(items)
        if len(items) < 20 or len(rows) >= int(payload.get("numFound") or 0):
            break
        time.sleep(rate)
    return rows


def load_done(out_path: Path) -> set[tuple[str, str, str, str]]:
    done = set()
    if not out_path.exists():
        return done
    with out_path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            done.add((row.get("univ_slug", ""), row.get("year", ""),
                      row.get("province", ""), row.get("local_type", "")))
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="掌上高考招生计划采集")
    parser.add_argument("--limit", type=int, default=20, help="学校数（按 2021 名次）")
    parser.add_argument("--provinces", default="41,51,11,37", help="招生省份 ID，逗号分隔")
    parser.add_argument("--years", default="2021,2022,2023,2024")
    parser.add_argument("--types", default="", help="强制类型 ID，逗号分隔；默认按省份自动")
    parser.add_argument("--out", default=str(OUT_CSV))
    parser.add_argument("--rate", type=float, default=0.8, help="请求间隔秒")
    parser.add_argument("--min-rows", type=int, default=0, help="达到行数后可提前结束")
    parser.add_argument("--resume", action="store_true", help="跳过已采集组合")
    args = parser.parse_args(argv)

    setup_logging()
    schools = load_schools(args.limit)
    provinces = [p.strip() for p in args.provinces.split(",") if p.strip()]
    years = [int(y) for y in args.years.split(",") if y.strip()]
    forced_types = [int(t) for t in args.types.split(",") if t.strip()]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cache = {}
    if MAP_JSON.exists():
        cache = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    done = load_done(out_path) if args.resume else set()

    write_header = not out_path.exists() or out_path.stat().st_size == 0
    fh = out_path.open("a", encoding="utf-8-sig", newline="")
    writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
    if write_header:
        writer.writeheader()

    total = 0
    started = time.time()
    logger.info("开始采集：%d 所学校 x %d 省 x %d 年", len(schools), len(provinces), len(years))
    try:
        for index, (slug, name) in enumerate(schools, 1):
            school_id = find_school_id(name, cache, args.rate)
            if not school_id:
                logger.warning("[跳过] 未找到学校：%s", name)
                continue

            for province in provinces:
                types = forced_types or ([3] if province in NEW_GAOKAO else [1])
                for year in years:
                    for type_id in types:
                        key = (slug, str(year), PROVINCE_NAME.get(province, province), str(type_id))
                        if key in done:
                            continue
                        items = fetch_plan(school_id, province, type_id, year, args.rate)
                        for item in items:
                            writer.writerow({
                                "univ_slug": slug,
                                "univ_name": name,
                                "school_id": school_id,
                                "year": item.get("year", year),
                                "province": item.get("local_province_name") or PROVINCE_NAME.get(province, province),
                                "local_type": item.get("local_type_name", ""),
                                "major": item.get("sp_name") or item.get("level3_name", ""),
                                "batch": item.get("local_batch_name", ""),
                                "count": item.get("num", ""),
                                "tuition": item.get("tuition", ""),
                            })
                        fh.flush()
                        total += len(items)
                        logger.info("%d/%d %s · %s · %d · type%s -> %d 行（累计 %d）",
                                    index, len(schools), name, PROVINCE_NAME.get(province, province),
                                    year, type_id, len(items), total)
                        if args.min_rows and total >= args.min_rows and index >= 8:
                            logger.info("已达到 min-rows=%d，提前结束", args.min_rows)
                            raise StopIteration
                        time.sleep(args.rate)
            MAP_JSON.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except StopIteration:
        pass
    finally:
        fh.close()
        MAP_JSON.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    logger.info("完成：%d 行，用时 %.1f 秒 -> %s", total, time.time() - started, out_path)
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
