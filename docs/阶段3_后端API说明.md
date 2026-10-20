# 阶段 3 · Flask 后端 API 说明（API-01 ~ API-06）

> 对应设计文档 v2 `4；执行日期 2026-10-19；状态：待人工确认
> 技术栈：Flask 3.1.3 + flask-cors 6.0.5 + PyMySQL 1.2.3 + MySQL 5.7.28

## 1. 交付物

| 产出 | 路径 | 说明 |
|---|---|---|
| 后端服务 | `app.py` | 6 个业务接口 + `/api/health` 健康检查，端口 5000 |
| OpenAPI 契约 | `docs/openapi.yaml` | 可直接导入 Apifox / Swagger Editor |
| 接口自检脚本 | `check_api.py` | 黑盒 HTTP 检查 53 项，退出码 0/1 |
| 依赖 | `requirements.txt` | 已含 Flask / flask-cors / PyMySQL |

## 2. 启动方式

```powershell
# 1) 确保 MySQL 5.7 服务已启动（Windows 服务名 MySQL）
Get-Service MySQL

# 2) 直接启动（账号密码在 config.py 中，已按使用要求内置）
python app.py
# 或双击 start.bat（自动打开浏览器）

# 可选参数
python app.py --port 5000 --db-user root --db-password 其他密码
```

配置来源：`config.py` 的 `DB_CONFIG`（默认 root / 123456 / university），
也可用环境变量 `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE`
或命令行参数临时覆盖。

> ⚠️ 明文密码仅用于本机实训；若要推 GitHub，请先改为环境变量并轮换密码。

## 3. 接口清单与返回样例

统一结构：`{"code": 0, "data": ..., "message": "ok"}`。
错误码：`1001` 参数缺失/非法、`1002` 数据不存在、`5000` 服务器内部错误。

### API-01 `GET /api/map_data?year=2026`
各省学校数量与 985/211 数量（`year` 可省略，默认最新年份）。
```json
{"code":0,"message":"ok","data":[
  {"province":"江苏","total":39,"is985":2,"is211":10},
  {"province":"山东","total":33,"is985":2,"is211":3},
  {"province":"河南","total":31,"is985":0,"is211":1}
]}
```

### API-02 `GET /api/trend?school=清华大学`
某校 6 年排名与总分；`school` 必填，精确匹配优先，找不到时模糊匹配。
```json
{"code":0,"message":"ok","data":{
  "years":[2021,2022,2023,2024,2025,2026],
  "ranks":[1,1,1,1,1,1],
  "scores":[969.2,999.4,1004.1,992.6,1076.1,1087.1]
}}
```

### API-03 `GET /api/province?province=广东`
省内层次统计 + 大学列表（按下拉年份的名次升序；`rankDisplay` 已是「500+」友好文本）。
```json
{"code":0,"message":"ok","data":{
  "year":2026,
  "levelStats":[{"level":"普通","count":20},{"level":"985","count":2},
                {"level":"双一流","count":2},{"level":"211","count":2}],
  "schools":[
    {"name":"中山大学","level":"985","rank":13,"rankDisplay":"13","score":597.6},
    {"name":"南方科技大学","level":"双一流","rank":30,"rankDisplay":"30","score":466.9}
  ]
}}
```

### API-04 `GET /api/correlation?year=2026`
科研 vs 人才培养散点，仅返回两个分数都存在的学校（软科只发布前 100 名，故每年前 100 个点）。
```json
{"code":0,"message":"ok","data":[
  {"name":"清华大学","research":116.2,"talent":333.0},
  {"name":"北京大学","research":116.8,"talent":330.5}
]}
```

### API-05 `GET /api/heatmap`
年份 × 省份 招生人次热力图结构。当前 `admission` 表为空（阶段 5 才爬），
返回完整坐标系 + `hasData:false`，前端可先渲染空网格。
```json
{"code":0,"message":"ok","data":{
  "years":[2021,2022,2023,2024,2025,2026],
  "provinces":["上海","云南","内蒙古","..."],
  "values":[],
  "hasData":false
}}
```
阶段 5 写入招生数据后，`values` 变为 `[[省份下标, 年份下标, 人次], ...]`，`hasData` 变 true。

### API-06 `GET /api/schools?keyword=清华&limit=50`
学校列表/搜索；`keyword` 与 `limit` 均可省略（默认返回 50 条，最多 500）。
```json
{"code":0,"message":"ok","data":[{"id":405,"name":"清华大学"}]}
```

### 辅助 `GET /api/health`
数据库连通性检查，返回 `{"status":"ok","database":"university"}`。

## 4. 验收自检结果

运行：`python check_api.py` → **通过 53 项，失败 0 项**。

覆盖点：
- 6 个接口 + health 全部 HTTP 200、统一结构、关键字段齐全
- `map_data`：31 个省级行政区；2026 合计 590 所、2024 合计 594 所（与库内一致）
- `trend`：清华大学 6 年数据，排名 [1,1,1,1,1,1]
- `province`：广东 26 所，按名次升序，层次统计与列表口径一致（26 = 26）
- `correlation`：100 个点（前 100 名口径）
- `heatmap`：6 年 × 31 省坐标系正确，`hasData=false`
- `schools`：关键词「清华」命中清华大学；无参默认 50 条
- 错误分支：`trend` 缺参 → 1001；学校不存在 → 1002；`year=abc` → 1001

## 5. 手动检查步骤（你也可以自己过一遍）

```powershell
# 0. 前置：MySQL 服务运行中
Get-Service MySQL

