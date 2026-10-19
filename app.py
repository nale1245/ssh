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

数据库：MySQL 5.7（库 university），连接信息从参数或环境变量读取：
    MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
    密码不写死、不给默认值；未配置时接口返回 code=5000 并提示。

启动：
    $env:MYSQL_PASSWORD="******"; python app.py
    python app.py --port 5000 --db-user root
"""

from __future__ import annotations

import argparse
import os

import pymysql
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

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


@app.errorhandler(Exception)
def handle_unexpected(err: Exception):
    app.logger.exception("未处理异常：%s", err)
    return jsonify({"code": 5000, "data": None, "message": "服务器内部错误"}), 500


# --------------------------------------------------------------------------- #
# 数据库
# --------------------------------------------------------------------------- #
def db_settings() -> dict:
    password = os.environ.get("MYSQL_PASSWORD")
    if password is None:
        raise ApiError(5000, "未配置数据库密码：请设置环境变量 MYSQL_PASSWORD 后重启服务")
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "root"),
        "password": password,
        "database": os.environ.get("MYSQL_DATABASE", "university"),
    }


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
# 健康检查（辅助，不在 6 个业务接口内）
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def api_health():
    query_all("SELECT 1")
    return ok({"status": "ok", "database": db_settings()["database"]})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="全国大学数据分析大屏 · Flask API")
    parser.add_argument("--host", default=os.environ.get("FLASK_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("FLASK_PORT", "5000")))
    parser.add_argument("--db-host", default=None)
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--db-user", default=None)
    parser.add_argument("--db-password", default=None)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    # 允许命令行覆盖环境变量（密码仅用于本进程，不落盘）
    if args.db_host:
        os.environ["MYSQL_HOST"] = args.db_host
    if args.db_port:
        os.environ["MYSQL_PORT"] = str(args.db_port)
    if args.db_user:
        os.environ["MYSQL_USER"] = args.db_user
    if args.db_password:
        os.environ["MYSQL_PASSWORD"] = args.db_password

    if not os.environ.get("MYSQL_PASSWORD"):
        print("❌ 未配置数据库密码：请设置 MYSQL_PASSWORD 或使用 --db-password")
        return 2

    print("全国大学数据分析 API 启动：http://%s:%d" % (args.host, args.port))
    print("数据库：%s@%s:%s/%s" % (
        os.environ.get("MYSQL_USER", "root"),
        os.environ.get("MYSQL_HOST", "127.0.0.1"),
        os.environ.get("MYSQL_PORT", "3306"),
        os.environ.get("MYSQL_DATABASE", "university"),
    ))
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
