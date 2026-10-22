# 全国大学数据分析大屏

基于 **软科大学排名（2021–2026）** 与 **掌上高考招生计划数据** 构建的全国高校数据可视化大屏项目。后端使用 Flask 提供 JSON API，前端基于 ECharts 实现大屏展示，支持地图分布、排名趋势、省份下钻、招生热力图、专业流向桑基图与科研/人才散点分析等多级交互。

## 功能特性

### P0 · 基础大屏
- 全国各省高校数量与 985 / 211 分布地图（`/api/map_data`）
- 任意高校历年排名趋势与总分变化（`/api/trend`）
- 科研得分 vs 人才培养得分散点分析（`/api/correlation`）
- 学校列表搜索 / 筛选（`/api/schools`）

### P1 · 院校详情与招生数据
- 省内大学列表 + 层次（985 / 211 / 双一流 / 普通）统计（`/api/province`）
- 招生计划爬虫：掌上高考公开 JSON 接口（`api.zjzw.cn`）采集 2021–2024 年招生计划
- 年份 × 省份招生人次热力图，支持框选联动查看专业招生情况（`/api/heatmap`、`/api/majors`）
- 招生筛选元数据（年份 / 省份 / 学校下拉）与学校专业明细（`/api/admission_meta`、`/api/school_majors`）

### P2 · 专业流向桑基图与科研/人才散点
- **三级下钻桑基图**（`/api/sankey`）：
  - `level=province`：学校所在省 → 招生省份（默认）
  - `level=university`：指定省份下，大学 → 招生省份
  - `level=major`：指定学校下，专业大类 → 招生省份
- 828 个专业按关键词归并为 12 大类 + 其他（`build_major_categories.py` → `data/major_categories.csv`）
- 详情页新增「科研 / 人才散点」，框选散点后可联动查看选中学校的排名趋势与专业招生

## 技术栈

| 层次 | 技术 |
|---|---|
| 后端 | Python 3.10+、Flask 3.1.3、flask-cors、PyMySQL |
| 数据 | pandas 2.3.3、numpy 2.2.4、requests、beautifulsoup4、lxml |
| 数据库 | MySQL 5.7（utf8mb4 / utf8mb4_unicode_ci） |
| 前端 | ECharts（本地 `static/vendor/echarts.min.js`）+ 原生 HTML / JS / CSS，单页 `dashboard.html` |

依赖清单见 `requirements.txt`（与本机 Python 3.10.19 实测版本一致）。

## 项目结构

```
ssh/
├── app.py                     # Flask 后端 API（12 个路由）
├── dashboard.html             # ECharts 大屏前端（单页）
├── config.py                  # 数据库与启动配置（支持环境变量覆盖）
├── schema.sql                 # MySQL 建库建表脚本（可重复执行）
├── requirements.txt           # 运行依赖
├── requirements-dev.txt       # 自检脚本依赖（check_dashboard.py 用）
├── start.bat                  # Windows 一键启动（等价 python app.py --open）
├── spider_ranking.py          # 软科排名爬虫（2021–2026，输出 data/rankings_raw.csv）
├── spider_admission.py        # 掌上高考招生计划爬虫（输出 data/admission_*_raw.csv）
├── load_data.py               # 软科数据清洗入库（university / ranking）
├── load_admission.py          # 招生数据清洗入库（admission / admission_cross）
├── build_major_categories.py  # 专业大类映射（828 专业 → 12 类 + 其他）
├── check_api.py               # 接口自检脚本
├── check_dashboard.py         # 大屏自动化自检脚本
├── data/                      # 原始与清洗后数据（CSV / JSON）
├── docs/                      # 阶段文档、接口文档、截图、实训报告
├── static/vendor/             # ECharts、中国地图 GeoJSON（china.json）
└── logs/                      # 爬虫与清洗日志
```

## 数据规模

`data/` 目录主要数据文件（行数均为不含表头的实测值）：

| 文件 | 说明 | 规模 |
|---|---|---|
| `rankings_raw.csv` | 软科排名原始数据（2021–2026 六年版） | 3535 行 / 603 校（每年约 582–594 校） |
| `clean_rankings.csv` | 清洗后排名明细（一校一年一条） | 3535 行 |
| `admission_cross_raw.csv` | 掌上高考跨省招生原始数据 | 51981 行 |
| `admission_clean.csv` | 跨省招生清洗后明细 | 42728 行（101 校 / 22 省 / 496 专业 / 约 31.9 万人次，2024 年） |
| `admission_local_raw.csv` | 各省本地招生原始数据 | 75601 行 |
| `admission_raw.csv` | 招生爬虫早期样例数据 | 3014 行 |
| `major_categories.csv` | 专业 → 大类映射 | 828 行（12 类 + 其他） |
| `admission_school_map.json` | 学校名 / slug 映射（清洗匹配用） | — |

> 说明：`admission_clean.csv` 由 `admission_cross_raw.csv` 清洗而来，入库到 `admission_cross` 表（桑基图专用，仅 2024 年、22 个有跨省数据的招生省份）；`admission` 表的 2024 年口径为「22 省跨省 + 9 省保留本省数据」，2021–2023 年为本省口径。

## 数据库说明

数据库：`university`（MySQL 5.7，字符集 utf8mb4），表结构见 `schema.sql`：