# 1. 启动 API（另开一个终端）
$env:MYSQL_PASSWORD="你的密码"
cd C:\Users\warn\Desktop\ssh
python app.py

# 2. 健康检查（应返回 code=0）
curl.exe "http://127.0.0.1:5000/api/health"

# 3. 逐个接口（PowerShell 里中文参数用 --data-urlencode）
curl.exe "http://127.0.0.1:5000/api/map_data?year=2026"
curl.exe -G "http://127.0.0.1:5000/api/trend" --data-urlencode "school=清华大学"
curl.exe -G "http://127.0.0.1:5000/api/province" --data-urlencode "province=广东"
curl.exe "http://127.0.0.1:5000/api/correlation?year=2026"
curl.exe "http://127.0.0.1:5000/api/heatmap"
curl.exe -G "http://127.0.0.1:5000/api/schools" --data-urlencode "keyword=清华"

# 4. 错误分支
curl.exe "http://127.0.0.1:5000/api/trend"                     # 期望 code=1001
curl.exe -G "http://127.0.0.1:5000/api/trend" --data-urlencode "school=不存在XYZ"  # 期望 code=1002
curl.exe "http://127.0.0.1:5000/api/map_data?year=abc"          # 期望 code=1001

# 5. 一键自检（最省事）
python check_api.py

# 6. 与数据库对账（可选，验证接口不是假数据）
$env:MYSQL_PWD="你的密码"
mysql -uroot -e "USE university; SELECT COUNT(*) FROM ranking WHERE year=2026;"   # 应 590
```

### Apifox 导入步骤
1. 打开 Apifox → 项目设置 → 导入数据 → OpenAPI/Swagger → 选择 `docs/openapi.yaml`
2. 导入后可看到 6 个接口（+health），服务器地址已填 `http://127.0.0.1:5000`
3. 逐个点「发送」，核对 HTTP 200 且 `code = 0`

## 6. 已知限制 / 与契约的差异

1. **heatmap 暂无数据**：`admission` 表为空，返回 `values: []` 与 `hasData: false`，不算失败；
   阶段 5 爬取写入后自动有数据，接口代码不用改。
2. **rank 哨兵值 1000**：`trend` 的 `ranks` 中 1000 表示「500+」，前端展示时替换；
   `province` 已额外提供 `rankDisplay` 可直接用。
3. **correlation 只有前 100 名**：软科分项分数只发布前 100 名，散点图点数为 100/年。
4. **错误响应 HTTP 状态码**：业务错误（1001/1002）按文档返回 HTTP 200 + 业务码；
   只有路由不存在/方法不允许等协议错误才用 4xx，且同样返回统一 JSON 结构。
5. **CORS 全开**：`CORS(app)` 允许前端大屏直接跨域调用。

## 7. 下一步（阶段 4）

- `dashboard.html`：中国地图省份着色 + 排名趋势折线（dataZoom）
- 地图用 `/api/map_data`，趋势用 `/api/trend`，选校用 `/api/schools`
- 深色科技风，1920×1080 自适应
