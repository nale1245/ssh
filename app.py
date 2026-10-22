#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
app.py —— 阶段 3：Flask 后端 API（设计文档 v2 §4，API-01 ~ API-06）

统一响应结构：{"code": 0, "data": ..., "message": "ok"}
    0     成功
    1001  参数缺失/非法
    1002  数据不存在
    5000  服务器内部错误（含数据库连接失败）

6 个接口：
    GET /api/map_data      各省学校数量与 985/211 数量（地图着色）
    GET /api/trend         某校历年排名趋势
    GET /api/province      省内大学列表 + 层次统计
    GET /api/correlation   科研 vs 人才培养散点数据
    GET /api/heatmap       年份 × 省份 招生人次热力图
    GET /api/schools       学校列表（搜索/筛选）
额外：GET /api/health     健康检查（数据库连通性），便于联调与自检

数据库：MySQL 5.7（库 university），账号密码在 config.py 中（按使用要求内置）。
也可用环境变量 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE 覆盖。

启动（最简单）：
    python app.py            # 直接启动，浏览器打开 http://127.0.0.1:5000/
    python app.py --open     # 启动后自动打开浏览器
    start.bat                # Windows 双击启动（等价于 python app.py --open）
"""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

import pymysql
from flask import Flask, g, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from config import APP_HOST, APP_PORT, DB_CONFIG

app = Flask(__name__)
app.json.ensure_ascii = False  # 中文直接输出，不转 \uXXXX
CORS(app)

RANK_PLUS_SENTINEL = 1000  # 排名 >= 1000 表示软科「500+」


class ApiError(Exception):
    def __init__(self, code: int, message: str, http_status: int = 200):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def ok(data):
    return jsonify({"code": 0, "data": data, "message": "ok"})


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return jsonify({"code": err.code, "data": None, "message": err.message}), err.http_status


@app.errorhandler(HTTPException)
def handle_http_exception(err: HTTPException):
    return jsonify({
        "code": 1002,
        "data": None,
        "message": err.description or "请求错误",
    }), err.code


@app.errorhandler(pymysql.MySQLError)
def handle_db_error(err: pymysql.MySQLError):
    """数据库错误统一转成可读 JSON，避免浏览器只看到 500。"""
    app.logger.error("数据库错误：%s", err)
    detail = str(err).split("\n")[0][:160]
    return jsonify({
        "code": 5000,
        "data": None,
        "message": "数据库连接或查询失败：%s。请确认 MySQL 服务已启动，且 config.py 中的账号密码正确。" % detail,
    }), 200


@app.errorhandler(Exception)
def handle_unexpected(err: Exception):
    app.logger.exception("未处理异常：%s", err)
    return jsonify({"code": 5000, "data": None, "message": "服务器内部错误：%s" % str(err)[:160]}), 500


# --------------------------------------------------------------------------- #
# 数据库
# --------------------------------------------------------------------------- #
def db_settings() -> dict:
    """账号密码来自 config.py，可用环境变量或命令行参数覆盖。"""
    return dict(DB_CONFIG)


def get_db():
    if "db" not in g:
        g.db = pymysql.connect(
            **db_settings(), charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        )
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql: str, params=()) -> list[dict]:
    with get_db().cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def latest_year() -> int | None:
    rows = query_all("SELECT MAX(year) AS y FROM ranking")
    return rows[0]["y"] if rows else None


# --------------------------------------------------------------------------- #
# 参数工具
# --------------------------------------------------------------------------- #
def parse_year(required: bool = False) -> int | None:
    """读取可选 year 参数；缺省返回 None（由调用方决定用最新年份）。"""
    raw = request.args.get("year")
    if raw is None or raw.strip() == "":
        if required:
            raise ApiError(1001, "缺少参数 year")
        return None
    try:
        return int(raw)
    except ValueError:
        raise ApiError(1001, "参数 year 必须为整数")


def require_param(name: str) -> str:
    value = (request.args.get(name) or "").strip()
    if not value:
        raise ApiError(1001, "缺少参数 %s" % name)
    return value


def resolve_year() -> int:
    year = parse_year()
    if year is None:
        year = latest_year()
    if year is None:
        raise ApiError(1002, "排名数据为空，请先执行 load_data.py")
    return year


def rank_display(rank) -> str:
    """软科 500+ 的哨兵值 1000 在前端展示为「500+」。"""
    if rank is None:
        return ""
    return "500+" if int(rank) >= RANK_PLUS_SENTINEL else str(int(rank))


# --------------------------------------------------------------------------- #
# API-01 各省学校数量与层次分布
# --------------------------------------------------------------------------- #
@app.get("/api/map_data")
def api_map_data():
    year = resolve_year()
    rows = query_all(
        "SELECT u.province AS province, COUNT(*) AS total, "
        "       SUM(u.is_985) AS is985, SUM(u.is_211) AS is211 "
        "FROM ranking r JOIN university u ON u.id = r.univ_id "
        "WHERE r.year = %s "
        "GROUP BY u.province ORDER BY total DESC",
        (year,),
    )
    data = [
        {
            "province": row["province"],
            "total": int(row["total"] or 0),
            "is985": int(row["is985"] or 0),
            "is211": int(row["is211"] or 0),
        }
        for row in rows
    ]
    return ok(data)


# --------------------------------------------------------------------------- #
# API-02 某校历年排名趋势
# --------------------------------------------------------------------------- #
@app.get("/api/trend")
def api_trend():
    school = require_param("school")
    rows = query_all(
        "SELECT r.year, r.`rank`, r.score_total "
        "FROM ranking r JOIN university u ON u.id = r.univ_id "
        "WHERE u.name = %s ORDER BY r.year",
        (school,),
    )
    if not rows:
        rows = query_all(
            "SELECT r.year, r.`rank`, r.score_total "
            "FROM ranking r JOIN university u ON u.id = r.univ_id "
            "WHERE u.name LIKE %s ORDER BY r.year",
            ("%" + school + "%",),
        )
    if not rows:
        raise ApiError(1002, "未找到学校：%s" % school)

    return ok({
        "years": [int(r["year"]) for r in rows],
        "ranks": [int(r["rank"]) if r["rank"] is not None else None for r in rows],
        "scores": [float(r["score_total"]) if r["score_total"] is not None else None for r in rows],
    })


# --------------------------------------------------------------------------- #
# API-03 省内大学列表 + 层次统计
# --------------------------------------------------------------------------- #
@app.get("/api/province")
def api_province():
    province = require_param("province")
    year = resolve_year()

    # 层次统计与学校列表都限定在同一年，保证饼图与列表口径一致
    level_rows = query_all(
        "SELECT u.level AS level, COUNT(*) AS count "
        "FROM ranking r JOIN university u ON u.id = r.univ_id "
        "WHERE u.province = %s AND r.year = %s "
        "GROUP BY u.level ORDER BY count DESC",
        (province, year),
    )
    school_rows = query_all(
        "SELECT u.name, u.level, r.`rank`, r.score_total "
        "FROM ranking r JOIN university u ON u.id = r.univ_id "
        "WHERE u.province = %s AND r.year = %s "
        "ORDER BY r.`rank`, u.name",
        (province, year),
    )
    if not level_rows and not school_rows:
        raise ApiError(1002, "未找到省份：%s" % province)

    return ok({
        "year": year,
        "levelStats": [{"level": r["level"], "count": int(r["count"])} for r in level_rows],
        "schools": [
            {
                "name": r["name"],
                "level": r["level"],
                "rank": int(r["rank"]) if r["rank"] is not None else None,
                "rankDisplay": rank_display(r["rank"]),
                "score": float(r["score_total"]) if r["score_total"] is not None else None,
            }
            for r in school_rows
        ],
    })


# --------------------------------------------------------------------------- #
# API-04 科研 vs 人才培养散点
# --------------------------------------------------------------------------- #
@app.get("/api/correlation")
def api_correlation():
    year = resolve_year()
    rows = query_all(
        "SELECT u.name, r.score_research, r.score_talent "
        "FROM ranking r JOIN university u ON u.id = r.univ_id "
        "WHERE r.year = %s AND r.score_research IS NOT NULL "
        "  AND r.score_talent IS NOT NULL "
        "ORDER BY r.score_talent DESC",
        (year,),
    )
    return ok([
        {"name": r["name"], "research": float(r["score_research"]),
         "talent": float(r["score_talent"])}
        for r in rows
    ])


# --------------------------------------------------------------------------- #
# API-05 年份 × 省份 招生人次热力图
# --------------------------------------------------------------------------- #
@app.get("/api/heatmap")
def api_heatmap():
    year = parse_year()
    years = [2021, 2022, 2023, 2024, 2025, 2026]
    province_rows = query_all(
        "SELECT DISTINCT province FROM university WHERE province IS NOT NULL ORDER BY province"
    )
    provinces = [r["province"] for r in province_rows]

    sql = "SELECT year, province, SUM(`count`) AS total FROM admission "
    params: list = []
    if year is not None:
        sql += "WHERE year = %s "
        params.append(year)
    sql += "GROUP BY year, province ORDER BY year, province"
    rows = query_all(sql, tuple(params))

    y_index = {y: i for i, y in enumerate(years)}
    p_index = {p: i for i, p in enumerate(provinces)}
    values = [
        [p_index[r["province"]], y_index[r["year"]], int(r["total"] or 0)]
        for r in rows
        if r["province"] in p_index and r["year"] in y_index
    ]
    return ok({
        "years": years,
        "provinces": provinces,
        "values": values,
        "hasData": bool(values),
    })


# --------------------------------------------------------------------------- #
# API-06 学校列表（搜索）
# --------------------------------------------------------------------------- #
@app.get("/api/schools")
def api_schools():
    keyword = (request.args.get("keyword") or "").strip()
    limit = request.args.get("limit", "50")
    try:
        limit_int = max(1, min(int(limit), 500))
    except ValueError:
        raise ApiError(1001, "参数 limit 必须为整数")

    if keyword:
        rows = query_all(
            "SELECT id, name FROM university WHERE name LIKE %s ORDER BY name LIMIT %s",
            ("%" + keyword + "%", limit_int),
        )
    else:
        rows = query_all(
            "SELECT id, name FROM university ORDER BY name LIMIT %s", (limit_int,)
        )
    return ok([{"id": int(r["id"]), "name": r["name"]} for r in rows])


# --------------------------------------------------------------------------- #
# 辅助：专业招生人数（热力图框选联动用）
# --------------------------------------------------------------------------- #
def parse_csv_arg(name: str) -> list[str]:
    raw = (request.args.get(name) or "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


@app.get("/api/majors")
def api_majors():
    """
    按省份/年份筛选招生专业（阶段 5 热力图框选联动）。

    参数（均可选，逗号分隔多值）：
        province=广东,广西
        year=2023,2024
        limit=20
    返回：{rows:[{major,total,schools,provinces,years}], hasData}
    """
    provinces = parse_csv_arg("province")
    year_values = parse_csv_arg("year")
    try:
        limit = max(1, min(int(request.args.get("limit", "20")), 100))
    except ValueError:
        raise ApiError(1001, "参数 limit 必须为整数")

    where = []
    params: list = []
    if provinces:
        where.append("province IN (%s)" % ",".join(["%s"] * len(provinces)))
        params.extend(provinces)
    if year_values:
        try:
            years = [int(y) for y in year_values]
        except ValueError:
            raise ApiError(1001, "参数 year 必须为整数")
        where.append("year IN (%s)" % ",".join(["%s"] * len(years)))
        params.extend(years)

    sql = (
        "SELECT major, SUM(`count`) AS total, COUNT(DISTINCT univ_id) AS schools, "
        "       COUNT(DISTINCT province) AS provinces, COUNT(DISTINCT year) AS years "
        "FROM admission "
    )
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "GROUP BY major ORDER BY total DESC, major LIMIT %s"
    params.append(limit)

    rows = query_all(sql, tuple(params))
    return ok({
        "filters": {"provinces": provinces, "years": [int(y) for y in year_values] if year_values else []},
        "rows": [
            {
                "major": r["major"],
                "total": int(r["total"] or 0),
                "schools": int(r["schools"] or 0),
                "provinces": int(r["provinces"] or 0),
                "years": int(r["years"] or 0),
            }
            for r in rows
        ],
        "hasData": bool(rows),
    })


# --------------------------------------------------------------------------- #
# 辅助：招生筛选元数据（年份/省份/学校下拉）
# --------------------------------------------------------------------------- #
@app.get("/api/admission_meta")
def api_admission_meta():
    years = [int(r["year"]) for r in query_all(
        "SELECT DISTINCT year FROM admission ORDER BY year")]
    provinces = [
        {"province": r["province"], "total": int(r["total"] or 0), "schools": int(r["schools"] or 0)}
        for r in query_all(
            "SELECT province, SUM(`count`) AS total, COUNT(DISTINCT univ_id) AS schools "
            "FROM admission GROUP BY province ORDER BY total DESC")
    ]
    schools = [
        {"id": int(r["id"]), "name": r["name"], "total": int(r["total"] or 0),
         "majors": int(r["majors"] or 0)}
        for r in query_all(
            "SELECT u.id, u.name, SUM(a.`count`) AS total, COUNT(DISTINCT a.major) AS majors "
            "FROM admission a JOIN university u ON u.id = a.univ_id "
            "GROUP BY u.id, u.name ORDER BY total DESC")
    ]
    return ok({"years": years, "provinces": provinces, "schools": schools,
               "hasData": bool(years)})


# --------------------------------------------------------------------------- #
# 辅助：某所大学的招生专业明细（大学详情 / 学校联动）
# --------------------------------------------------------------------------- #
@app.get("/api/school_majors")
def api_school_majors():
    school = require_param("school")
    year = parse_year()
    province = (request.args.get("province") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit", "200")), 500))
    except ValueError:
        raise ApiError(1001, "参数 limit 必须为整数")

    rows = query_all(
        "SELECT id, name, province, level FROM university WHERE name = %s", (school,))
    if not rows:
        rows = query_all(
            "SELECT id, name, province, level FROM university WHERE name LIKE %s LIMIT 1",
            ("%" + school + "%",))
    if not rows:
        raise ApiError(1002, "未找到学校：%s" % school)
    univ = rows[0]

    where = ["univ_id = %s"]
    params: list = [univ["id"]]
    if year is not None:
        where.append("year = %s")
        params.append(year)
    if province:
        where.append("province = %s")
        params.append(province)
    params.append(limit)

    detail = query_all(
        "SELECT year, province, major, SUM(`count`) AS total FROM admission "
        "WHERE " + " AND ".join(where) + " "
        "GROUP BY year, province, major "
        "ORDER BY year DESC, province, total DESC LIMIT %s", tuple(params))

    return ok({
        "school": {"id": int(univ["id"]), "name": univ["name"],
                   "province": univ["province"], "level": univ["level"]},
        "rows": [
            {"year": int(r["year"]), "province": r["province"],
             "major": r["major"], "total": int(r["total"] or 0)}
            for r in detail
        ],
        "hasData": bool(detail),
    })


# --------------------------------------------------------------------------- #
# 辅助：桑基图数据（学校所在省/大学/专业大类 → 招生省份）
# --------------------------------------------------------------------------- #
MAJOR_CATEGORY_CSV = Path(__file__).resolve().parent / "data" / "major_categories.csv"
_major_category_cache: dict[str, str] | None = None


def major_category_map() -> dict[str, str]:
    """专业名 -> 大类；映射表不存在时全部归入“其他”。"""
    global _major_category_cache
    if _major_category_cache is None:
        mapping: dict[str, str] = {}
        if MAJOR_CATEGORY_CSV.exists():
            import csv as _csv
            with MAJOR_CATEGORY_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in _csv.DictReader(fh):
                    if row.get("major"):
                        mapping[row["major"]] = row.get("category") or "其他"
        _major_category_cache = mapping
    return _major_category_cache


@app.get("/api/sankey")
def api_sankey():
    """
    桑基图数据。

    level=province：学校所在省 -> 招生省份（默认）
    level=university：指定 province 下，学校 -> 招生省份
    level=major：指定 school 下，专业大类 -> 招生省份
    其他参数：year、target（招生省份过滤）
    """
    level = (request.args.get("level") or "province").strip()
    if level not in ("province", "university", "major"):
        raise ApiError(1001, "level 只能是 province / university / major")

    year = parse_year()
    target = (request.args.get("target") or "").strip()
    province = (request.args.get("province") or "").strip()
    school = (request.args.get("school") or "").strip()

    where = ["1 = 1"]
    params: list = []
    if year is not None:
        where.append("a.year = %s")
        params.append(year)
    if target:
        where.append("a.province = %s")
        params.append(target)

    if level == "province":
        select = "u.province AS src, a.province AS dst, SUM(a.`count`) AS value"
        group = "u.province, a.province"
    elif level == "university":
        if not province and not target:
            raise ApiError(1001, "缺少参数 province 或 target")
        if province:
            where.append("u.province = %s")
            params.append(province)
        select = "u.name AS src, a.province AS dst, SUM(a.`count`) AS value"
        group = "u.name, a.province"
    else:
        if not school:
            raise ApiError(1001, "缺少参数 school")
        where.append("u.name = %s")
        params.append(school)
        select = "a.major AS src, a.province AS dst, SUM(a.`count`) AS value"
        group = "a.major, a.province"

    sql = (
        "SELECT " + select + " FROM admission a "
        "JOIN university u ON u.id = a.univ_id "
        "WHERE " + " AND ".join(where) + " "
        "GROUP BY " + group
    )
    rows = query_all(sql, tuple(params))

    if level == "major":
        category_map = major_category_map()
        aggregated: dict[tuple[str, str], int] = {}
        for row in rows:
            category = category_map.get(row["src"], "其他")
            key = (category, row["dst"])
            aggregated[key] = aggregated.get(key, 0) + int(row["value"] or 0)
        links = [
            {"source": source, "target": dest, "value": value}
            for (source, dest), value in aggregated.items()
        ]
    else:
        links = [
            {"source": row["src"], "target": row["dst"], "value": int(row["value"] or 0)}
            for row in rows
        ]

    return ok({
        "level": level,
        "links": links,
        "total": sum(link["value"] for link in links),
        "filters": {"year": year, "target": target, "province": province, "school": school},
    })


# --------------------------------------------------------------------------- #
# 健康检查（辅助，不在 6 个业务接口内）
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def api_health():
    query_all("SELECT 1")
    return ok({"status": "ok", "database": db_settings()["database"]})


# --------------------------------------------------------------------------- #
# 前端大屏（阶段 4）
# --------------------------------------------------------------------------- #
DASHBOARD_FILE = Path(__file__).resolve().parent / "dashboard.html"


@app.get("/")
def index():
    """直接打开 http://127.0.0.1:5000/ 即可访问大屏（同源，无跨域问题）。"""
    return send_file(str(DASHBOARD_FILE))


