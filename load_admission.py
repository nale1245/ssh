#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
load_admission.py —— 阶段 5：清洗招生计划数据并写入 admission 表

输入：data/admission_raw.csv（招生爬虫产物）
    支持列名（大小写/中英文均可）：
        univ_name / name / 学校（必需）
        year / 年份（必需）
        province / 省份（必需）
        major / 专业（必需）
        count / 招生人数 / 人数（必需）
        univ_slug（可选，有则优先按 slug 匹配）
输出：
    data/admission_clean.csv   清洗后明细
    MySQL admission 表（每次全量重导）

清洗规则：
    1. 必需字段为空 → 丢弃
    2. year / count 转整数；非法值丢弃
    3. 学校名精确匹配 university.name；找不到时做「去空格 + 规范化」匹配
    4. 同一 (univ_id, year, province, major) 合并，count 求和
    5. 匹配不到学校的记录跳过并汇总报告

用法：
    python load_admission.py --dry-run        # 只清洗，不写库
    python load_admission.py                  # 清洗 + 入库（config.py 提供账号密码）
    python load_admission.py --csv data/admission_raw.csv --limit-report 30
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import pymysql

from config import DB_CONFIG

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_CSV = PROJECT_ROOT / "data" / "admission_raw.csv"
CLEAN_CSV = PROJECT_ROOT / "data" / "admission_clean.csv"

COLUMN_ALIASES = {
    "univ_name": ["univ_name", "name", "学校", "学校名", "院校", "院校名称"],
    "year": ["year", "年份"],
    "province": ["province", "省份", "招生省份"],
    "major": ["major", "专业", "专业名称"],
    "count": ["count", "招生人数", "人数", "计划数", "招生计划"],
    "univ_slug": ["univ_slug", "slug"],
}


def log(message: str = "") -> None:
    print(message, flush=True)


def normalize_name(name: str) -> str:
    """去掉空格、括号内容，用于宽松匹配校名。"""
    text = re.sub(r"\s+", "", str(name or ""))
    text = re.sub(r"[（(].*?[）)]", "", text)
    return text


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    lower_map = {c.lower(): c for c in df.columns}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lower_map:
                rename[lower_map[alias.lower()]] = target
                break
    df = df.rename(columns=rename)
    missing = [c for c in ("univ_name", "year", "province", "major", "count") if c not in df.columns]
    if missing:
        raise SystemExit("❌ CSV 缺少必需列：%s（实际列：%s）" % (missing, list(df.columns)))
    return df


def clean(df: pd.DataFrame, university_map: dict[str, int], normalize_map: dict[str, int],
          slug_map: dict[str, str] | None = None) -> tuple[pd.DataFrame, dict]:
    report = {"input_rows": int(len(df))}
    before = len(df)

    for col in ("univ_name", "province", "major"):
        df[col] = df[col].astype(str).str.strip()

    mask = (df["univ_name"] != "") & (df["province"] != "") & (df["major"] != "")
    report["dropped_missing"] = int((~mask).sum())
    df = df[mask].copy()

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["count"] = pd.to_numeric(df["count"], errors="coerce")
    valid = df["year"].notna() & df["count"].notna()
    report["dropped_invalid_number"] = int((~valid).sum())
    df = df[valid].copy()
    df["year"] = df["year"].astype(int)
    df["count"] = df["count"].astype(int)
    df = df[df["count"] > 0].copy()

    df["univ_id"] = df["univ_name"].map(university_map)
    missing = df["univ_id"].isna()
    if missing.any():
        normalized = df.loc[missing, "univ_name"].map(normalize_name).map(normalize_map)
        df.loc[missing, "univ_id"] = normalized
    # 仍有未匹配：用 univ_slug 反查规范校名（爬虫输出常带 slug）
    missing = df["univ_id"].isna()
    if missing.any() and slug_map and "univ_slug" in df.columns:
        via_slug = df.loc[missing, "univ_slug"].map(slug_map).map(normalize_name).map(normalize_map)
        df.loc[missing, "univ_id"] = via_slug
    unmatched = df[df["univ_id"].isna()]
    report["unmatched_schools"] = int(len(unmatched))
    report["unmatched_examples"] = (
        unmatched["univ_name"].value_counts().head(15).to_dict() if len(unmatched) else {}
    )
    df = df[df["univ_id"].notna()].copy()
    df["univ_id"] = df["univ_id"].astype(int)

    before_dedup = len(df)
    df = (
        df.groupby(["univ_id", "year", "province", "major"], as_index=False)
        .agg({"count": "sum", "univ_name": "first"})
    )
    report["duplicate_rows_merged"] = int(before_dedup - len(df))
    report["clean_rows"] = int(len(df))
    report["schools"] = int(df["univ_id"].nunique())
    report["years"] = sorted(int(y) for y in df["year"].unique())
    report["provinces"] = int(df["province"].nunique())
    report["majors"] = int(df["major"].nunique())
    return df, report


def connect():
    return pymysql.connect(**DB_CONFIG, charset="utf8mb4", autocommit=False)


