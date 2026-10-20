# 招生计划数据源探测报告（admission）

- 探测时间：2026-10-20
- 目标：为 admission(univ_id, year, province, major, count) 找公开、免登录、可批量采集的数据源
- 结论：**可用**。掌上高考（api.zjzw.cn）招生计划 JSON 接口，无需登录/Cookie/签名，字段完整，覆盖 23 个省份、2021–2024 年。

---

## 1. 可用来源

| 项目 | 内容 |
|---|---|
| 接口 | `https://api.zjzw.cn/web/api/` |
| 业务 uri | `apidata/api/gkv3/plan/school` |
| 方法 | GET |
| 鉴权 | 无（不需要 token / cookie / 加密参数） |
| 关键 header | `User-Agent`（普通 Chrome UA）、`Referer: https://www.gaokao.cn/` |
| 返回 | `application/json; charset=UTF-8`，`code=0000` 为成功 |

### 请求参数

| 参数 | 含义 | 示例 |
|---|---|---|
| school_id | 掌上高考学校 ID | 140（清华大学） |
| local_province_id | **招生省份** ID（不是学校所在省） | 41=河南，51=四川，11=北京 |
| local_type_id | 科类：1=理科，2=文科，3=综合（新高考） | 1 |
| year | 招生年份 | 2024 |
| page / size | 分页；**size 上限 20**，>20 返回空数组 | 1 / 20 |
| uri | 固定业务路径 | apidata/api/gkv3/plan/school |

完整示例（可直接浏览器/curl 打开）：

```
https://api.zjzw.cn/web/api/?school_id=140&local_province_id=41&local_type_id=1&year=2024&page=1&size=20&uri=apidata/api/gkv3/plan/school
```

### 学校名 → school_id

`uri=apidata/api/gk/school/lists&keyword=清华大学&page=1&size=10&request_type=1`
返回 item[].school_id / name，按 name 精确匹配即可。600 所学校需 600 次查询，建议缓存（脚本已带 school_map.json）。

---

## 2. 字段样例（真实返回，已截断）

```json
{
 "code": "0000",
 "message": "成功---success",
 "data": {
  "numFound": 21,
  "item": [{
    "school_id": "140",
    "name": "清华大学",
    "year": "2024",
    "local_province_name": "河南",
    "local_type_name": "理科",
    "local_batch_name": "本科一批",
    "sp_name": "工科试验班类",
    "level2_name": "工学",
    "level3_name": "计算机类",
    "spcode": "0809",
    "num": "12",
    "tuition": "5000",
    "length": "四年",
    "remark": "（包含专业：...）"
  }]
 }
}
```

映射到目标表：

| admission 字段 | 接口字段 |
|---|---|
| univ_id | 由 univ_name/univ_slug 关联 clean_rankings（脚本直接输出 univ_slug） |
| year | `year`（字符串，转 INT） |
| province | `local_province_name` |
| major | `sp_name`（招生专业名；大类招生时含方向说明，可退化用 level3_name） |
| count | `num`（字符串，转 INT） |
| 附加 | local_type_name（文/理/综合）、local_batch_name、tuition、spcode、remark |

注意：同一专业可能因批次/专业组/方向出现多行，count 不可跨行直接相加去重；入库建议保留 batch、spcode、local_type 作为区分列，或按 (year,province,major,batch,type) 聚合。

---

## 3. 实测规模与覆盖

小规模实抓：清华大学(140)、北京大学(31)、中山大学(104) × 河南(41)/四川(51)/北京(11) × 2023/2024：

- 18 个「学校×省×年」组合，**463 行**，约 25.7 行/组合；
- 单组合 4–44 行，`numFound` 与实际翻页一致；
- 河南 127 行、四川 177 行、北京 159 行。

### 年份
- 2021、2022、2023、2024 有数据；
- 2025、2026 实测 `numFound=0`（截至探测时接口未更新）。目标表 2025–2026 需留空或后续补源。

### 省份（用清华 2023 逐省扫描，自动尝试 type 3/1/2）
有数据 23 个：
北京、天津、山西、内蒙古、吉林、黑龙江、上海、浙江、安徽、江西、山东、河南、广西、海南、四川、贵州、云南、西藏、陕西、甘肃、青海、宁夏、新疆。

无数据 8 个：
河北(13)、辽宁(21)、江苏(32)、福建(35)、湖北(42)、湖南(43)、广东(44)、重庆(50)。

> 广东即使换 type 1/2/3 仍为 0，判断该接口未收录广东计划数据；东部几个高考大省缺失，热力图会缺角，报告中需注明。

