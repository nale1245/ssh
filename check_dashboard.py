#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
check_dashboard.py —— 阶段 4 前端大屏验收自检（Playwright 驱动本机 Chrome/Edge）

检查内容：
    1. 页面能打开，无 JS 报错 / console error
    2. 地图与折线两张 ECharts canvas 正常渲染
    3. KPI（上榜高校/985/211/覆盖省份）与接口数据一致
    4. 年份切换后地图数据刷新（2026 -> 590，2024 -> 594）
    5. 搜索换校后趋势图标题切换
    6. 点击省份有提示（地图交互可用）
    7. 截图保存到 docs/screenshots/

用法：
    python check_dashboard.py
    python check_dashboard.py --base http://127.0.0.1:5000 --chrome "C:\...\chrome.exe"

退出码：0 全部通过 / 1 有失败项 / 2 未找到浏览器
"""

from __future__ import annotations

import argparse
from pathlib import Path

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

PROJECT_ROOT = Path(__file__).resolve().parent
SCREENSHOT_DIR = PROJECT_ROOT / "docs" / "screenshots"


class Result:
    def __init__(self):
        self.ok = 0
        self.bad = 0

    def check(self, title: str, cond, detail: str = ""):
        if cond:
            self.ok += 1
            print("✅ %s%s" % (title, ("  (%s)" % detail) if detail else ""))
        else:
            self.bad += 1
            print("❌ %s%s" % (title, ("  (%s)" % detail) if detail else ""))


def find_chrome(explicit: str | None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() else None
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="阶段 4/5 大屏自检")
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    parser.add_argument("--chrome", default=None)
    args = parser.parse_args(argv)

    chrome = find_chrome(args.chrome)
    if not chrome:
        print("❌ 未找到 Chrome/Edge，可用 --chrome 指定路径")
        return 2

    from playwright.sync_api import sync_playwright

    res = Result()
    console_errors: list[str] = []
    page_errors: list[str] = []

    print("=" * 70)
    print("阶段 4/5 大屏自检：%s" % args.base)
    print("浏览器：%s" % chrome)
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: page_errors.append(str(exc)))

        page.goto(args.base, wait_until="networkidle", timeout=30000)
        page.wait_for_function("document.getElementById('kpiTotal').textContent !== '-'", timeout=15000)
        page.wait_for_timeout(1200)

        # 1) JS 错误
        res.check("页面无 JS 运行时错误", not page_errors, str(page_errors[:2]))
        res.check("控制台无 error 日志", not console_errors, str(console_errors[:3]))

        # 2) canvas
        canvases = page.locator("canvas").all()
        sizes = [(c.bounding_box() or {}).get("width", 0) for c in canvases]
        res.check("地图/趋势/饼图/热力图 canvas 均渲染",
                  len(canvases) >= 4 and all(w > 200 for w in sizes),
                  "%d 个 canvas，宽度 %s" % (len(canvases), [round(w) for w in sizes]))

        # 2.5) 健康状态灯
        health_class = page.locator("#healthStatus").get_attribute("class") or ""
        res.check("页脚显示服务正常", "ok" in health_class,
                  page.locator("#healthText").inner_text())

        # 3) KPI
        kpi = {k: page.locator("#" + k).inner_text().strip()
               for k in ["kpiTotal", "kpi985", "kpi211", "kpiProv"]}
        res.check("KPI 2026 上榜 590", kpi["kpiTotal"] == "590", str(kpi))
        res.check("KPI 985 = 37", kpi["kpi985"] == "37")
        res.check("KPI 211 = 97", kpi["kpi211"] == "97")
        res.check("KPI 覆盖省份 = 31", kpi["kpiProv"] == "31")

        # 4) 年份切换
        page.select_option("#yearSelect", "2024")
        page.wait_for_function("document.getElementById('kpiTotal').textContent === '594'", timeout=10000)
        res.check("切换 2024 年地图刷新为 594", page.locator("#kpiTotal").inner_text() == "594")
        res.check("地图标题年份更新", "2024" in page.locator("#mapMeta").inner_text())

        # 5) 搜索换校
        page.fill("#schoolInput", "浙江大学")
        page.click("#searchBtn")
        page.wait_for_function(
            "document.querySelector('#trendPanel h2').textContent.includes('浙江大学')",
            timeout=10000,
        )
        res.check("搜索换校后趋势标题切换", "浙江大学" in page.locator("#trendPanel h2").inner_text())

        # 6) 地图点击联动提示 + 省份下钻
        map_box = page.locator("#mapChart").bounding_box()
        if map_box:
            page.mouse.click(map_box["x"] + map_box["width"] * 0.52,
                             map_box["y"] + map_box["height"] * 0.55)
            page.wait_for_timeout(900)
            res.check("点击省份弹出提示",
                      "show" in (page.locator("#toast").get_attribute("class") or ""),
                      page.locator("#toast").inner_text())
            province_title = page.locator("#provinceTitle").inner_text()
            res.check("点击省份加载省内详情", "省份详情 ·" in province_title, province_title)
            res.check("省内学校列表非空",
                      page.locator("#schoolList .school-item").count() > 0,
                      "%d 所" % page.locator("#schoolList .school-item").count())

        # 6.5) 热力图 / 专业表格 + 框选联动
        res.check("招生热力图已渲染", page.locator("#heatmapChart canvas").count() > 0)
        res.check("专业招生表格存在",
                  page.locator("#majorsBody tr").count() >= 1,
                  page.locator("#majorsBody").inner_text()[:30])

        hm_box = page.locator("#heatmapChart").bounding_box()
        if hm_box:
            page.mouse.move(hm_box["x"] + 70, hm_box["y"] + 60)
            page.mouse.down()
            page.mouse.move(hm_box["x"] + hm_box["width"] - 50,
                            hm_box["y"] + hm_box["height"] - 45, steps=15)
            page.mouse.up()
            page.wait_for_timeout(1400)
            majors_meta = page.locator("#majorsMeta").inner_text()
            res.check("框选热力图联动专业表格", "框选" in majors_meta, majors_meta)

        # 6.8) 热力图分页 + 详情页
        pager = page.locator("#heatPageLabel").inner_text()
        res.check("热力图分页标示", "/" in pager, pager)
        page.click("#detailBtn")
        page.wait_for_timeout(1800)
        res.check("详情页打开", "show" in (page.locator("#detailPage").get_attribute("class") or ""))
        res.check("详情页默认年份", page.locator("#dYear").input_value() != "",
                  page.locator("#dYear").input_value())
        res.check("详情页默认省份", page.locator("#dProvince").input_value() != "",
                  page.locator("#dProvince").input_value())
        res.check("详情页标签存在", page.locator("#detailTabs button").count() >= 1,
                  str(page.locator("#detailTabs button").all_inner_texts()))
        page.click("#detailBack")
        page.wait_for_timeout(900)
        res.check("详情页返回总览", "show" not in (page.locator("#detailPage").get_attribute("class") or ""))

        # 7) 截图
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = SCREENSHOT_DIR / "p0_check.png"
        page.screenshot(path=str(shot), full_page=False)
        res.check("截图已保存", shot.exists(), str(shot))

        browser.close()

    print("=" * 70)
    print("通过 %d 项，失败 %d 项" % (res.ok, res.bad))
    print("结论：%s" % ("✅ 阶段 4/5 大屏自检通过" if res.bad == 0 else "❌ 存在失败项"))
    print("=" * 70)
    return 0 if res.bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())