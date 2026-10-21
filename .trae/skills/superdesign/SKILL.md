---
name: superdesign
description: Systematically upgrade data-dashboard front-end visuals. Use when the user asks to polish optimize beautify or elevate a single-HTML dashboard with ECharts or similar. Do not use for greenfield pages or backend-only changes.
---

# SuperDesign — 前端数据大屏视觉升级

对已有的数据大屏（单 HTML + CSS + ECharts/Chart.js）进行系统性视觉升级。
不是推倒重来，是在保留现有结构和功能的基础上叠加高影响力的视觉层次。

## 前提检查

1. 确认项目可运行：启动服务 → 浏览器打开 → 截图确认 baseline。
2. 读一遍前端源码（通常一个 dashboard.html 里 CSS + JS 都有）。
3. 确认主题系统：是单主题还是 dark/light 双主题。OKLCH 变量优先，HSL/RGB 也可。

## 八步升级清单

按优先级顺序执行，每一步都验证无 JS 错误：

### 1. 语义化 accent 配色（CSS 变量扩展）
在 `:root` 和每个主题（如 `html[data-theme="light"]`）里添加：

```css
/* 深色主题示例 */
--accent-rank: oklch(0.985 0 0);          /* primary 白 */
--accent-score: oklch(0.55 0 0);          /* 中性灰 */
--accent-delta-up: oklch(0.75 0.14 150);  /* 升=绿 */
--accent-delta-down: oklch(0.74 0.16 25); /* 降=红 */
--accent-best: oklch(0.82 0.16 85);       /* 金 */
--accent-map: oklch(0.82 0.12 255);       /* 蓝紫 */
--accent-trend: oklch(0.985 0 0);          /* 白 */
--accent-province: oklch(0.75 0.14 150);  /* 绿 */
--accent-heat: oklch(0.85 0.14 280);      /* 紫 */
--accent-majors: oklch(0.80 0.16 50);     /* 橙 */
```

每个主题都要有一套对偶值，保持亮暗下都可读。

### 2. KPI 卡片微交互
给 `.kpi` 或类似的 KPI 元素：
- `::before` 伪元素做 2px 渐变 accent 条（`linear-gradient(90deg, transparent, var(--accent-trend), transparent)`）
- `hover` 时 `translateY(-2px) + filter: brightness(1.08)`
- 数字保持 tabular-nums，hover 时 accent 条 opacity 提升
- 若原有 `::before` 被用作分隔线，改用 `::after` 以免覆盖 accent 条

### 3. Score-strip 语义化
每个数据指标卡（如当前排名/总分/年度变化/历史最佳）分配不同 accent：
- 第 1 格 → `--accent-rank`（白/主色）
- 第 2 格 → `--accent-score`（中性灰）
- 第 3 格 → `--accent-delta-up`（绿/红随数据变）
- 第 4 格 → `--accent-best`（金）

每个 card 要：
- 顶部渐变 accent 条（`::after` 或 `::before`）
- 数字 `text-shadow: 0 0 20px var(--sc)` 发光
- hover 时 `translateY(-2px) + border-color 加深`
- 背景加一个 radial-gradient 微光晕 (`--cell-glow` 变量)

### 4. Panel 顶部 accent bar
给每个 `.panel` 或图表容器：
- `overflow: hidden`（clip the bar）
- `::before` 伪元素：`height: 3px`，`linear-gradient(90deg, var(--panel-accent), transparent)`
- hover 时 opacity 从 0.7 → 1.0
- 每个具体 panel id 分配专属 accent：`#mapPanel { --panel-accent: var(--accent-map) }` 等

### 5. 健康状态脉冲动画
给 footer 的健康状态指示器（`.status.ok i` / `.status.bad i`）：
- ok：`pulse-ok` 动画，2.2s 周期，box-shadow 扩散光圈效果
- bad：`pulse-bad` 动画，1.4s 周期，简单透明度闪烁

### 6. ECharts 趋势图 areaStyle 渐变
给 line chart 的主趋势线：
```javascript
areaStyle: {
  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
    { offset: 0, color: C.lineMainShadow },
    { offset: 1, color: "rgba(0,0,0,0)" }
  ]),
  opacity: 0.7
}
```
同时加强 `lineStyle` 的 `shadowBlur`（16）和 `shadowOffsetY`（4），让线有漂浮感。

### 7. ECharts 地图选中态发光
给 map series 的 `emphasis` 和 `select` 各加：
```javascript
emphasis: {
  itemStyle: { borderWidth: 1.5, shadowBlur: 14, shadowColor: "rgba(120,120,120,0.35)" }
},
select: {
  itemStyle: { borderWidth: 2, shadowBlur: 20, shadowColor: C.mapSelectArea }
}
```
label 加 `fontWeight: "bold"`。

### 8. 饼图 + 热力图圆角 & hover
饼图：
- `itemStyle.borderRadius: 3`（每个扇形圆角）
- `emphasis.scale: true, scaleSize: 8`（hover 弹出）
- `emphasis.itemStyle.shadowBlur: 18`

热力图：
- `itemStyle.borderRadius: 4`（格子圆角）
- `emphasis.itemStyle.shadowBlur: 8, shadowColor: C.heatEmph`（hover 发光）

## 双主题差异化（暗/亮）

不要只做颜色取反对偶，两种主题要有不同的视觉气质：