def check_database() -> tuple[bool, str]:
    """启动时做一次数据库连通性检查，给人话提示而不是等接口 500。"""
    try:
        conn = pymysql.connect(**db_settings(), charset="utf8mb4", connect_timeout=3)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM university")
                count = cur.fetchone()[0]
            return True, "university 表 %d 行" % count
        finally:
            conn.close()
    except pymysql.MySQLError as exc:
        return False, str(exc).split("\n")[0][:160]


def port_in_use(host: str, port: int) -> bool:
    """判断端口是否已有服务在监听（用于给出「已有实例在运行」的友好提示）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def open_browser_later(url: str, delay: float = 1.2) -> None:
    def _open():
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="全国大学数据分析大屏 · Flask API")
    parser.add_argument("--host", default=APP_HOST)
    parser.add_argument("--port", type=int, default=APP_PORT)
    parser.add_argument("--db-host", default=None)
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-password", default=None)
    parser.add_argument("--open", dest="open_browser", action="store_true",
                        help="启动后自动打开浏览器")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    # 命令行参数优先于 config.py
    if args.db_host:
        DB_CONFIG["host"] = args.db_host
    if args.db_port:
        DB_CONFIG["port"] = args.db_port
    if args.db_user:
        DB_CONFIG["user"] = args.db_user
    if args.db_password is not None:
        DB_CONFIG["password"] = args.db_password

    db_ok, db_detail = check_database()
    print("=" * 64)
    print("  全国大学数据分析大屏 · 后端服务")
    print("  访问地址 : http://%s:%d/" % (args.host, args.port))
    print("  数据库   : %s@%s:%s/%s" % (
        DB_CONFIG["user"], DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["database"]))
    if db_ok:
        print("  连接状态 : [OK] 已连接（%s）" % db_detail)
    else:
        print("  连接状态 : [FAIL] 连接失败：%s" % db_detail)
        print("  处理建议 : 启动 MySQL 服务，或修改 config.py 中的账号密码后重试")
    print("=" * 64)

    url = "http://%s:%d/" % (args.host, args.port)
    if port_in_use(args.host, args.port):
        print("  端口提示 : 端口 %d 已被占用" % args.port)
        print("  处理建议 : 大屏可能已经在运行 → 直接打开 %s" % url)
        print("             如需重启：先关掉旧的 python app.py 窗口，或用 --port 5001 换端口")
        return 3

    if args.open_browser:
        open_browser_later(url)
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