| 表 | 说明 |
|---|---|
| `university` | 学校基础信息：校名 / 省份 / 类型 / 层次（985 / 211 / 双一流 / 普通） |
| `ranking` | 历年软科排名：名次 / 总分 / 科研 / 人才培养 / 社会服务得分 / 星级，`(univ_id, year)` 唯一 |
| `admission` | 招生计划（P1）：学校 × 年份 × 省份 × 专业 × 人次 |
| `admission_cross` | 跨省招生数据（P2 桑基图专用，结构与 admission 相同） |
| `major_score` | 专业录取线（预留，先建空表） |

建表方式（二选一）：

```bash
mysql -u root -p < schema.sql
# 或推荐：python load_data.py --user root --password 你的密码   # 自动建库建表并入库
```

`load_data.py` 可重复执行：每次会清空 `university / ranking` 后全量重导，`admission / major_score` 不受影响。

## 环境准备

1. **Python 3.10+**（本项目在 Python 3.10.19 实测）
2. **MySQL 5.7**（服务需已启动，字符集 utf8mb4）
3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 数据库配置：账号密码默认写在 `config.py`（本机实训用），无需额外设置环境变量；如需覆盖可设置 `MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE`。

## 启动方法

```bash
python app.py          # 启动后端，浏览器访问 http://127.0.0.1:5000/
python app.py --open   # 启动后自动打开浏览器（推荐）
start.bat              # Windows 双击一键启动（等价于 python app.py --open）
```

- 换端口：`python app.py --port 5001`
- 覆盖数据库连接：命令行参数 `--db-host / --db-port / --db-user / --db-password`
- 启动时会自动检查数据库连通性，并检测端口占用（若端口被占会提示大屏可能已在运行）

### 数据准备流程（从零复现）

```powershell
python spider_ranking.py    # 1) 软科排名 2021-2026 → data/rankings_raw.csv
python load_data.py --user root --password 你的密码   # 2) 清洗入库 → university / ranking
python spider_admission.py --selection top-per-province --rank-year 2024 --top-per-province 10 --local --years 2021,2022,2023,2024 --out data/admission_local_raw.csv --rate 1.5 --resume --limit 0
python load_admission.py --csv data/admission_local_raw.csv   # 4) 清洗入库 → admission
```

跨省桑基图数据（`admission_cross`）由 `admission_cross_raw.csv` 经 `load_admission.py --table admission_cross` 清洗入库，已有数据时不必重跑。

## 功能接口一览

统一响应结构：`{"code": 0, "data": ..., "message": "ok"}`；`code`：`0` 成功、`1001` 参数缺失/非法、`1002` 数据不存在、`5000` 服务器内部错误（含数据库连接失败）。

| 接口 | 说明 | 主要参数 |
|---|---|---|
| `GET /` | 返回大屏页面 `dashboard.html` | — |
| `GET /api/map_data` | 各省学校数量与 985/211 数量（地图着色） | `year` |
| `GET /api/trend` | 某校历年排名趋势 | `school` |
| `GET /api/province` | 省内大学列表 + 层次统计 | `province`、`year` |
| `GET /api/correlation` | 科研 vs 人才培养散点 | `year` |
| `GET /api/heatmap` | 年份 × 省份招生人次热力图 | `year`（可选） |
| `GET /api/schools` | 学校列表（搜索 / 筛选） | `keyword`、`limit` |
| `GET /api/majors` | 专业招生情况（热力图框选联动） | `province`、`year`、`limit` |
| `GET /api/admission_meta` | 招生筛选元数据（年份 / 省份 / 学校下拉） | — |
| `GET /api/school_majors` | 某校招生专业明细 | `school`、`year`、`province` |
| `GET /api/sankey` | 桑基图三级下钻数据 | `level=province\|university\|major`、`year`、`target`、`province`、`school` |
| `GET /api/health` | 健康检查（数据库连通性） | — |

接口自检：`python check_api.py`；大屏自动化自检：`python check_dashboard.py`（需 `pip install -r requirements-dev.txt`）。

## 已知说明

- **数据库配置**：`config.py` 统一管理连接参数，内置本机 MySQL 账号密码；环境变量 `MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE` 与命令行 `--db-*` 参数均可覆盖（优先级：命令行 > 环境变量 > 配置文件）。⚠️ 本文件含明文密码，仅用于本机实训；若推送到 GitHub / 公网，请先改为环境变量或删除密码。
- **软科 500+ 排名**：软科排名中「500+」的学校统一记为哨兵值 `1000` 入库，前端展示为「500+」。
- **分项得分**：科研 / 人才培养 / 社会服务得分软科仅发布前 100 名，其余为空（NULL）；星级按名次分段派生（非软科官方字段）。
- **城市字段已取消**：按需求不建 `city` 字段；学校换过 slug 的同名同省条目已按并查集合并，取最新年份信息。
- **跨省数据范围**：桑基图仅覆盖 2024 年 22 个有跨省数据的招生省份；山西、内蒙古、河南、云南、西藏、陕西、青海、宁夏、新疆 9 省暂无跨省流向数据。
- **华北电力大学**：北京校区对应排名主条目「华北电力大学」；保定校区单独建为「华北电力大学（保定）」（河北）。
- **项目分支**：P2（桑基图 / 散点）位于 `feat/p2-cross-sankey` 分支，尚未合并 `main`。