def load_universities(conn) -> tuple[dict[str, int], dict[str, int]]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM university")
        rows = cur.fetchall()
    exact = {name: uid for uid, name in rows}
    normalized = {normalize_name(name): uid for uid, name in rows}
    return exact, normalized


def load_to_mysql(df: pd.DataFrame, database: str) -> dict:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("USE `%s`" % database)
            cur.execute("DELETE FROM admission")
            cur.execute("ALTER TABLE admission AUTO_INCREMENT = 1")
            records = [
                (int(r.univ_id), int(r.year), r.province, r.major, int(r.count))
                for r in df.itertuples(index=False)
            ]
            cur.executemany(
                "INSERT INTO admission (univ_id, year, province, major, `count`) "
                "VALUES (%s, %s, %s, %s, %s)",
                records,
            )
        conn.commit()
        return {"inserted": len(records)}
    except pymysql.MySQLError:
        conn.rollback()
        raise
    finally:
        conn.close()


def verify(database: str) -> bool:
    conn = connect()
    ok = True
    try:
        with conn.cursor() as cur:
            cur.execute("USE `%s`" % database)
            cur.execute("SELECT COUNT(*) FROM admission")
            total = cur.fetchone()[0]
            log("")
            log("=" * 62)
            log("招生数据入库校验")
            log("=" * 62)
            log("  admission 总行数：%d" % total)
            if total == 0:
                ok = False

            cur.execute("SELECT year, COUNT(*), SUM(`count`) FROM admission GROUP BY year ORDER BY year")
            for year, rows, people in cur.fetchall():
                log("  %s 年：%d 条，合计 %s 人" % (year, rows, people))

            cur.execute(
                "SELECT province, SUM(`count`) AS total FROM admission "
                "GROUP BY province ORDER BY total DESC LIMIT 5"
            )
            log("  招生人数 Top5 省份：" + "，".join("%s %s" % (p, t) for p, t in cur.fetchall()))

            cur.execute(
                "SELECT major, SUM(`count`) AS total FROM admission "
                "GROUP BY major ORDER BY total DESC LIMIT 5"
            )
            log("  招生人数 Top5 专业：" + "，".join("%s %s" % (m, t) for m, t in cur.fetchall()))

            cur.execute(
                "SELECT COUNT(*) FROM admission a LEFT JOIN university u ON a.univ_id = u.id "
                "WHERE u.id IS NULL"
            )
            orphan = cur.fetchone()[0]
            log("  孤儿记录：%d" % orphan)
            if orphan:
                ok = False
    finally:
        conn.close()
    log("  校验结论：%s" % ("通过" if ok else "未通过"))
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="阶段 5：招生计划清洗入库")
    parser.add_argument("--csv", default=str(RAW_CSV))
    parser.add_argument("--clean-out", default=str(CLEAN_CSV))
    parser.add_argument("--database", default=DB_CONFIG["database"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.csv)
    if not path.exists():
        log("❌ 找不到招生 CSV：%s（请先运行招生爬虫）" % path)
        return 2

    log("读取 %s ..." % path)
    df = read_csv(path)

    slug_map = {}
    clean_path = PROJECT_ROOT / "data" / "clean_rankings.csv"
    if clean_path.exists():
        import csv as _csv
        with clean_path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in _csv.DictReader(fh):
                if row.get("univ_slug"):
                    slug_map[row["univ_slug"]] = row["univ_name"]

    log("读取 university 学校名单 ...")
    try:
        conn = connect()
        try:
            exact, normalized = load_universities(conn)
        finally:
            conn.close()
    except pymysql.MySQLError as exc:
        log("❌ 连接数据库失败：%s" % exc)
        return 3

    df, report = clean(df, exact, normalized, slug_map)

    log("=" * 62)
    log("招生数据清洗报告")
    log("=" * 62)
    log("  输入行数            %d" % report["input_rows"])
    log("  缺失字段丢弃        %d" % report["dropped_missing"])
    log("  非法数字丢弃        %d" % report["dropped_invalid_number"])
    log("  未匹配到学校        %d" % report["unmatched_schools"])
    for name, cnt in report["unmatched_examples"].items():
        log("    - %s（%d 条）" % (name, cnt))
    log("  合并重复记录        %d" % report["duplicate_rows_merged"])
    log("  清洗后行数          %d" % report["clean_rows"])
    log("  覆盖学校/年份/省份/专业：%d / %s / %d / %d" % (
        report["schools"], report["years"], report["provinces"], report["majors"]))

    out = Path(args.clean_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df[["univ_id", "univ_name", "year", "province", "major", "count"]].to_csv(
        out, index=False, encoding="utf-8-sig")
    log("已写出清洗结果：%s（%d 行）" % (out, len(df)))

    if args.dry_run:
        log("--dry-run：已跳过数据库写入")
        return 0

    try:
        stats = load_to_mysql(df, args.database)
    except pymysql.MySQLError as exc:
        log("❌ 入库失败：%s" % exc)
        return 4
    log("✅ 入库完成：admission %d 行" % stats["inserted"])
    return 0 if verify(args.database) else 1


if __name__ == "__main__":
    raise SystemExit(main())