#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
load_data.py —— 阶段 2：清洗软科排名数据并写入 MySQL 5.7

输入：data/rankings_raw.csv（阶段 1 产物，3535 行）
输出：
    data/clean_rankings.csv   清洗后的明细（一校一年一行）
    MySQL university / ranking 两张表（admission / major_score 建空表）

清洗规则（对应设计文档 v2 §3 / 阶段 2 要求）：
    1. 去重：按 (univ_slug, year) 唯一，保留后出现的记录
    2. 缺失：univ_slug / year / univ_name / province / univ_type / rank 任一为空则丢弃该行
    3. 排名：软科 "500+" 统一记为 1000（哨兵值，与真实名次区分），其余转整数
    4. 分数：空串/None 转 NULL；总分与三项分项均转浮点
    5. 星级：转整数 1-5
    6. 学校主表：同一 slug 取最新年份的校名/省份/类型；层次按 985 > 211 > 双一流 > 普通 归并
    7. 城市：按用户要求取消该字段（软科本身也不提供）
    8. 学校标识：软科换过 slug 的同一学校（同名同省）按并查集合并，取最新 slug 为规范标识

用法：
    # 只清洗不连库（先看清洗报告）
    python load_data.py --dry-run

    # 清洗 + 建库建表 + 入库（账号密码通过参数或环境变量传入）
    python load_data.py --user root --password 你的密码
    $env:MYSQL_PASSWORD="你的密码"; python load_data.py --user root

    # 自定义连接
    python load_data.py --host 127.0.0.1 --port 3306 --user root --database university

注意：脚本不会猜测账号密码；未提供时直接报错退出。
     可重复执行：每次会清空 university/ranking 后全量重导（admission/major_score 不动）。
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pymysql

PROJECT_ROOT = Path(__file__).resolve().parent
RAW_CSV = PROJECT_ROOT / "data" / "rankings_raw.csv"
CLEAN_CSV = PROJECT_ROOT / "data" / "clean_rankings.csv"
SCHEMA_SQL = PROJECT_ROOT / "schema.sql"

# 软科 "500+" 的哨兵值：真实名次最大 594，用 1000 可与之明确区分，避免与真实第 501 名混淆
RANK_CAP = 1000
SCORE_COLUMNS = ["score_total", "score_research", "score_talent", "score_social"]
FLAG_COLUMNS = ["is_985", "is_211", "is_double"]
LEVEL_ORDER = [("is_985", "985"), ("is_211", "211"), ("is_double", "双一流")]

CLEAN_FIELDS = [
    "year", "univ_slug", "univ_name", "province", "univ_type", "level",
    "is_985", "is_211", "is_double", "rank",
    "score_total", "score_research", "score_talent", "score_social", "stars",
]