| 维度 | 深色 | 亮色 |
|------|------|------|
| 气质 | 深邃科技风 | 温暖纸感风 |
| 背景 | 带蓝紫调 `oklch(0.11 0.025 265)` | 暖黄纸底 `oklch(0.972 0.015 90)` |
| 前景 | 微暖白 `oklch(0.975 0.008 90)` | 暖深灰 `oklch(0.200 0.01 65)` |
| 卡片 | 蓝紫调 | 暖白 |
| 光晕 | 蓝紫高饱和 | 柔暖低饱和 |
| 阴影 | 深重 | 轻薄 |

实现要点：

1. **body 多层光晕**
```css
body::before {
  background:
    radial-gradient(ellipse 70% 55% at 50% 0%, var(--glow-primary) 0%, transparent 65%),
    radial-gradient(ellipse 50% 40% at 15% 100%, var(--glow-secondary) 0%, transparent 60%),
    radial-gradient(ellipse 50% 40% at 85% 100%, var(--glow-secondary) 0%, transparent 60%),
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: auto, auto, auto, 48px 48px, 48px 48px;
  mask-image: radial-gradient(ellipse 90% 80% at 50% 0%, black 20%, transparent 85%);
}
```

2. **header glass-morphism**
```css
header {
  background: var(--header-bg);            /* 半透明 */
  backdrop-filter: blur(var(--header-blur)) saturate(1.4);
  -webkit-backdrop-filter: blur(var(--header-blur)) saturate(1.4);
  box-shadow: var(--shadow-1), inset 0 1px 0 var(--border-strong);
}
```

3. **staggered 入场**：给 header 和每个 panel 递增 `animation-delay`（80/160/240/320/400ms），用 `riseIn` 而不是统一 `fadeIn`。

4. **统一主题过渡**：定义 `--theme-transition: 350ms var(--ease)`，body/header/panel/button/footer 的颜色、背景、边框、阴影都走这个时长。

5. **ECharts 延迟重绘**：主题切换后 `setTimeout(fn, 380)` 再重绘，让 CSS 过渡先跑完，避免图表闪一下。

6. **panel hover 浮起**：`transform: translateY(-2px)` + `shadow-2`。

## 验证流程

每完成 2-3 步就跑一轮：

1. 浏览器 Ctrl+Shift+R 硬刷新（必要时加 `?v=随机数` 绕缓存）
2. Dev console → 0 errors（必须）
3. 截图确认每个面板 accent bar、score-strip 四色、KPI 顶条
4. 交互测试：hover 地图 → 看发光；选省份 → 看选中态发光；hover 饼图 → 看放大发光；hover 热力图 → 看发光
5. 切换主题 → 确认两侧气质的差异真实存在，且所有元素对比度可读

## ECharts 颜色系统

- **不要把 oklch() 字符串直接传给 ECharts option**（ECharts 5.5.1 及更早版本的 zrender 颜色解析器不含 OKLCH 支持）。直绘时浏览器 canvas 能渲染 oklch，但**动画/状态切换时 zrender 要做颜色插值**，解析失败返回 undefined → 动画帧抛 `TypeError: Cannot read properties of undefined (reading 'length')`，且只在部分浏览器环境暴露，难排查。
- 正确做法：option 颜色统一经 canvas 栅格化转成 `rgba()`。运行时转换器（放在 chartTheme 前）：

```javascript
var _cssColorCtx = null;
function cssToRgba(str) {
  if (typeof str !== "string" || str.indexOf("oklch(") !== 0) return str;
  var m = str.match(/^oklch\(([^)]+)\)$/);
  if (!m) return str;
  var parts = m[1].split("/");
  var alpha = parts.length > 1 ? parseFloat(parts[1]) : 1;
  if (!_cssColorCtx) {
    var cv = document.createElement("canvas");
    cv.width = cv.height = 1;
    _cssColorCtx = cv.getContext("2d", { willReadFrequently: true });
  }
  _cssColorCtx.fillStyle = "#010203";
  _cssColorCtx.fillStyle = "oklch(" + parts[0].trim() + ")";
  if (_cssColorCtx.fillStyle === "#010203") return str;
  _cssColorCtx.clearRect(0, 0, 1, 1);
  _cssColorCtx.fillRect(0, 0, 1, 1);
  var d = _cssColorCtx.getImageData(0, 0, 1, 1).data;
  return "rgba(" + d[0] + "," + d[1] + "," + d[2] + "," + alpha + ")";
}
function rgbaTheme(raw) {
  var out = {};
  Object.keys(raw).forEach(function (k) {
    var v = raw[k];
    out[k] = Array.isArray(v) ? v.map(cssToRgba) : cssToRgba(v);
  });
  return out;
}
// chartTheme() 两个分支各自 return rgbaTheme({ ...oklch 令牌... });
```

- 同理，**不要在 series option 里放 `new echarts.graphic.LinearGradient` 渐变对象**——主题切换时渐变对象间的插值同样走崩溃路径。面积填充用纯色 + 低 `opacity`（如 `areaStyle: { color: C.lineMain, opacity: 0.15 }`）。
- `chartTheme()` 两个分支的返回对象要对称：颜色数量、语义、命名一致。
- CSS 侧（设计令牌、面板、卡片）继续用 OKLCH 没问题——崩溃只发生在 ECharts/zrender 的 JS 颜色插值路径。

## 约束

- 全程不改动 HTML 结构和后端 API 契约
- 所有新增 CSS 变量必须在双主题下都有值
- 尊重 `prefers-reduced-motion: reduce`（有就关掉 animation/transition）
- 不引入新的外部依赖（CDN、字体服务等），只用已有资源
- 保持数字 `font-variant-numeric: tabular-nums` 防止跳动
