#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_api.py —— 阶段 3 接口验收自检（黑盒 HTTP 检查）

对运行中的 Flask 服务逐个请求 6 个接口 + 错误分支，校验：
    - HTTP 状态码 200
    - 统一响应结构 {code, data, message}
    - 各接口关键字段、数据量、排序
    - 参数缺失/非法/学校不存在时的错误码（1001 / 1002）

用法：
    python check_api.py
    python check_api.py --base http://127.0.0.1:5000

退出码：0 全部通过 / 1 有失败项
"""

from __future__ import annotations

import argparse
import sys

import requests


class Checker:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.passed = 0
        self.failed = 0

    def get(self, path: str, **params):
        return requests.get(self.base + path, params=params, timeout=10)

    def check(self, title: str, condition, detail: str = ""):
        if condition:
            self.passed += 1
            print("✅ %s%s" % (title, ("  (%s)" % detail) if detail else ""))
        else:
            self.failed += 1
            print("❌ %s%s" % (title, ("  (%s)" % detail) if detail else ""))


def envelope(resp, checker: Checker, title: str) -> dict | None:
    checker.check(title + " HTTP 200", resp.status_code == 200, "status=%s" % resp.status_code)
    try:
        body = resp.json()
    except ValueError:
        checker.check(title + " 返回 JSON", False)
        return None
    checker.check(
        title + " 统一结构",
        set(["code", "data", "message"]).issubset(body.keys()),
        "keys=%s" % sorted(body.keys()),
    )
    return body


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="阶段 3 接口验收自检")
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    args = parser.parse_args(argv)

    c = Checker(args.base)
    print("=" * 70)
    print("阶段 3 接口自检：%s" % c.base)
    print("=" * 70)

    # 0) 健康检查
    body = envelope(c.get("/api/health"), c, "[health]")
    if body:
        c.check("[health] code=0", body["code"] == 0, "code=%s" % body["code"])

    # 1) API-01 map_data
    body = envelope(c.get("/api/map_data"), c, "[map_data]")
    if body and body["code"] == 0:
        rows = body["data"]
        c.check("[map_data] 非空", len(rows) > 0, "%d 个省份" % len(rows))
        c.check(
            "[map_data] 字段完整",
            all(set(["province", "total", "is985", "is211"]).issubset(r) for r in rows),
        )
        total = sum(r["total"] for r in rows)
        c.check("[map_data] 2026 合计 590 所", total == 590, "total=%d" % total)
        top = rows[0]
        print("      样例：%s 共 %d 所（985 %d / 211 %d）" % (
            top["province"], top["total"], top["is985"], top["is211"]))
    else:
        c.check("[map_data] code=0", False)

    body = envelope(c.get("/api/map_data", year=2024), c, "[map_data?year=2024]")
    if body and body["code"] == 0:
        c.check("[map_data?year=2024] 合计 594 所",
                sum(r["total"] for r in body["data"]) == 594)

    # 2) API-02 trend
    body = envelope(c.get("/api/trend", school="清华大学"), c, "[trend]")
    if body and body["code"] == 0:
        d = body["data"]
        c.check("[trend] 6 个年份", d["years"] == [2021, 2022, 2023, 2024, 2025, 2026],
                str(d["years"]))
        c.check("[trend] 逐年名次与分数", len(d["ranks"]) == 6 and len(d["scores"]) == 6)
        c.check("[trend] 清华 2021 第 1 名", d["ranks"][0] == 1, "ranks=%s" % d["ranks"])
    else:
        c.check("[trend] code=0", False)

    body = envelope(c.get("/api/trend"), c, "[trend 缺参]")
    if body:
        c.check("[trend 缺参] code=1001", body["code"] == 1001, "code=%s" % body["code"])

    body = envelope(c.get("/api/trend", school="不存在的大学XYZ"), c, "[trend 不存在]")
    if body:
        c.check("[trend 不存在] code=1002", body["code"] == 1002, "code=%s" % body["code"])

    # 3) API-03 province
    body = envelope(c.get("/api/province", province="广东"), c, "[province]")
    if body and body["code"] == 0:
        d = body["data"]
        c.check("[province] levelStats 非空", len(d["levelStats"]) > 0)
        c.check("[province] schools 非空", len(d["schools"]) > 0,
                "%d 所" % len(d["schools"]))
        c.check("[province] 学校按名次升序",
                d["schools"] == sorted(d["schools"], key=lambda s: s["rank"] or 99999))
        c.check("[province] 含 rankDisplay", "rankDisplay" in d["schools"][0])
        c.check("[province] 层次统计与列表口径一致",
                sum(x["count"] for x in d["levelStats"]) == len(d["schools"]),
                "%d vs %d" % (sum(x["count"] for x in d["levelStats"]), len(d["schools"])))
        print("      样例：%s（%s，第 %s 名）" % (
            d["schools"][0]["name"], d["schools"][0]["level"], d["schools"][0]["rankDisplay"]))
    else:
        c.check("[province] code=0", False)

    body = envelope(c.get("/api/province"), c, "[province 缺参]")
    if body:
        c.check("[province 缺参] code=1001", body["code"] == 1001)

    # 4) API-04 correlation
    body = envelope(c.get("/api/correlation"), c, "[correlation]")
    if body and body["code"] == 0:
        rows = body["data"]
        c.check("[correlation] 非空", len(rows) > 0, "%d 个点" % len(rows))
        c.check(
            "[correlation] 字段完整",
            all(set(["name", "research", "talent"]).issubset(r) for r in rows),
        )
        c.check("[correlation] 每年前 100 名口径", len(rows) <= 100,
                "%d 个点" % len(rows))
    else:
        c.check("[correlation] code=0", False)

    # 5) API-05 heatmap
    body = envelope(c.get("/api/heatmap"), c, "[heatmap]")
    if body and body["code"] == 0:
        d = body["data"]
        c.check("[heatmap] 6 个年份", len(d["years"]) == 6, str(d["years"]))
        c.check("[heatmap] 31 个省份", len(d["provinces"]) == 31,
                "%d 个" % len(d["provinces"]))
        c.check("[heatmap] values 为列表", isinstance(d["values"], list))
        if d["hasData"]:
            c.check("[heatmap] 有数据时 values 非空", len(d["values"]) > 0,
                    "%d 个格子" % len(d["values"]))
            c.check("[heatmap] 坐标下标在范围内",
                    all(0 <= v[0] < len(d["provinces"]) and 0 <= v[1] < len(d["years"])
                        for v in d["values"]))
        else:
            c.check("[heatmap] 无数据时 hasData=false 且 values 为空",
                    d["values"] == [], "阶段 5 爬取导入后应变为 true")
    else:
        c.check("[heatmap] code=0", False)

    # 6) API-06 schools
    body = envelope(c.get("/api/schools", keyword="清华"), c, "[schools]")
    if body and body["code"] == 0:
        names = [r["name"] for r in body["data"]]
        c.check("[schools] 命中清华大学", "清华大学" in names, str(names[:3]))
        c.check("[schools] id/name 字段", all(set(["id", "name"]).issubset(r) for r in body["data"]))

    body = envelope(c.get("/api/schools"), c, "[schools 无参]")
    if body and body["code"] == 0:
        c.check("[schools 无参] 默认 50 条", len(body["data"]) == 50,
                "%d 条" % len(body["data"]))

    # 6.5) 辅助接口：专业招生
    body = envelope(c.get("/api/majors", province="河南", year=2024), c, "[majors]")
    if body and body["code"] == 0:
        c.check("[majors] rows 为列表", isinstance(body["data"]["rows"], list))
        has_data = body["data"]["hasData"]
        c.check("[majors] rows 与 hasData 一致",
                (len(body["data"]["rows"]) > 0) == has_data)

    # 7) 参数校验：year 非法
    body = envelope(c.get("/api/map_data", year="abc"), c, "[year=abc]")
    if body:
        c.check("[year=abc] code=1001", body["code"] == 1001, "code=%s" % body["code"])

    print("=" * 70)
    print("通过 %d 项，失败 %d 项" % (c.passed, c.failed))
    print("结论：%s" % ("✅ 阶段 3 接口自检通过" if c.failed == 0 else "❌ 存在失败项"))
    print("=" * 70)
    return 0 if c.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())