def log(message: str = "") -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# 清洗
# --------------------------------------------------------------------------- #
def read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def strip_text(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()
    return df


def resolve_school_identity(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    合并软科的重复学校条目。

    背景：软科对同一所学校偶尔会换 slug（如常熟理工学院在 2021-2022 用
    changshu-institute-of-technology-2、2023-2024 用 ...-3、2025 起用原名 slug），
    导致同一所学校被拆成多个 univ_slug。

    规则：只要两个 slug 在任意年份出现相同的 (province, univ_name)，就判定为同一所学校，
    用并查集合并；合并后统一使用「覆盖年份最新」的 slug 作为规范标识。
    同一年份同名同省本身即为重复条目，合并后由后续去重处理。
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for slug in df["univ_slug"].unique():
        parent[slug] = slug

    owner: dict[tuple[str, str], str] = {}
    for row in df.itertuples(index=False):
        key = (row.province, row.univ_name)
        if key in owner:
            union(owner[key], row.univ_slug)
        else:
            owner[key] = row.univ_slug

    groups: dict[str, list[str]] = {}
    for slug in parent:
        groups.setdefault(find(slug), []).append(slug)

    latest: dict[str, int] = df.groupby("univ_slug")["year"].max().to_dict()
    alias: dict[str, str] = {}
    merged: list[dict] = []
    for members in groups.values():
        canonical = max(members, key=lambda s: (latest.get(s, 0), s))
        for slug in members:
            alias[slug] = canonical
        if len(members) > 1:
            merged.append({"canonical": canonical, "aliases": sorted(members)})

    df = df.copy()
    df["univ_slug"] = df["univ_slug"].map(alias)
    return df, merged


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """执行清洗规则，返回 (清洗后明细, 清洗报告)。"""
    report = {"input_rows": int(len(df))}

    # 0) 城市字段：按用户要求取消
    if "city" in df.columns:
        df = df.drop(columns=["city"])
        report["dropped_city_column"] = True

    df = strip_text(df)

    # 0.5) 合并软科重复条目（同一学校换过 slug 的情况）
    df, merged_schools = resolve_school_identity(df)
    report["merged_school_aliases"] = merged_schools

    # 1) 去重：一校一年一条
    before = len(df)
    df = df.drop_duplicates(subset=["univ_slug", "year"], keep="last")
    report["duplicate_rows_removed"] = int(before - len(df))

    # 2) 必需字段缺失
    required = ["univ_slug", "year", "univ_name", "province", "univ_type", "rank"]
    mask = pd.Series(True, index=df.index)
    for col in required:
        mask &= df[col].astype(str).str.strip().ne("") & df[col].notna()
    report["dropped_missing_required"] = int((~mask).sum())
    df = df[mask].copy()

    # 3) 年份
    year = pd.to_numeric(df["year"], errors="coerce")
    report["dropped_invalid_year"] = int(year.isna().sum())
    df = df[year.notna()].copy()
    df["year"] = year[year.notna()].astype(int)

    # 4) 排名：500+ -> 哨兵 1000
    rank_raw = df["rank"].astype(str).str.strip()
    is_plus = rank_raw.str.endswith("+")
    rank_num = pd.to_numeric(rank_raw.str.replace("+", "", regex=False), errors="coerce")
    rank_num.loc[is_plus] = RANK_CAP
    report["rank_capped_500plus"] = int(is_plus.sum())
    report["rank_invalid"] = int(rank_num.isna().sum())
    df["rank"] = rank_num

    # 5) 分数与星级
    for col in SCORE_COLUMNS:
        df[col] = pd.to_numeric(df[col].replace("", None), errors="coerce")
    df["stars"] = (
        pd.to_numeric(df["stars"], errors="coerce").fillna(1).clip(1, 5).astype(int)
    )
    for col in FLAG_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # 6) 排序，便于“取最新年份”
    df = df.sort_values(["univ_slug", "year"]).reset_index(drop=True)
    report["clean_rows"] = int(len(df))
    report["unique_schools"] = int(df["univ_slug"].nunique())
    return df, report


def merge_level(flags: dict) -> str:
    """985 > 211 > 双一流 > 普通。"""
    for field, label in LEVEL_ORDER:
        if int(flags.get(field, 0)) == 1:
            return label
    return "普通"


def build_school_master(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """按 slug 归并学校主表：取最新年份的校名/省份/类型。"""
    rows = []
    renamed = {}
    province_changed = {}
    for slug, sub in df.groupby("univ_slug", sort=True):
        sub = sub.sort_values("year")
        last = sub.iloc[-1]
        names = sorted({str(x) for x in sub["univ_name"]})
        provinces = sorted({str(x) for x in sub["province"]})
        if len(names) > 1:
            renamed[slug] = {"chosen": str(last["univ_name"]), "all": names}
        if len(provinces) > 1:
            province_changed[slug] = {"chosen": str(last["province"]), "all": provinces}
        flags = {col: int(last[col]) for col in FLAG_COLUMNS}
        rows.append({
            "univ_slug": slug,
            "name": str(last["univ_name"]),
            "province": str(last["province"]),
            "type": str(last["univ_type"]),
            "level": merge_level(flags),
            **flags,
        })

    master = pd.DataFrame(rows).sort_values("name").reset_index(drop=True)
    duplicated = master[master.duplicated("name", keep=False)]
    if len(duplicated):
        raise RuntimeError(
            "学校主表出现重名，无法直接入库：\n%s"
            % duplicated[["name", "province", "univ_slug"]].to_string(index=False)
        )

    meta = {
        "renamed_schools": renamed,
        "province_changed_schools": province_changed,
        "level_distribution": master["level"].value_counts().to_dict(),
    }
    return master, meta


def write_clean(rankings: pd.DataFrame, master: pd.DataFrame, path: Path) -> None:
    """输出清洗后的明细 CSV：明细字段 + 学校主表归并结果。"""
    out = rankings.merge(
        master[["univ_slug", "name", "province", "type", "level", *FLAG_COLUMNS]],
        on="univ_slug", how="left", suffixes=("", "_m"),
    )
    out["univ_name"] = out["name"].fillna(out["univ_name"])
    out["province"] = out["province_m"].fillna(out["province"])
    out["univ_type"] = out["type"].fillna(out["univ_type"])
    out["level"] = out["level_m"].fillna(out["level"])
    for col in FLAG_COLUMNS:
        out[col] = out[col + "_m"].fillna(out[col]).astype(int)

    out = out[CLEAN_FIELDS].sort_values(["year", "rank", "univ_name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")


# --------------------------------------------------------------------------- #
# 数据库
# --------------------------------------------------------------------------- #
def resolve_credentials(args) -> tuple[str, str]:
    """账号密码只从参数/环境变量取，绝不猜测。"""
    user = args.user or os.environ.get("MYSQL_USER")
    password = args.password if args.password is not None else os.environ.get("MYSQL_PASSWORD")
    if password is None and sys.stdin.isatty():
        password = getpass.getpass("MySQL 密码（%s）：" % (user or "root"))
    if not user:
        raise SystemExit("❌ 未提供 MySQL 用户名：请用 --user 或环境变量 MYSQL_USER")
    if password is None:
        raise SystemExit(
            "❌ 未提供 MySQL 密码：请用 --password、环境变量 MYSQL_PASSWORD，或在终端交互输入。"
            "（本脚本不会猜测账号密码）"
        )
    return user, password


def db_connect(host: str, port: int, user: str, password: str, database: str | None):
    return pymysql.connect(
        host=host, port=port, user=user, password=password,
        charset="utf8mb4", autocommit=False, database=database,
    )


def ensure_database(host: str, port: int, user: str, password: str, database: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise SystemExit("❌ 数据库名只允许字母/数字/下划线：%r" % database)
    conn = db_connect(host, port, user, password, None)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE DATABASE IF NOT EXISTS `%s` DEFAULT CHARACTER SET utf8mb4 "
                "COLLATE utf8mb4_unicode_ci" % database
            )
        conn.commit()
    finally:
        conn.close()


def split_sql(sql: str) -> list[str]:
    statements = []
    for chunk in sql.split(";"):
        lines = [ln for ln in chunk.splitlines() if not ln.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt)
    return statements


def run_schema(conn, schema_path: Path) -> None:
    statements = split_sql(schema_path.read_text(encoding="utf-8"))
    with conn.cursor() as cur:
        for stmt in statements:
            cur.execute(stmt)
    conn.commit()
    log("✅ 建表脚本执行完成（schema.sql，共 %d 条语句）" % len(statements))


def to_int(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return int(value)


def to_float(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return float(value)


def load_to_mysql(conn, master: pd.DataFrame, rankings: pd.DataFrame, database: str) -> dict:
    """清空 university/ranking 后全量写入；admission/major_score 不动。"""
    with conn.cursor() as cur:
        cur.execute("USE `%s`" % database)
        cur.execute("DELETE FROM ranking")
        cur.execute("DELETE FROM university")
        cur.execute("ALTER TABLE ranking AUTO_INCREMENT = 1")
        cur.execute("ALTER TABLE university AUTO_INCREMENT = 1")

        slug2id: dict[str, int] = {}
        for row in master.itertuples(index=False):
            cur.execute(
                "INSERT INTO university (name, province, type, level, is_985, is_211, is_double) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (row.name, row.province, row.type, row.level,
                 int(row.is_985), int(row.is_211), int(row.is_double)),
            )
            slug2id[row.univ_slug] = int(cur.lastrowid)

        records = []
        for row in rankings.itertuples(index=False):
            records.append((
                slug2id[row.univ_slug], int(row.year), to_int(row.rank),
                to_float(row.score_total), to_float(row.score_research),
                to_float(row.score_talent), to_float(row.score_social), int(row.stars),
            ))
        cur.executemany(
            "INSERT INTO ranking (univ_id, year, `rank`, score_total, score_research, "
            "score_talent, score_social, stars) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            records,
        )
    conn.commit()
    return {"universities": len(master), "rankings": len(records)}


def verify(conn, database: str) -> bool:
    log("")
    log("=" * 62)
    log("入库校验")
    log("=" * 62)
    ok = True
    with conn.cursor() as cur:
        cur.execute("USE `%s`" % database)
        for table in ("university", "ranking", "admission", "major_score"):
            cur.execute("SELECT COUNT(*) FROM `%s`" % table)
            count = cur.fetchone()[0]
            log("  %-12s %d 行" % (table, count))
            if table in ("university", "ranking") and count == 0:
                ok = False

        log("")
        log("各年份排名记录数：")
        cur.execute("SELECT year, COUNT(*) FROM ranking GROUP BY year ORDER BY year")
        for year, count in cur.fetchall():
            log("  %d：%d 条" % (year, count))

        log("")
        log("层次分布：")
        cur.execute("SELECT level, COUNT(*) FROM university GROUP BY level ORDER BY COUNT(*) DESC")
        for level, count in cur.fetchall():
            log("  %-6s %d 所" % (level, count))

        log("")
        log("孤儿记录检查（ranking.univ_id 不存在于 university）：")
        cur.execute(
            "SELECT COUNT(*) FROM ranking r LEFT JOIN university u ON r.univ_id = u.id "
            "WHERE u.id IS NULL"
        )
        orphans = cur.fetchone()[0]
        log("  %d 条" % orphans)
        if orphans:
            ok = False

        log("")
        log("2026 年前 5 名（JOIN 校验）：")
        cur.execute(
            "SELECT u.name, u.province, r.`rank`, r.score_total, r.stars "
            "FROM ranking r JOIN university u ON r.univ_id = u.id "
            "WHERE r.year = 2026 ORDER BY r.`rank` LIMIT 5"
        )
        for name, province, rank, score, stars in cur.fetchall():
            log("  %-2s | %-10s | %-4s | %-8s | %s星" % (rank, name, province, score, stars))

    log("")
    log("校验结论：%s" % ("✅ 通过" if ok else "❌ 未通过"))
    return ok


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="阶段 2：清洗软科排名并写入 MySQL 5.7")
    parser.add_argument("--csv", default=str(RAW_CSV), help="原始 CSV 路径")
    parser.add_argument("--clean-out", default=str(CLEAN_CSV), help="清洗后 CSV 输出路径")
    parser.add_argument("--schema", default=str(SCHEMA_SQL), help="建表 SQL 路径")
    parser.add_argument("--host", default=os.environ.get("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_PORT", "3306")))
    parser.add_argument("--user", default=None, help="MySQL 用户名（或用 MYSQL_USER）")
    parser.add_argument("--password", default=None, help="MySQL 密码（或用 MYSQL_PASSWORD）")
    parser.add_argument("--database", default=os.environ.get("MYSQL_DATABASE", "university"))
    parser.add_argument("--dry-run", action="store_true", help="只清洗、不连数据库")
    return parser.parse_args(argv)


def print_report(report: dict, meta: dict) -> None:
    log("=" * 62)
    log("清洗报告")
    log("=" * 62)
    log("  输入行数            %d" % report["input_rows"])
    if report.get("dropped_city_column"):
        log("  已移除字段          city（按需求取消）")
    log("  重复行已删除        %d" % report["duplicate_rows_removed"])
    log("  必需字段缺失已删除  %d" % report["dropped_missing_required"])
    log("  非法年份已删除      %d" % report["dropped_invalid_year"])
    log("  500+ 记为哨兵 1000  %d 条" % report["rank_capped_500plus"])
    log("  排名无法解析        %d 条" % report["rank_invalid"])
    log("  合并重复学校条目    %d 组" % len(report.get("merged_school_aliases") or []))
    for group in report.get("merged_school_aliases") or []:
        log("    %-38s <- %s" % (group["canonical"], ", ".join(group["aliases"])))
    log("  清洗后行数          %d" % report["clean_rows"])
    log("  学校数              %d" % report["unique_schools"])

    log("")
    log("  校名变更（取最新年份）：")
    for slug, info in meta["renamed_schools"].items():
        log("    %-42s %s -> %s" % (slug, "/".join(info["all"]), info["chosen"]))
    log("  省份变更（取最新年份）：")
    for slug, info in meta["province_changed_schools"].items():
        log("    %-42s %s -> %s" % (slug, "/".join(info["all"]), info["chosen"]))
    log("  层次分布：%s" % meta["level_distribution"])
    log("=" * 62)


def main(argv=None) -> int:
    args = parse_args(argv)

    raw_path = Path(args.csv)
    if not raw_path.exists():
        log("❌ 找不到原始数据：%s（请先执行 python spider_ranking.py）" % raw_path)
        return 2

    log("读取 %s ..." % raw_path)
    df, report = clean(read_raw(raw_path))
    master, meta = build_school_master(df)
    print_report(report, meta)

    clean_path = Path(args.clean_out)
    write_clean(df, master, clean_path)
    log("已写出清洗结果：%s（%d 行 × %d 列）"
        % (clean_path, len(df), len(CLEAN_FIELDS)))

    if args.dry_run:
        log("")
        log("--dry-run：已跳过数据库写入")
        return 0

    user, password = resolve_credentials(args)
    log("")
    log("连接 MySQL：%s:%d，用户 %s，数据库 %s" % (args.host, args.port, user, args.database))
    try:
        ensure_database(args.host, args.port, user, password, args.database)
        conn = db_connect(args.host, args.port, user, password, args.database)
    except pymysql.err.OperationalError as exc:
        log("❌ 连接 MySQL 失败：%s" % exc)
        log("   请确认服务已启动、账号密码正确、账号有建库权限。")
        return 3

    try:
        run_schema(conn, Path(args.schema))
        stats = load_to_mysql(conn, master, df, args.database)
        log("✅ 入库完成：university %d 行，ranking %d 行"
            % (stats["universities"], stats["rankings"]))
        ok = verify(conn, args.database)
    except pymysql.MySQLError as exc:
        conn.rollback()
        log("❌ 入库失败，已回滚：%s" % exc)
        return 4
    finally:
        conn.close()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