### 行数估算
- 2000 行：约 80 个「学校×省×年」组合，约 100–130 次请求，**2–3 分钟**；
- 600 校 × 4 省 × 4 年 × 1.5 科类 ≈ 1.4 万组合，按 12–25 行/组合 ≈ **17–35 万行**，请求约 1.8 万次，按 1.2s/次约 **6 小时**；
- 推荐落地规模：600 校 × 23 省 × 4 年全量过大，先做 600 校 × 8–10 个代表省 × 4 年（约 2–4 万行，1–2 小时）。

---

## 4. 反爬与稳定性

- **无登录、无 Cookie、无签名**；只校验 UA/Referer 的概率低（实测带常规头即可）。
- `size>20` 不报错但返回 `data: []`，必须 20 条/页翻页。
- 未登录高频请求可能触发风控（返回空/验证码），建议：
  - 请求间隔 **≥1.2s**，单 IP 并发 1；
  - 每 200–300 次请求休息 30–60s；
  - 失败重试 2–3 次、指数退避；不要伪造登录态。
- 接口为掌上高考生产接口，字段/路径可能变动（历史上有 gkv3 版本号），脚本中已把 uri 集中为常量，便于替换。
- 合规：仅采集公开招生计划页面对应 JSON，控制频率，不绕过登录/付费墙；报告与脚本仅用于课程数据分析。

---

## 5. 阳光高考（gaokao.chsi.com.cn）探测结果

| 地址 | 方式 | 结果 |
|---|---|---|
| https://gaokao.chsi.com.cn/ | requests | **HTTP 412**，返回混淆 JS 挑战页 |
| https://gaokao.chsi.com.cn/ | Playwright + 本机真实 Chrome（有头，等待 6s） | 文档响应仍 **412**，但首页内容被 JS 渲染出来；Cookie 含 acw_tc/CHSICC 等 |
| https://gaokao.chsi.com.cn/zsjh/search.do?method=search | Playwright 真实 Chrome | **412/404**，路径不存在 |
| https://gaokao.chsi.com.cn/zsjh/search.do?method=search&provinceId=41&year=2024 | Playwright 真实 Chrome | **404** |

结论：412 是 CDN 反爬（acw_tc），真实 Chrome 可渲染首页但无法稳定拿到招生计划数据页；且计划查询路径已变更，**不推荐**作为主源。若必须使用，需要在浏览器内人工定位「招生计划」入口并处理动态表单，成本高、稳定性差。

其他试过但不可用的接口：
- `apidata/api/gk/plan/school` → `code 1064 接口请求版本不存在`
- `apidata/api/gkv4|gkv5|gkv2/plan/school` → 1064
- `apidata/api/gk/plan/special` → `code 1071 接口加密请求缺失`（需签名，未逆向）
- `apidata/api/gk/plan/school` 不带省份 → `code 1070`

---

## 6. 最小可运行脚本

文件：`_probe_admission/fetch_admission_plans.py`

```bash
cd C:UserswarnDesktopssh_probe_admission
python fetch_admission_plans.py
# 默认：20 校 × 河南/四川/北京/山东 × 2021-2024，约 1.2 万行，10-15 分钟
```

常用参数：

```bash
# 快速验证（1 校 1 省 1 年，约 10 秒）
python fetch_admission_plans.py --limit 1 --provinces 41 --years 2024 --out smoke.csv

# 凑 2000+ 行（40 校 × 河南 × 4 年，约 5 分钟）
python fetch_admission_plans.py --limit 40 --provinces 41 --years 2021,2022,2023,2024

# 多省热力图（60 校 × 8 省 × 2024，约 20 分钟）
python fetch_admission_plans.py --limit 60 --provinces 41,51,11,37,33,31,46,62 --years 2024
```

输出 `admission_plans.csv`（utf-8-sig），列：
univ_slug, univ_name, school_id, year, province, local_type, major, batch, count, tuition, spcode, remark。

脚本内置：1.2s 限速、失败重试、20 条/页翻页、学校 ID 缓存、新高考省份自动用 type=3。
运行环境：Python 3.10+，仅标准库，无需 playwright/requests。

---

## 7. 建议

1. **采用掌上高考接口作为主源**，先跑 600 校 × 河南/四川/北京/山东/浙江 5 省 × 2021-2024，约 1–2 万行，足够大屏演示。
2. 入库时 `count` 转 INT，保留 local_type/batch 以处理重复专业行；缺失省份在页面上标注「暂无公开数据」。
3. 2025/2026 数据待官方更新后再补；若必须覆盖广东/江苏/湖北等 8 省，建议改从各省考试院「招生计划」PDF/Excel 或阳光高考人工导出补充。
4. 控制频率 ≥1.2s，单线程，避免对公开服务造成压力。
