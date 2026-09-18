# 接口调试工具箱 (DevToolbox) - SKILL

> 最终版本 · 轻量级浏览器端接口调试工具，零依赖，双击即用。

## 项目概述

纯前端单页应用 + Python 标准库后端，集**九大功能模块**于一体：JSON 解析、异步任务轮询、HTTP 接口测试、WebSocket 调试、开发者工具集（计算器/进制转换/时间戳/Cron 表达式/编解码/正则测试/内容比对/在线白板）、书签管理、番茄钟、剪贴板历史（系统级监听，支持文本与截图图片）、滚动提醒（本地大字滚动展示）。支持局域网共享、配置分类保存、搜索高亮、树形折叠展示、常用网址云端持久化。

**设计理念**：零第三方依赖、零构建步骤、单文件前端、单文件后端，开箱即用。

## 技术栈

- **后端**: Python 3 标准库 `http.server`（静态文件 + API 代理 + 配置/书签/番茄钟/剪贴板 CRUD）+ `ctypes` Windows 剪贴板监听线程（文本 + 截图位图）
- **前端**: 原生 HTML / CSS / JavaScript（无框架、无 npm、无打包）
- **数据存储**:
  - `saved_requests.json` — 接口测试配置（共享）
  - `bookmarks.json` — 书签数据（共享）
  - `whiteboard.json` — 白板画布内容（共享，矢量笔画数据）
  - `pomodoro.json` — 番茄钟任务与统计（共享）
  - `clipboard.json` — 剪贴板历史（共享，服务器所在机器的系统剪贴板）
  - `clipboard_files/` — 剪贴板图片 PNG 文件（与 clipboard.json 记录一一对应）
  - `pet_state.json` — 桌面宠物联动状态（番茄钟运行态 + 一次性通知，宠物轮询用）
  - 浏览器 localStorage — 个人设置与本地缓存
- **跨域方案**: 服务端代理转发 + 自动添加 CORS 头

## 文件结构

```
jsonParesTools/
├── index.html              # 前端单页应用（所有 UI + JS 逻辑）
├── server.py               # Python 服务器（静态服务 + 代理 + 配置/书签/白板/番茄钟/剪贴板 API + 剪贴板监听）
├── saved_requests.json     # 持久化的接口配置（自动生成，可备份/迁移）
├── bookmarks.json          # 持久化的书签数据（自动生成，可备份/迁移）
├── whiteboard.json         # 持久化的白板画布（自动生成，可备份/迁移）
├── pomodoro.json           # 持久化的番茄钟数据（自动生成，可备份/迁移）
├── clipboard.json          # 持久化的剪贴板历史（自动生成，含敏感信息请谨慎备份）
├── clipboard_files/        # 剪贴板图片 PNG 文件目录（自动生成，含敏感截图请谨慎备份）
├── pet_state.json          # 桌面宠物联动状态（番茄钟运行态，自动生成）
├── pet.py                  # 桌面宠物（独立小程序：透明置顶矢量小生物，pythonw 运行）
├── 启动服务器.bat           # Windows 双击启动脚本（自动清理端口 + 启动 + 打开浏览器）
├── 启动宠物.bat            # 双击启动桌面宠物（pythonw 无控制台窗口）
└── SKILL.md                # 本文档
```

## 端口

默认端口：**6868**

- 本机: http://localhost:6868
- 局域网: http://<本机IP>:6868

修改端口：编辑 `server.py` 末尾 `port = 6868`，同步修改 `启动服务器.bat` 中的端口号。

## Python 服务的作用

1. **静态文件服务器** — 提供 `index.html` 访问，监听 `0.0.0.0:6868` 支持局域网
2. **API 代理（核心）** — 解决浏览器同源策略限制，转发 GET/POST/DELETE/OPTIONS 请求，透传自定义请求头
3. **配置存储 API** — 读写 `saved_requests.json`，实现接口配置的增删改查和局域网共享
4. **书签存储 API** — 读写 `bookmarks.json`，实现书签数据的服务器端持久化
5. **白板存储 API** — 读写 `whiteboard.json`，实现白板画布的服务器端持久化与多设备同步
6. **番茄钟存储 API** — 读写 `pomodoro.json`，实现任务清单与专注统计的持久化共享
7. **剪贴板监听 + 存储 API** — `ctypes` 后台线程监听 Windows 系统剪贴板（序号轮询，**文本 + 截图位图**），读写 `clipboard.json` 与 `clipboard_files/`
8. **宠物联动状态 API** — 读写 `pet_state.json`，前端番茄钟上报运行态，桌面宠物（pet.py）轮询消费

> 仅用 JSON 解析和开发者工具 Tab 时可直接双击 `index.html` 打开；涉及跨域请求、配置/书签/白板/番茄钟共享与持久化时必须启动 Python 服务（书签、白板、番茄钟未启动服务时自动降级为 localStorage 本地模式；剪贴板历史在服务器不可用时隐藏入口）。滚动提醒为纯前端功能，不依赖服务器。
> WebSocket 不走代理（WebSocket 协议本身不受同源策略限制，浏览器直连）。

---

## 九大功能模块

### 1. JSON 解析 (`tab-parser`)

- 粘贴任意 JSON 字符串，一键解析为可折叠树形视图
- `smartParse()` 自动递归解包嵌套 JSON 字符串（如接口返回的 `result` 字段是转义 JSON）
- 默认全部收起，点击 ▶/▼ 展开；支持全部展开/全部收起、复制结果
- 收起时预览前 **10 个子项**（`white-space: nowrap` 不换行），超出显示 `…`
- 搜索高亮：实时匹配键名和值，自动展开含匹配项的父节点，▲▼ 键盘导航

**核心函数**:
- `smartParse(text)` — 递归解析 JSON，自动解包嵌套 JSON 字符串
- `renderValue(value, key, isRoot, depth, compact)` — 递归渲染树形 DOM
- `previewValue(v)` — 收起状态下的预览值渲染
- `toggleNode(id)` / `expandAll(treeId)` / `collapseAll(treeId)` — 展开收起
- `performSearch(treeId)` — TreeWalker 遍历文本节点搜索高亮
- `highlightTerm(el, term)` / `searchNext(treeId)` / `searchPrev(treeId)` — 高亮与导航

### 2. 异步任务查询 (`tab-task`)

- 单个 URL 输入框（自动补全 `http://`），GET 请求轮询异步接口
- 自定义请求头表格（Key/Value 动态增删，持久化到 localStorage）
- 按设定间隔自动轮询，进度条 + 状态信息实时更新
- `status=4` 自动停止，解析 `data.result` 中的嵌套 JSON
- `status=5` 或网络错误自动停止并提示
- 支持配置分类保存/加载

**核心函数**:
- `pollTask()` — 发起单次轮询请求（通过 `/proxy` 代理，传递 `X-Proxy-Headers`）
- `startTaskQuery()` / `stopTaskQuery()` — 轮询生命周期管理（`setInterval`）
- `addTaskHeaderRow()` / `getTaskHeaders()` / `setTaskHeaders(headers)` — 请求头管理
- `saveTaskConfig()` / `loadTaskSaved()` — 配置保存/加载（调用通用 `saveConfig`）

### 3. 接口测试 (`tab-apitest`)

- GET / POST 方法切换（GET 绿色、POST 橙色），POST 时自动显示请求体编辑区
- 动态请求头表格、JSON 请求体格式化按钮
- 通过代理发送请求，绕过浏览器跨域限制
- 响应展示：状态码（带颜色）、耗时(ms)、响应大小(KB/MB) + JSON 树形视图 + 搜索
- 配置分类保存（名称 + 分类），下拉框按分类 `<optgroup>` 分组

**核心函数**:
- `sendApiRequest()` — 通过代理发送 GET/POST，传递 `X-Proxy-Headers`，计算耗时和大小
- `getHeaders()` / `setHeaders(headers)` / `addHeaderRow()` — 请求头管理
- `formatApiBody()` — JSON 请求体格式化
- `updateMethodColor()` — 根据 GET/POST 切换方法选择器颜色

### 4. WebSocket (`tab-websocket`)

- 浏览器原生 WebSocket 直连（无需代理）
- 支持 `ws://` 和 `wss://`，自动补全协议前缀
- 状态指示：未连接（灰）、连接中（黄闪烁）、已连接（绿脉冲动画）、已断开（红）
- 深色终端风格消息记录：↑发送（蓝色）、↓接收（绿色）、系统消息（灰色）、错误（红色）
- **JSON 消息默认树形展示**（根节点自动展开），可切换查看格式化原始字符串
- 非 JSON 消息直接显示原始文本
- Enter 发送 / Shift+Enter 换行、自动滚动（可关闭）、一键清空
- 可选断线自动重连（3 秒间隔），手动断开不触发重连
- 支持配置分类保存/加载

**核心函数**:
- `wsConnect()` / `wsDisconnect()` — 连接管理 + onopen/onmessage/onerror/onclose 回调
- `wsAppendMsg(type, content)` — 消息渲染（自动 `JSON.parse` 判断类型）
- `wsToggleTree()` / `wsToggleRaw()` — 树形视图/原始文本切换
- `wsSend()` / `wsFormatBody()` — 发送消息 / 格式化 JSON
- `wsReconnectTimer` — 自动重连定时器管理

### 5. 开发者工具 (`tab-devtools`)

内含八个子 Tab（`.subtabs` 子导航），所有计算均为**纯前端完成**，不依赖 Python 服务。

#### 5.1 标准计算器 (`subtab-calc`)
- 完整按键面板：数字、加减乘除、括号、百分比、退格、清除
- 支持开方 √、平方 x²、幂运算 xʸ（xʸ 按钮插入 `**`，即 JS 幂运算符）
- **表达式过程行**（`.calc-expr`）：输入时实时显示当前完整算式，按 `=` 后算式上移到过程行、结果显示在主显示屏，连续运算时可回顾上一步
- **可见闪烁光标**：显示屏为受控 `<input>`（非 `readonly`），通过 `caret-color: #2563eb` 显示蓝色光标，支持鼠标点击定位和文本选择
- **键盘直接输入 + 粘贴过滤**：支持数字、运算符、小数点直接键入，Enter=等于、Backspace=退格、Esc=清除；通过 `beforeinput` 事件拦截非法字符（`calcInsertText` 只保留 `[0-9.+\-*/%()]`），粘贴内容自动过滤
- **光标位置智能处理**：初始空状态（`calcExpr === ''` 且显示 `"0"`）下，聚焦/点击后光标自动置于 `"0"` 之后（`calcDisplayPos()`），视觉自然
- 历史记录侧栏，点击历史项可恢复结果，自动持久化到 localStorage（最多50条）
- 安全表达式校验（token 白名单匹配），防止代码注入

**核心函数**:
- `calcInput(v)` / `calcEquals()` / `calcClear()` / `calcBack()` / `calcParen()` — 计算操作
- `calcSafeEval(expr)` — 安全表达式求值（正则白名单 + `new Function`）
- `calcDisplayPos()` — 将光标定位到显示屏末尾（清空状态"0"之后）
- `addCalcHistory()` / `loadCalcHistory()` / `saveCalcHistory()` — 历史记录管理

#### 5.2 程序员计算器 (`subtab-programmer`)
- 输入数字实时显示 **二/八/十/十六进制** 四种结果（2×2 卡片网格）
- 支持 `0x`、`0o`、`0b` 前缀输入，也支持直接输入纯十六进制（如 `FF`）
- 点击任意进制结果**一键复制**
- 位运算：AND、OR、XOR、NOT、左移/右移(n)、循环左移/右移(1位)
- 使用 `BigInt` 支持大整数运算

**核心函数**:
- `parseProgNumber(s)` — 智能解析各种进制数值为 BigInt
- `progConvert()` — 实时转换并显示四种进制
- `progBit(op)` / `progApplyBit()` — 位运算
- `addProgHistory()` — 运算历史

#### 5.3 时间戳转换 (`subtab-timestamp`)
- 顶部**实时刷新**当前秒级/毫秒级时间戳（蓝色渐变卡片，每秒更新），点击复制
- 时间戳 → 日期时间（自动识别秒/毫秒，显示本地时间+UTC）
- 日期时间 → 时间戳（datetime-local 选择器，同时输出秒和毫秒）
- **日期加减**：基准时间 + N 单位（周/天/时/分/秒，N 可为负数），结果同时给出秒/毫秒时间戳与星期；结果区点击复制秒级时间戳
- **时长计算**：两个时间点相差多久——双视图：`N 天 HH:MM:SS` 精确时长（附总秒数/小时数/天数）+ 按日历的自然维度拆解（X 年 X 个月 X 天 X 小时…，跨月按日历算）；结束早于开始自动取绝对值并提示

**核心函数**:
- `updateTsNow()` / `startTsClock()` — 实时时钟
- `tsToDate()` — 时间戳转日期
- `dateToTs()` — 日期转时间戳
- `calcDateAdd()` — 日期加减（毫秒单位乘算，闰年/跨月由 Date 自动处理）
- `calcDuration()` — 时长计算（绝对毫秒差 + 日历维度借位拆解：日不够借上月天数、月不够借年）

#### 5.4 Cron 表达式 (`subtab-cron`)
- **支持 5 字段**（分 时 日 月 周）**和 6 字段**（带秒）表达式，输入即解析
- **中文描述生成**：表达式转自然语言（如 `0 9 * * 1-5` → "每周一 到 周五 9 点整"）
- **未来 5 次执行时间预览**：含"多久后"相对时间
- **字段解析表**：每个字段展开显示匹配值集合（连续值压缩为段）与特殊标记
- **完整语法**：`*` `,` `a-b` `*/n` `a-b/n` `?`；特殊字符 `L`（最后一天/最后一个周x）、`W`（最近工作日）、`x#y`（第 y 个周 x）；周字段支持 `MON-SUN` 名称、月字段支持 `JAN-DEC` 名称
- **标准 cron 语义**：日与周同时指定时为 OR 关系
- 10 个常用模板下拉（每分钟/工作日 9 点/每月 1 号/带秒每 30 秒等）
- 语法错误即时红色提示（字段数、范围越界、无效值）

**核心函数**:
- `cronParse(expr)` — 解析为结构化字段（每字段 `{any, values:Set, specials[], desc}`）
- `cronParseSimple(expr, meta)` / `cronParseField(expr, meta)` — 单表达式/整字段（含逗号列表）解析，desc 为最终中文描述
- `cronDayMatches(t, dayF, weekF)` — 日匹配（L/W/# 特殊语义 + 日周 OR）
- `cronNextTime(parsed, from)` — 下次执行时间（月→日→时→分→秒智能跳跃，5 年搜索上限，闰年正确）
- `cronDescribe(parsed)` — 中文描述组合
- `cronRun()` / `cronUseTemplate()` — 入口渲染 / 模板填充

#### 5.5 编解码工具 (`subtab-codec`)
左右双栏布局（输入→结果），四组编解码：

| 工具 | 函数 | 说明 |
|------|------|------|
| URL 编解码 | `codecUrlEncode/Decode()` | `encodeURIComponent` / `decodeURIComponent` |
| Base64 编解码 | `codecBase64Encode/Decode()` | 支持中文（UTF-8 安全，`btoa`+`encodeURIComponent`） |
| Unicode 转中文 | `codecUnicodeEncode/Decode()` | `你好` ↔ `\u4f60\u597d` |
| JSON 转义/反转义 | `codecJsonEscape/Unescape()` | `{"a":"b"}` ↔ `"{\"a\":\"b\"}"` |

#### 5.6 正则测试 (`subtab-regex`)
实时正则匹配测试器，输入即测。位于「编解码工具」之后的子 Tab。

- **输入即测**：正则、测试文本、替换串任一变化即重跑（`oninput` 直连 `rxRun()`），无「执行」按钮
- **flags 勾选**：g（全局）/ i（忽略大小写）/ m（多行）/ s（点号匹配换行），实时显示在正则右侧（`/pattern/gi` 形式）；无 g 时仅匹配首个并提示
- **常用模板**：下拉选择手机号/邮箱/URL/IPv4/日期/时间/中文/身份证/十六进制颜色/数字 10 个模板（`<select id="rxTemplate">` 的 option value 即正则源，选择后填充并自动执行，随后复位便于重复选择）
- **匹配高亮**：黄色 `<mark>` 高亮全部匹配；文本按匹配区间分段转义后拼接（防 XSS）；高亮盒独立滚动（max-height 240px）
- **匹配详情**：每条显示 `#序号 [start, end) 匹配文本` + 捕获组徽标（`$1=xxx`，命名组粉色 `name=xxx`）；**点击条目滚动定位到对应高亮并橙色闪烁 900ms**（`rxLocate`）
- **替换预览**：`text.replace(re, replacement)`，天然支持 `$1` `$&` 等引用；g 标志替换全部
- **健壮性**：正则语法错误即时提示不中断；零宽匹配手动推进 `lastIndex` 防死循环；匹配数上限 10000、详情列表上限 200 条（超出提示）

**核心函数**：
- `rxRun()` — 主流程：构造 RegExp → 收集匹配（g 时 exec 循环）→ 渲染高亮/统计/详情/替换预览
- `rxUseTemplate()` — 应用下拉模板并复位选择框
- `rxGetFlags()` — 收集勾选的 flags 字符串
- `rxLocate(i)` — 匹配详情点击定位（scrollIntoView + 闪烁类）

#### 5.7 内容比对 (`subtab-jsondiff`)
双模式比对工具：**JSON 结构比对**（深度递归对比两份 JSON）+ **文本行比对**（任意文本按行 LCS 对齐，左右双栏原文标注）。位于「正则测试」之后的子 Tab。

**模式切换**：顶部两个按钮（`jdSetMode`），切换时联动更新标签文案、占位符、隐藏「美化格式」（仅 JSON 模式）并清空结果。

**模式一：JSON 结构比对**
- 左右双栏输入 JSON A（原）/ JSON B（新），「开始比对」触发
- 深度递归对比（`jdDiffValues`）：对象按键名（键顺序无关）、数组按索引；类型不同/值不同记为修改；单边独有记为新增（仅 B 有）或删除（仅 A 有）
- 差异报告：顶部汇总徽标（修改/新增/删除计数）+ 每条差异卡片（左色条 + 类型徽标 + `$.path.to[2].field` 路径 + 旧值红底/新值绿底对照）；完全一致显示绿色提示
- 路径格式：`data.list[1].name`（根为 `$（根节点）`）；特殊字符键名 `JSON.stringify` 加引号；值预览截断 120 字符

**模式二：文本行比对（任意文本，无需 JSON）**
- **行级 LCS 对齐**（`jdDiffLines`）：先裁剪公共前后缀（大幅加速），中段 `Uint32Array` DP 求 LCS，回溯产出逐行操作（same/del/add，均带原始行号）；文本过大（n×m > 400 万格）自动降级为中段全删全增并提示
- **双栏原文标注**（`.jd2-grid`，44px 行号 + 1fr 内容 × 两侧）：删除行左侧红底、新增行右侧绿底、相同行两侧正常显示；连续的删/增按顺序配对为「修改」行（左右同行号对照）
- **行内差异高亮**（`jdIntraPair`）：配对的修改行按公共前后缀裁剪，变化中段加亮（左红右绿），一眼看出行内哪个片段变了
- **相同内容折叠**：连续相同行 > 7 时首尾各保留 3 行、中间折叠为「⋯ 已折叠 N 行相同内容 ⋯」蓝条，点击展开（`jdExpandFold`，按组 id 移除隐藏类）
- 顶部汇总徽标（修改 x / 新增 y / 删除 z 行）；表头粘性滚动；结果区独立滚动（max-height 560px）；差异行上限 8000 防卡死
- 辅助按钮：交换 A/B、加载示例（日志文本）、清空

**核心函数**：
- `jdSetMode(mode)` — 模式切换联动（按钮样式/标签/占位符/隐藏美化按钮/清空结果）
- `jdDiffValues(path, a, b, out)` — JSON 递归对比核心，产出 `{type, path, a?, b?}` 列表
- `jdDiff()` — 入口分发：text 模式走 `jdDiffText()`，否则 JSON 比对
- `jdDiffLines(aText, bText)` — 行级 LCS（前后缀裁剪 + DP + 回溯），产出带行号的操作序列
- `jdDiffText()` — 文本模式主流程：操作序列 → 行对配对（删增配对为修改）→ 渲染双栏网格（含折叠）
- `jdIntraPair(s1, s2)` — 行内差异高亮（公共前后缀 + 中段加亮）
- `jdExpandFold(g)` / `jdPreview(v)` / `jdSwap()` / `jdFormat()` / `jdClear()` / `jdExample()` / `jdTextExample()` — 折叠展开 / 值预览 / 交换 / 美化 / 清空 / 两种示例

#### 5.8 在线白板 (`subtab-whiteboard`)
原生 Canvas 实现，零依赖、纯前端。位于「内容比对」之后的子 Tab。**矢量笔画存储**：每页保存操作序列而非位图快照，任意窗口尺寸 / DPR / 浏览器缩放下重放绘制，永不模糊、无代际损耗。

**笔画数据格式**（坐标为 0~1 归一化值，线宽相对画布宽度归一化）：
```json
[
  {"t":"p","c":"#2563eb","w":0.005,"pts":[[0.1,0.2],[0.15,0.22],...]},  // 画笔路径
  {"t":"e","w":0.03,"pts":[[...],...]},                                // 橡皮路径（重放时 destination-out）
  {"t":"l","c":"#dc2626","w":0.004,"a":[0.1,0.1],"b":[0.8,0.8]},       // 直线
  {"t":"r","c":"#16a34a","w":0.004,"a":[0.1,0.1],"b":[0.8,0.8]},       // 矩形（a/b 为对角）
  {"t":"o","c":"#d97706","w":0.004,"a":[0.1,0.1],"b":[0.8,0.8]},       // 椭圆（a/b 为外接矩形对角）
  {"t":"t","c":"#111827","f":0.015,"a":[0.1,0.1],"str":"标注文字"},     // 文本（f 归一化字号，str ≤500 字，支持 \n 多行）
  {"t":"c"}                                                             // 清空标记（可撤销）
]
```

- **六种工具**：画笔（自由绘制）、直线、矩形、椭圆（拖拽实时预览）、文本（点击画布输入）、橡皮（`destination-out` 真擦除；擦除轨迹也记录为矢量操作，按时间顺序重放即还原擦除效果）
- **文本工具**：选「T 文本」后点击画布弹出浮动输入框（定位到点击处）——Enter 提交、Shift+Enter 换行、Esc 取消、失焦自动提交；再点画布：输入框有内容则提交收起，为空则移动到新位置；字号随粗细滑块联动（size × 5，默认 3 → 15px，归一化存储任意缩放不糊）；颜色实时跟随色板；输入框 maxLength=500 与服务端校验对齐；已提交文本为普通矢量操作（可撤销/擦除，暂不支持二次编辑）
- **颜色**：8 个预设色板 + `input[type=color]` 自定义取色（选色时若在橡皮模式自动切回画笔）
- **线宽**：1-30 滑块，`lineCap/lineJoin: round` 圆润笔触
- **撤销/重做（操作序列模式）**：`strokes` 数组即完整操作历史——undo = pop 末尾操作 + 全量重放，redo = push 回去 + 重放；清空画布记录为 `{t:'c'}` 标记故也可撤销；重做栈 `wbRedoOps` 按页独立，翻页/新绘制时重置；每页上限 `WB_MAX_STROKES=2000` 条（超出裁剪最早操作）
- **多页白板（PPT 式）**：画布下方翻页栏 `◀ 上一页 | 1 / N | 下一页 ▶ | ＋ 新页 | 🗑 删页`；数组顺序即页序，页 id 形如 `wb_p_xxx`；至少保留一页；绘制中禁止翻页/增删（防笔画丢失）；翻页前自动 flush 当前页
- **导出 PNG**：先全量重放确保画布与数据一致，临时画布铺白底后 `toDataURL` 下载，文件名 `whiteboard_YYYYMMDD_HHmm.png`（导出当前页）
- **手动保存模型（不自动上传）**：绘制/翻页/增页只写 localStorage（`jsonTool_whiteboard`，`{pages, activeIndex}` 全量缓存，600ms 防抖），**不再每笔自动 POST 服务器**；服务器同步仅靠工具栏「💾 保存」手动触发；服务端文件 `whiteboard.json` 为 `{"pages":[{id,strokes,updatedAt}...],"updatedAt"}`；**旧位图格式（dataUrl）已废弃**，前后端均直接丢弃旧数据页
- **笔画级合并（多设备同步）**：`wbPullAndMerge()` 拉取服务器全量后按页 id 对齐，同页做**笔画 union**（服务器笔画保序在前、本地新增按 JSON 深比较去重后追加）——多设备并发绘制同一页时双方笔画都保留，取代旧的页级 last-write-wins 整页覆盖（旧策略两设备改同一页会互相丢笔画）；单边独有页互相补齐；正在绘制时跳过本次合并
- **手动保存 / 手动刷新（静默无提示）**：「💾 保存」= 先 `wbPullAndMerge()` 吸收服务器最新笔画 → 全部页推送（`wbPostPage` 队列串行）→ `wbWaitSyncIdle()` 等全部 POST 完成；「🔄 刷新」= 仅 `wbPullAndMerge()` 拉取合并、不上传；启动时也只做拉取合并不上传（未保存的本地内容不会自动出现在其他设备）；删页仍为即时 POST `deletePageId`；绘制中/文本输入中点按钮直接忽略（不弹窗），唯一保留的弹窗是删页时的「至少保留一页」
- **合并已知边界**：笔画去重按内容深比较，故意画两笔完全相同的笔画合并后只剩一笔；A 删页后 B 用旧本地数据点保存可能使该页复活（单用户多设备场景罕见）；保存瞬间的 GET→POST 窗口期内他人新推送的笔画会漏合并（下次保存补齐）
- **高 DPI**：canvas 物理尺寸 = CSS 尺寸 × `devicePixelRatio`，`setTransform(dpr,...)` 缩放绘制，清晰不糊
- **尺寸自适应（矢量重放）**：`ResizeObserver` 监听画布容器（tab 激活 display:none→block 和窗口 resize 均触发），重设尺寸后**全量重放**——坐标/线宽按新画布物理尺寸映射，内容自动铺满且笔触重新光栅化，无缩略、无模糊、无 DPR 错位
- **触屏支持**：Pointer Events 统一处理鼠标/触摸，`setPointerCapture` 拖出画布仍跟踪，`touch-action: none` 防滚动干扰

**核心函数**：
- `wbInit()` — 初始化（构建色板、ResizeObserver、指针事件、恢复保存内容）
- `wbResize()` — 高 DPI 尺寸自适应（设尺寸后矢量重放，无需位图拷贝）
- `wbBindPointer()` — pointerdown/move/up/cancel 绘制流程（画笔逐段绘制并收集归一化点集 / 形状快照预览）
- `wbNormPt(p)` — CSS 坐标 → 归一化坐标 `[x,y]`（0~1，5 位小数精度）
- `wbCommitStroke()` — pointerup 时把刚画的笔画固化为矢量操作 push 到当前页（含归一化线宽、undo 深度裁剪、重做栈清零）
- `wbStrokeReplay(s)` — 重放单条操作（物理像素坐标系，坐标/线宽按当前画布映射；单点画圆点；橡皮 destination-out；文本 fillText 逐行绘制、字号按画布宽映射）
- `wbReplay()` — 清空画布并按时间顺序全量重放当前页操作（同步毫秒级；末尾统一维护提示层显隐）
- `wbOpenTextInput(p)` / `wbCommitTextInput()` / `wbCancelTextInput()` — 文本工具输入框生命周期（打开/提交为矢量操作/取消）；提交时字号归一化 clamp、blur 自动提交、幂等可重入
- `wbDrawShape(a, b)` / `wbApplyStyle()` — 形状绘制 / 画笔样式（橡皮切换 composite）
- `wbUndo()` / `wbRedo()` / `wbClear()` — 操作序列增删 + 重放（清空记录为 `{t:'c'}` 可撤销）
- `wbNewPage()` / `wbNormalizePage(p)` — 新建空白页 / 页对象规范化（无 strokes 的旧位图页返回 null 丢弃）
- `wbReadLocal()` / `wbWriteLocalAll()` — localStorage 全量读写（`{pages, activeIndex}`；旧位图格式忽略）
- `wbScheduleSave()` — 600ms 防抖：更新当前页 updatedAt 仅写本地缓存（不上传）
- `wbPostPage(page)` / `wbProcessSyncQueue()` — 页级 POST 同步（队列去重 + 串行，POST 时读页对象最新 strokes；仅「💾 保存」使用）
- `wbPullAndMerge()` / `wbMergePage(sp, lp)` — GET 服务器全量 + 笔画级合并（不上传）；启动加载与「🔄 刷新」共用
- `wbSaveNow()` / `wbRefreshNow()` / `wbWaitSyncIdle()` — 工具栏手动保存（先拉取合并再全部页推送 + 等待完成，静默）/ 手动刷新（仅拉取合并，静默）/ 等待同步队列排空
- `wbLoadSaved()` — 先渲染本地缓存当前页，再异步拉服务器合并
- `wbUpdatePager()` / `wbFlushActivePage()` / `wbShowActivePage()` — 页码显示 / 当前页标记更新（strokes 已实时在页上）/ 呈现当前页（重放 + 重做栈清零）
- `wbGoToPage(idx)` / `wbPrevPage()` / `wbNextPage()` / `wbAddPage()` / `wbDeletePage()` — 翻页与增删页（删页 POST `deletePageId`）
- `wbExport()` — 导出 PNG（先重放保证一致性）
- `wbPid()` — 生成页 id（`wb_p_` + 时间戳36进制 + 随机）

### 6. 书签管理 (`tab-bookmarks`)

常用网页链接管理工具，数据持久化到服务器端 `bookmarks.json`，局域网共享、清缓存不丢失。位于「开发者工具」之后的主 Tab。

**核心能力**：
- 左侧分类侧边栏 + 右侧书签卡片网格的双栏布局（`.bookmarks-layout`）
- **「全部」视图按分类分组展示**：每个分类一个区块（蓝色竖条标题 + 数量徽标 + 该分类卡片网格），点击分类标题可直接跳转到该分类；搜索或进入单个分类时自动回归扁平网格
- 分类管理：新增、重命名、删除分类（删除时其书签归入「未分类」）；侧边栏显示各分类书签数量，顶部「全部」聚合视图
- 书签卡片：显示图标 + 别名，默认只展示别名；**鼠标悬浮时通过 tooltip 显示完整 URL**，保持卡片整洁
- **拖拽排序**：卡片可拖拽（原生 HTML5 DnD），悬浮目标卡片时显示蓝色左右插入指示线；分类内调整顺序，「全部」分组视图下还支持跨分组拖拽（书签自动归入目标分类）；搜索状态下禁用（过滤列表不适合排序）
- **拖拽自动滚动**：拖到视口上/下边缘 70px 区域时页面持续滚动（rAF 循环实现，鼠标停住不动也滚），越靠近边缘速度越快（最高 12px/帧）
- 点击卡片在新标签页打开网址
- 添加/编辑弹窗：支持手动输入 URL（无协议时自动补全 `https://`）、别名（留空则用域名）、选择/新建分类、自定义图标
- **图标自动获取**：未设置自定义图标时，请求 `https://{host}/favicon.ico`（直连网站自身，国内访问稳定，避免 Google 服务）；favicon 加载失败时回退为根据域名哈希取色的彩色首字母圆形头像
- 自定义图标：支持 emoji/文本，或图片 URL（http/https、`/` 相对路径、`data:` URI；图片加载失败显示 🌐）
- 实时搜索：按别名和 URL 模糊匹配，跨分类过滤
- 数据导入/导出：JSON 格式，方便备份和迁移
- **数据持久化策略**：「本地缓存即时渲染 + 服务器异步同步」

**数据模型 (`bookmarks.json`)**：
```json
{
  "categories": [
    { "id": "default", "name": "未分类" },
    { "id": "bm_xxx", "name": "开发文档" }
  ],
  "bookmarks": [
    {
      "id": "bm_xxx",
      "name": "别名（显示在卡片上）",
      "url": "https://example.com",
      "categoryId": "bm_xxx",
      "icon": "",
      "createdAt": 1700000000000
    }
  ]
}
```
> 图标字段为空时自动获取 favicon；`categoryId` 为 `"default"` 表示未分类。**`bookmarks` 数组顺序即显示顺序**（拖拽排序直接写回数组并持久化，无需额外 order 字段；新添加的书签插入数组头部）。

**持久化机制（前后端协同）**：
1. 页面打开时，先从 localStorage（key: `jsonTool_bookmarks`）读取缓存**立即渲染**，无白屏
2. 随后异步 `GET /api/bookmarks` 拉取服务器最新数据：
   - 服务器有数据 → 以服务器为准，更新本地缓存并重新渲染
   - 服务器为空但本地有旧数据 → 自动迁移上传到服务器
3. 任何增删改操作：先写 localStorage（即时生效），再通过 **400ms 防抖** 批量 `POST /api/bookmarks` 同步服务器
4. 同步使用串行队列（`bmSyncing` 标志 + `bmPendingSync`），防止并发请求乱序
5. 服务器不可用时自动降级为纯 localStorage 模式（`bmServerAvailable` 标志），不影响使用

**核心函数**：
- 数据层：
  - `bmLoadFromServer()` — 启动时从服务器拉取，处理空数据迁移
  - `bmSyncToServer()` — 防抖同步到服务器（串行队列）
  - `bmPersist()` — 写缓存 + 调度同步
  - `bmLoadCache()` / `bmSaveCache()` — localStorage 缓存读写
  - `bmNormalizeData(data)` — 数据规范化与校验
- 渲染与交互：
  - `bmRender()` — 渲染分类侧边栏 + 书签区；「全部」视图且非搜索时按分类分组（`.bm-group`），单分类/搜索时渲染扁平网格；**书签按数组顺序显示**（即拖拽自定义的顺序，新添加的书签由 `bmSave` 插入数组头部）
  - `bmCardHtml(b)` — 生成单张书签卡片 HTML（被分组/扁平两种视图复用；卡片 `draggable="true"` 并绑定拖拽事件）
  - `bmIconHtml(bm)` — 生成图标 HTML（favicon / emoji / 首字母头像；内部 `img` 设 `draggable="false"` 防止图片拖拽干扰）
  - `bmDragStart/End/Over/Leave/Drop` — 拖拽排序五件套：drop 时按鼠标 X 位置决定插到目标前/后（`splice` 移动数组元素），跨分组拖拽时源书签 `categoryId` 跟随目标分类，随后 `bmPersist()` 持久化；`bmDragStart` 检测到搜索词时 `preventDefault` 禁用拖拽
  - `bmAutoScrollTick/Start/Stop` — 拖拽自动滚动（rAF 循环 + `window.scrollBy`，页面无独立滚动容器故滚动 window）；start 启动、dragover 更新 `bmDragLastY`、dragend/drop 停止
  - `bmShowTooltip(e, text)` / `bmHideTooltip()` / `bmEnsureTooltip()` — 悬浮显示完整 URL
  - `bmSelectCategory(id)` — 切换分类筛选
  - `bmOpenUrl(url)` — 在新标签页打开书签（`window.open`，带 `noopener,noreferrer`）
- 分类与书签 CRUD：
  - `bmAddCategory()` / `bmRenameCategory(id)` / `bmDeleteCategory(id)` / `bmQuickAddCategory()` — 分类管理（`bmQuickAddCategory` 供编辑弹窗内快速新建分类）
  - `bmOpenEdit(id?)` — 打开编辑弹窗；无参为「添加」模式，传 id 为「编辑」模式
  - `bmCloseEdit()` / `bmSave()` / `bmDelete()` — 关闭弹窗 / 保存（URL 经 `new URL` 校验）/ 删除（删除按钮仅编辑模式可见）
- 工具与导入导出：
  - `bmUid()` — 生成 `bm_` 前缀的唯一 ID
  - `bmNormalizeUrl(url)`（无协议时补 `https://`）/ `bmHostname(url)` / `bmColorFromString(str)`（域名哈希取色）
  - `bmEscapeHtml(s)` — HTML 转义，防 XSS
  - `bmPopulateCategorySelect(selectedName?)` — 填充弹窗内分类下拉框
  - `bmExportData()` — 导出完整 JSON 文件（`bookmarks_YYYY-MM-DD.json`）
  - `bmImportData(event)` — **合并导入**：合并新分类、追加书签并重新生成 ID，不覆盖现有数据

### 7. 番茄钟 (`tab-pomodoro`)

番茄工作法计时器 + 待办任务清单 + 专注统计，数据持久化到服务器端 `pomodoro.json`（局域网共享）。位于「书签管理」之后的主 Tab「⏱ 番茄钟」，双栏布局：左侧计时面板 + 右侧任务/统计侧栏（`.pomo-layout`）。

**核心能力**：
- **专注/休息双模式**：`🍅 专注` / `☕ 休息` 切换按钮（计时中禁止切换），休息模式整面板变绿色调（`.pomo-break`）
- **SVG 圆环进度计时器**：200×200 viewBox、r=88 圆环（`.pomo-ring-bg` 灰底 + `.pomo-ring-fg` 渐变前景），`strokeDashoffset` 按剩余比例驱动；中心显示 `mm:ss` 倒计时与状态文案（准备专注/专注中…/已暂停等）
- **计时引擎**：基于**结束时间戳**（`pomoEndTs`）而非累加计数——250ms `setInterval` 轮询 `pomoTick()` 用 `Date.now()` 重算剩余，切后台再回来时间依然精确；**时长双变量**：`pomoTotalSec` 恒为本阶段计划时长（圆环分母 + 统计分钟数），`pomoRemainSec` 存暂停瞬间的剩余秒数——续跑（`pomoStart` 检查 `pomoPaused` 标志）以剩余秒数重建 `pomoEndTs`，**不重置满时长、圆环连续递减不回满、统计仍记满计划分钟**（暂停不消耗计时，自然走完 = 完整计划时长）；重置/跳过/改设置/切模式均清暂停态恢复满时长；`pomoRenderTime` 的圆环比例做了 0~1 钳制（防 NaN）
- **阶段流转**：自然走完（`pomoFinish(true)`）→ 记入统计 + 当前任务 🍅+1 + 提示音 + 标题栏通知 + 自动切到下一阶段（专注和休息自然结束**都**响铃通知）；「⏭ 跳过」= `pomoFinish(false)` 不计统计、不响铃，直接换阶段；「↺ 重置」恢复当前阶段满时长
- **完成提示**：`pomoBeep()` 用 Web Audio API 生成三连 880Hz 蜂鸣（无需音频文件）；`pomoNotify()` 把消息写入 `document.title` 闪烁 8 秒（不弹系统通知、不申请权限），连续通知会重置闪烁定时器并保留最初原始标题
- **桌面宠物联动**：`pomoReportState(note)` 在开始/暂停/重置/完成时 POST `/api/pet-state` 上报运行态（详见「桌面宠物」章节）；`pomoInit()` 启动时清一次陈旧状态（仍活跃的会话保留）
- **今日统计卡**：今日番茄数 + 专注分钟数（`history` 中按 `YYYY-MM-DD` 查询）
- **最近 7 天柱状图**：纯 div 柱状图（`.pomo-hbar`，高度按当日番茄数/7 天最大值比例，今天蓝色描边高亮，柱顶显示数字）
- **任务清单**：输入框回车添加（插入头部）；点击整行切换完成（划线置灰）；「▶」设为当前专注任务（再点取消，蓝色高亮 + 计时面板显示 `🎯 任务名`，**已完成任务不可设为当前**——toast 提示）；「🗑」删除；每条显示累计 🍅 数；完成的当前任务自动取消当前标记；任务 id 在 `pomoNormalize` 中剔除引号/反斜杠（id 拼入内联 onclick，防篡改数据注入）
- **时长设置**：专注 1~180 分钟、休息 1~60 分钟（越界自动钳制），未计时时实时重算剩余时间，改动即持久化

**数据模型 (`pomodoro.json`)**：
```json
{
  "tasks": [
    { "id": "pm_xxx", "name": "任务名（≤200字）", "done": false, "pomodoros": 3, "createdAt": 1700000000000 }
  ],
  "history": [
    { "date": "2026-08-31", "count": 5, "minutes": 125 }
  ],
  "settings": { "focus": 25, "break": 5 }
}
```
> `history` 按日期去重、倒序、最多 366 条；服务端 `_clean_pomodoro()` 做同样的白名单清洗。

**持久化机制**（与书签同款的「本地缓存 + 服务器同步」模式）：
1. 启动先读 localStorage（key: `jsonTool_pomodoro`）立即渲染
2. 异步 `GET /api/pomodoro`：服务器有数据 → 以服务器为准重渲染；服务器为空但本地有 → 迁移上传；加载返回时若本地已有新修改（`pomoEditSeq` 版本计数比对）则跳过覆盖，以本地为准
3. 任何变更（任务增删、勾选、设置修改、专注完成统计）先写缓存再 **POST 同步**（无防抖，串行队列 `pomoSyncing`/`pomoPendingSync` 防并发乱序）
4. 服务器不可用时降级为纯 localStorage（`pomoServerOk` 标志）
5. 「当前专注任务」标记（`pomoCurrentTaskId`）与计时运行状态为**内存态不持久化**——刷新后从首个未完成任务恢复当前标记；服务器数据覆盖后仅当当前标记的任务不存在**或已完成**时才重选

**核心函数**：
- 数据层：`pomoLoadCache()` / `pomoSaveCache()` / `pomoNormalize(data)` / `pomoPersist()` / `pomoSyncToServer()` / `pomoLoadFromServer()`
- 计时：`pomoDurationSec(mode)` / `pomoSwitchMode(mode)` / `pomoToggle()` / `pomoStart()` / `pomoPause()` / `pomoReset()` / `pomoSkip()` / `pomoTick()` / `pomoRenderTime(remainSec)` / `pomoFinish(complete)`
- 提示：`pomoBeep()` / `pomoNotify(msg)` / `pomoUpdateModeUI()`
- 任务：`pomoAddTask()` / `pomoToggleTask(id)` / `pomoDeleteTask(ev, id)` / `pomoSetCurrent(id)` / `pomoRenderTasks()`
- 统计与设置：`pomoRenderStats()` / `pomoRenderAll()` / `pomoUpdateSettings()` / `pomoRefreshSettingsInputs()` / `pomoToday()` / `pomoInit()`

---

## 剪贴板历史 (`tab-clipboard`)

系统级剪贴板历史记录（**文本 + 截图图片**），顶部主 Tab「📋 剪贴板」。**双通道采集**：① `server.py` 启动时开后台守护线程（`ctypes` 轮询 Windows 剪贴板序号），记录服务器所在机器上**任意应用**的复制——剪贴板有文本记文本，无文本时读 `CF_DIB` 位图（覆盖 Win+Shift+S 截图、图片复制）；② 前端监听页面内 `copy` 事件上报选中文本（覆盖非 Windows / 手机浏览器的页面内复制，仅文本）。

**数据模型 (`clipboard.json`，新在前)**：
```json
[
  { "id": "clip_xxx", "text": "复制的文本", "time": 1700000000000 },
  { "id": "clipimg_xxx", "type": "image", "file": "clip_img_xxx.png", "w": 1920, "h": 1080, "time": 1700000000000 }
]
```
> 图片条的 PNG 文件存 `clipboard_files/` 目录，与记录一一对应；记录被裁剪/删除/清空时对应文件同步删除。

**UI 结构**：
- 顶部 Tab 按钮 `#clipTabBtn`（📋 剪贴板，默认隐藏，首次探测 `/api/clipboard` 成功后才显示——服务器不可用则整个入口隐藏）
- Tab 内容区 `tab-clipboard` 内为 `.clip-panel` 白色卡片容器（高度 `calc(100vh - 250px)`，min 420px，flex 纵向）：标题栏（🔄 立即刷新 / 🗑 清空全部）+ 搜索框 + 记录列表 + 底部状态栏
- 记录列表 `.clip-list` 为**响应式双列网格**（`grid-template-columns: repeat(auto-fill, minmax(300px, 1fr))`，宽屏自动多列）
- 文本条目 `.clip-item`：点击**复制回本机剪贴板**（`copyText`，全局工具函数——**http 非安全上下文下 `navigator.clipboard` 不存在**，此时走 `execCommand('copy')` + 隐藏 textarea 兜底，兜底期间 `clipSuppressReport` 抑制 copy 事件上报防止历史重复入库）；显示文本内容（转义防 XSS）+ 相对时间（刚刚/N 分钟前/N 小时前/MM-DD HH:mm）+ 字符数；「✕」单条删除
- 图片条目：缩略图 `.clip-img-thumb`（`object-fit: contain`，max-height 130px，`loading="lazy"` 懒加载，`/clipboard_files/<file>` 由服务端路由提供）+ `📷 宽×高` 元信息；点击复制图片回本机剪贴板（**Promise 形式 `ClipboardItem`**：`clipboard.write` 在用户手势内同步发起、blob 异步解析——先 `await fetch` 再 write 会耗尽 transient activation 导致 NotAllowedError；**需安全上下文**：localhost / https 可用；局域网 IP 等 http 非安全上下文降级为新标签页打开图片自行右键复制，均有 toast 提示）
- Tab 激活时每 **2 秒轮询**刷新（`clipRefreshNow`），按「数量 + 最新条 id」签名对比，无变化不重渲染（避免打断滚动/选择）；切走 Tab 停止轮询（`switchTab` 内钩子：进入 `clipTabOn()` / 离开 `clipTabOff()`）
- 搜索为前端内存过滤（大小写不敏感子串匹配，**仅匹配文本条目**，图片条目搜索时隐藏）；清空需 `confirm` 确认

**服务端 (`server.py`)**：
- `clipboard_watcher()` — Windows 守护线程：每 0.5 秒比对 `GetClipboardSequenceNumber()`，变化时 `OpenClipboard` 内先读 `CF_UNICODETEXT` 文本；无文本时按**三级优先级**读图片——① 原生 PNG 注册格式（`RegisterClipboardFormatW('PNG')`，Win+Shift+S / 飞书 / 微信等截图工具普遍提供，无损直存）→ ② `CF_DIB` 位图兜底（**64 位下必须显式声明 `restype/argtypes = c_void_p`，否则 HANDLE 被 int 截断导致 GlobalLock 失败**；`GlobalSize` 需声明 `c_size_t`）；**剪贴板关闭后**才做耗时的解析/转换与写盘，避免长时间占用剪贴板锁；非 Windows 自动跳过
- `_png_trim(png)` / `_png_size(png)` — 原生 PNG 校验（按 chunk 遍历到 IEND）并裁掉尾部多余字节（GlobalSize 是分配大小可能大于实际数据）/ 解析 IHDR 取宽高
- `_dib_to_png(dib)` — 纯标准库位图转 PNG（`struct` 解析 BITMAPINFOHEADER + `zlib` 压缩 IDAT，手写 PNG chunk）：支持 **BI_RGB(0) 与 BI_BITFIELDS(3)**（截图工具的 CF_DIB 普遍是 BITFIELDS：头后跟 3 个 DWORD 颜色掩码，经典头像素偏移 = biSize+12，V4/V5 头掩码在头内偏移 40）、未压缩 24/32bpp、正/负高度（自底向上/自顶向下）、行 4 字节对齐填充裁剪；标准掩码（R=16/G=8/B=0 位）走 BGRA 切片快速路径，非标准掩码逐像素 DWORD 移位提取；返回 `(png_bytes, w, h)`；1920×1080 实测 0.07s
- `_clip_add(text)` — 线程安全写入文本（`_clip_lock`，注意 Lock 不可重入）：与最新一条相同则跳过（双通道去重），插入头部，最多保留 **200 条**（`CLIP_MAX_ITEMS`），单条文本上限 **100000 字符**；原子写盘（临时文件 + `os.replace`）
- `_clip_add_image(png, w, h)` — 线程安全写入图片：PNG 存 `clipboard_files/clip_img_<ts>_<n>.png`（单张上限 10MB），记录 `type/image/file/w/h`；按 PNG 内容 md5 与上一张去重（连续重复截图不重复记录）
- `_clip_remove_files(items)` — 删除记录对应的图片文件（列表裁剪 / 单条删除 / 清空时调用）
- API 路由 `handle_get_clipboard` / `handle_clipboard_action`（add / delete / clear 三种 action，均返回全量列表，delete/clear 联动删文件）/ `handle_clip_file`（提供 PNG 文件：`os.path.basename` 防目录穿越 + 仅允许 `.png` + `Cache-Control: no-store`）

**API 端点**：
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/clipboard` | 读取全部历史，返回 `{"success": true, "data": [{id, text?, type?, file?, w?, h?, time}...]}`（新在前） |
| POST | `/api/clipboard` | body `{"action":"add","text":"..."}` 添加文本 / `{"action":"delete","id":"..."}` 删除单条 / `{"action":"clear"}` 清空 |
| GET | `/clipboard_files/<name>.png` | 图片文件服务（仅 clipboard_files 目录内 .png） |

> `clipboard.json` 与 `clipboard_files/` 含敏感信息（复制的密码、截图等），请谨慎备份；监听优先记录文本（文本与图片同有时——如浏览器复制图片带 URL 文本——只记文本）；图片优先取原生 PNG 格式（无损），无 PNG 格式才由 CF_DIB 转换（BI_RGB / BI_BITFIELDS 均支持）；文件复制（CF_HDROP）不记录。

**核心函数**：
- `clipInit()` — 注册 copy 事件上报 + 首次探测服务器能力（决定顶部 Tab 按钮显隐）
- `clipTabOn()` / `clipTabOff()` — Tab 激活/离开钩子（`switchTab` 调用；激活即刷新 + 启动 2s 轮询，离开停止）
- `clipRefreshNow()` — 拉取列表 + 签名对比按需重渲染
- `clipRender()` — 渲染列表（文本/图片双分支模板，搜索过滤）/ `clipUpdateFoot()` — 底部状态（条数 / 服务器不可用提示）
- `clipCopyItem(id)`（async）— 复制条目：图片走 **Promise 形式 ClipboardItem**（`clipboard.write` 手势内同步发起 + blob 异步解析）写剪贴板（失败/不支持/非安全上下文降级新标签页打开 + toast 提示），文本走 `copyText`
- `copyText(text)` — 全局文本复制（全站共用）：优先 `navigator.clipboard.writeText`（安全上下文），**http 下 navigator.clipboard 为 undefined（同步 TypeError，.catch 接不住）**，需存在性判断后走 `execCommand` + 隐藏 textarea 兜底；兜底期间置 `clipSuppressReport` 抑制 copy 事件上报（防复制的旧条目重复入库）
- `clipDeleteItem(ev, id)` / `clipClearAll()` — 删除 / 清空
- `clipRelTime(ts)` — 相对时间格式化

---

## 滚动提醒 (`tab-danmaku`)

大字滚动提醒牌（LED 字幕效果）：输入一句话 → 大字从右向左**无限循环滚动**，支持全屏展示，适合放在屏幕上做走马灯提醒。顶部主 Tab「📱 滚动提醒」。**纯前端功能，零服务器依赖**（双击 index.html 也能用），仅个人设置存 localStorage。

**UI 结构**：
- 舞台 `.dm-stage`（黑色大屏，高度 `calc(100vh - 300px)`，min 260px，flex 垂直居中）；支持 `:fullscreen` 全屏（去圆角边框、铺满 100vh）
- 滚动文字 `.dm-item`：绝对定位、`white-space: nowrap`、特粗体（800）、`text-shadow: 0 0 24px currentColor` 同色发光（LED 质感）、垂直居中（动画关键帧内带 `translateY(-50%)`）
- 舞台右上角 `.dm-ctrl`：⛶ 全屏按钮（`requestFullscreen` / `exitFullscreen`；全屏切换触发 `fullscreenchange` 重启动画适配新尺寸，Esc 退出）
- 输入栏 `.dm-bar`：输入框（maxlength=100，回车即开始）+「▶ 开始 / ⏹ 停止」切换按钮
- 设置区 `.dm-settings`：**文字色板**（7 色：白/红/黄/绿/蓝/紫/粉）+ **背景色板**（7 色：黑/深灰/深红/深绿/深蓝/棕/白，LED 屏经典配色）+ 速度滑块（20~300 px/s）+ 字号滑块（40~260px）
- 空状态 `.dm-empty`：未开始时居中提示

**行为细节**：
- **无限循环滚动**：Web Animations API `iterations: Infinity`，单轮时长 = `(stageW + textW) / speed`，滚完自动重头再来，直到点「停止」
- **实时改设置**：换文字色直接改 `style.color` 不打断；调速度/字号会重启动画（宽度与时长变了）
- **设置持久化**：localStorage `jsonTool_danmaku_settings`（速度/字号/文字色/背景色），下次打开自动恢复
- 无多设备同步、无历史记录——本功能就是单机展示 / 提醒牌

**核心函数**：
- `dmInit()` — 初始化（双色板构建、设置回显、舞台背景、fullscreenchange 监听）
- `dmBuildPalette(elId, colors, cur, fn)` — 通用色板渲染（文字/背景共用）
- `dmRender()` — 渲染滚动文字 + Web Animations 无限循环动画（cancel 旧动画 → 重建元素 → 按当前设置启动）
- `dmToggle()` — 开始/停止（停止时清理动画与元素、恢复空状态提示、按钮文案切换）
- `dmPickColor(c)` / `dmPickBg(c)` — 文字色 / 背景色选择（持久化 + 实时应用）
- `dmOnSetting()` — 速度/字号滑块变更（持久化 + 运行中重启动画）
- `dmToggleFullscreen()` — 舞台全屏切换

---

## 桌面宠物 (`pet.py`)

独立的 Windows 桌面宠物小程序（与 Web 工具箱并列的独立进程，**纯标准库 tkinter + ctypes，零第三方依赖**）。双击 `启动宠物.bat`（内部 `pythonw pet.py`，无控制台窗口）启动；右键宠物 → 「退出」关闭。崩溃时自动写 `pet_error.log` 便于排查。

**功能（MVP）**：
- **透明置顶窗口**：`overrideredirect` 无边框 + `-transparentcolor` 背景透明 + `-topmost` 置顶（每 ~4s 刷新防止被其他置顶窗口压住）；ctypes 设 `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`——**点击不抢焦点**、不进任务栏/Alt-Tab；启动前 `SetProcessDpiAwareness(1)` 适配高分屏缩放
- **矢量小老鼠（杰瑞鼠风格原创棕色形象）**：Canvas 纯代码绘制（棕色圆身/奶白肚皮与口鼻/**两片大圆耳**带浅棕内耳/大白眼黑瞳/小棕鼻/每侧三根扇形胡须/**细长卷尾**摇摆/两只小手随状态摆动），无任何素材文件；形象为同风格原创绘制，不使用官方美术资源
- **动画状态机**（60fps `after(16)` 循环，每帧全量重绘）：
  - `idle` 待机——呼吸起伏、随机眨眼（2~5s 一次）、卷尾摇摆、25~60s 随机冒话泡（16 条杰瑞风短语池：吱~/奶酪呢？/猫来啦？溜！…）
  - `walk` 溜达——随机方向 42px/s、双脚交替抬、小手前后交替摆、身体颠簸、大圆耳轻晃，屏幕边缘自动折返
  - `drag` 拖拽——跟随指针、四肢下垂乱晃、惊讶表情（圆睁眼 + o 嘴）、轻微纵向拉伸
  - `fall` 抛掷——重力 2400px/s² 下落、**双手向上举挥舞**、落地弹跳衰减（vy×0.42）+ **挤压变形**（`canvas.scale` 以脚底为锚点）、左右墙/顶部反弹、地面摩擦滑行
  - `sleep` 睡觉——**150s 无互动自动入睡**：闭眼下弯眼、放松小嘴、深慢呼吸、头顶 Z/z 浮动字、6~12s 冒一次 Zzz 泡泡；任何交互（点击/拖拽/右键）或联动事件唤醒（「呼哇…醒啦！」）
- **交互**：**单击冒话泡**（随机短语，专注中则显示「🎯 专注中 · 剩 MM:SS」倒计时；延迟 330ms 触发给双击判定留窗口）；**双击弹出工具箱快捷菜单**——`on_press` 双击判定（间隔 <0.32s）置 `_pending_menu`，第二击松手后 `end_drag` 调 `show_quick_menu()` 在宠物头顶附近弹出（按下即弹会被松开误关，故等松手；第二击按住拖走超过 8px 则视为拖拽不弹）；`_build_quick_menu()` 每次弹出前重建——番茄钟运行中顶部灰色不可点条显示倒计时快照，主体为 `TOOL_TABS` 9 个 Tab 直达项（与右键菜单的 Tab 项同源），底部「💬 逗一下」随机冒话泡，按每项 ~26px 粗估菜单高度防出屏；按住拖拽、松手时按出手速度判定——**低于 300px/s 轻放则原地停留**（可放置在屏幕任意高度，不强制落底），甩出则抛物线飞行 + 落地弹跳 + 挤压变形
- **右键菜单**：9 个 Tab 直达项直接平铺（`TOOL_TABS` 表驱动构建，点击 `webbrowser.open` 打开 `http://localhost:6868/#tab-<id>`——前端 `applyTabHash()` 解析 URL hash 调 `switchTab` 直达，页面加载与 `hashchange` 均生效；服务器未启动时 `open_toolbox()` 先用 pythonw 无窗口拉起 `server.py`，`_wait_server_and_open()` 后台轮询就绪（最多 10 秒）后自动开浏览器）/ 重置位置 / **开机自启**（`add_checkbutton` 打勾显示当前状态；写注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `DevToolboxPet` 键，值为 `"<pythonw 绝对路径>" "<pet.py 绝对路径>"`——`autostart_cmd()` 自动解析 pythonw、`autostart_enabled()` 校验值与当前命令一致、`toggle_autostart()` 切换并气泡反馈） / 退出
- **中键（滚轮按下）区域截图**（QQ 截图式框选 + 标注，纯 ctypes GDI + tkinter，零依赖）：`on_mid_click()` → 宠物先溜出屏幕（`_capture_hidden=True`，tick 不更新位置，保证冻结画面不含自身）→ 220ms 后 `snip_region()` 弹出覆盖虚拟屏幕的 `Toplevel` 框选窗：
  - `_grab_virtual_screen()` GDI `BitBlt` 抓虚拟屏幕（`SM_xVIRTUALSCREEN` 覆盖所有显示器），`GetDIBits` 取底-up BGRA 像素；所有句柄函数显式声明 `wintypes.HANDLE` 原型（**64 位 Python 必须，否则 HANDLE 被截断为 32 位导致 GlobalLock 返回 0**）
  - `_encode_ppm()` BGRA→RGB 逐行翻转编码为 P6 PPM，写临时文件（`tempfile`，用完 `_cleanup()` 删除），`tk.PhotoImage(file=...)` 加载为冻结背景——PPM 免压缩，13MB 数据 ~0.1s 编码秒载
  - **框选阶段**：遮罩为选区四周 4 块 `gray50`+`stipple='gray50'` 点阵矩形（`_update_mask` 每帧 coords），选区内天然露出清晰底图；绿色边框 + 实时「宽 × 高」尺寸标签；选区 <4px 视为误触取消
  - **编辑阶段**（松开后 `_enter_edit()` 锁定选区，遮罩不再变化）：选区下方/上方（屏幕边缘自动翻上）深色工具条 `_build_toolbar()`——▭ 矩形 / ◯ 椭圆 / → 箭头 / ✎ 画笔 / T 文字（选中态蓝底），7 色圆点（红/橙/黄/绿/蓝/白/黑，当前色白圈），↩ 撤销 / ✓ 确认 / ✕ 取消；均为画布项带 `tool:/color:/act:` tag，`_tb_hit()` 用 `find_withtag('current')` 命中检测；形状拖拽实时预览（矩形/椭圆/箭头 tk 原生 shape，画笔收集点集 `coords()` 平滑重绘），文字弹 `tk.Entry`（Return 提交 / Esc 取消 / FocusOut 提交）；标注存 `self.annots`（坐标相对选区左上角，带 `annN` tag 便于撤销 `delete`）
  - **确认合成**（`_confirm()`）：`_clip_dib()` 裁剪选区 BGRA → `_compose_with_annotations()` 用 GDI 在裁剪图上重绘全部标注：`CreateDIBSection` 建 top-down（负高）32 位 DIB，逐行翻转拷入像素 → NULL_BRUSH 空心 + TRANSPARENT 背景，`CreatePen`（PS_SOLID/宽 3）按色重绘（Rectangle/Ellipse/MoveToEx+LineTo，箭头头部按 `atan2` 角度补两条 14px 短线，freehand 逐点 LineTo），文字 `CreateFontW`（20px YaHei Bold）+ `TextOutW` → 读回翻转为底-up；实测合成 ~0.004s
  - `_set_clipboard_dib()` 以 **CF_DIB**（BITMAPINFOHEADER + 像素）写剪贴板；Esc 取消（文字框打开时 Esc 只关输入框）/ 右键取消；`on_done` 回调后宠物移回原位并气泡反馈
  - 截图为 CF_DIB 位图，与 Win+Shift+S 同等待遇——服务器剪贴板监听线程自动收录进剪贴板历史（PNG 落盘），可直接粘贴到微信/钉钉

**服务器联动**（后台 daemon 线程每 3s 轮询，主线程消费事件队列 `_ev_lock` 保护；服务器不可用时静默待着）：
- **剪贴板**：`GET /api/clipboard` 最新一条 id 变化 → 醒来 + 蹦一下 + 气泡预览（`📋 文本前 14 字…` / `📋 [截图]`；首次轮询只记基线不反应）
- **番茄钟**：`GET /api/pet-state` 状态转换检测——开始（`🎯 专注开始！N分钟` / `☕ 休息开始~`）、暂停、停止、以及 `noteAt` 一次性通知（`🍅 专注完成！休息一下吧` 等，按 noteAt 去重只触发一次）
- **小跳反应**：`hop()` 原地垂直弹起（初速 -430px/s 的迷你版抛物线，独立于窗口 y），落地轻微挤压；拖拽/下落/睡觉时不跳
- **陈旧状态防御**：`endsAt` 超过当前时间 2 分钟仍 running（页面已关闭未上报停止）视为过期，忽略不显示

**健壮性细节**：
- 拖拽期间每帧读 `winfo_pointerx/y` 跟随 + `GetAsyncKeyState(VK_LBUTTON)` 轮询左键状态——指针移出窗口、窗外松开都不丢
- 出手速度取 ~0.1s 指针轨迹估算，上限 1800px/s；位移 <8px 且时长 <0.35s 判定为单击而非投掷
- `tick()` 回调与 `mainloop()` 双层 try/except 写 `pet_error.log`（pythonw 无控制台，after 回调异常不会传到 mainloop 外）

**核心结构**（单文件单类 `Pet`）：`tick()` 主循环（`update` 状态机 + `draw` 全量重绘）、`on_press/_single_click`（单击延迟冒话泡/双击判定置 `_pending_menu`）、`show_quick_menu/_build_quick_menu`（双击快捷菜单构建与弹出）、`end_drag`（拖拽与单击/双击判定、出手速度估算、双击松手触发菜单）、`_poll_worker/_on_pm_state`（后台轮询线程 + 状态转换检测）、`update()` 内事件消费（clip/pm_start/pm_pause/pm_stop/note → 话泡 + 小跳）、`draw()`（按状态计算姿态参数：bob/抬脚/尾巴摆幅/惊讶眼/睡觉闭眼/Zzz/话泡/挤压缩放）

**配套前端上报**（index.html 番茄钟模块）：
- `pomoReportState(note)` — fire-and-forget POST `/api/pet-state`，body `{running, paused, mode, endsAt, left, note?, noteAt?}`；在 `pomoStart`/`pomoPause`/`pomoReset`/`pomoFinish` 四处调用，完成时（`complete=true`）附带 `note` 通知文本
- `pomoInit()` 启动时 GET 一次 `/api/pet-state`：无活跃会话（endsAt 已过）则上报 stopped 清掉陈旧状态，有活跃会话则保留（防止误清其他页面进行中的计时）

---

## 统一配置保存系统

三个 Tab（异步任务、接口测试、WebSocket）共用同一套 CRUD，配置保存在服务器端 `saved_requests.json`，局域网共享。

### UI 布局（统一风格）

每个需要保存配置的 Tab 顶部有统一的 `.config-bar` 卡片（浅灰背景 + 圆角边框），包含两行：

```
┌──────────────────────────────────────────────────────┐
│ 已保存：[选择配置下拉框 ▼]  [刷新]  [删除]           │
│ [分类输入框]  [保存名称输入框]  [保存当前配置]       │
└──────────────────────────────────────────────────────┘
```

下拉框按分类分组（`<optgroup>`），选中即自动填充所有字段。

### 数据模型 (`saved_requests.json`)

```json
[
  {
    "name": "配置名称",
    "type": "apitest | async | websocket",
    "category": "分类名（默认：默认分类）",
    "method": "GET | POST | WS",
    "url": "http://...",
    "headers": {"Key": "Value"},
    "body": "POST 请求体字符串"
  }
]
```

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/saved-requests?type=<type>` | 获取配置列表（可按类型过滤） |
| POST | `/api/saved-requests` | 保存/更新配置（body 为 JSON 对象） |
| DELETE | `/api/saved-requests/<type>/<name>` | 删除指定类型和名称的配置 |

### 前端架构

- `SAVED_CONFIG` 对象 — 三个 Tab 的配置映射表（DOM ID、getPayload、apply 回调）
- `saveConfig(type)` — 通用保存（收集表单 → POST → 刷新下拉列表）
- `loadSavedConfig(type)` — 通用加载（选中项 → 填充表单）
- `deleteSavedConfig(type)` — 通用删除
- `refreshSavedList(type)` — 按分类分组渲染 `<optgroup>`

**唯一键**: `type + name`（不同类型允许同名）
**数据迁移**: `_migrate_items()` 自动为旧数据补全 `type` 和 `category` 字段

---

## 代理服务器详解 (`server.py`)

### 类结构

```
ProxyHandler(SimpleHTTPRequestHandler)
├── do_GET()          # 静态文件 / 代理 / 配置列表 / 书签 / 白板 / 番茄钟 / 剪贴板读取
├── do_POST()         # 代理 POST / 保存配置 / 保存书签 / 保存白板 / 保存番茄钟 / 剪贴板操作
├── do_DELETE()       # 代理 DELETE / 删除配置
├── do_OPTIONS()      # CORS 预检
├── handle_proxy()    # 核心代理转发逻辑
├── handle_list_saved()    # GET 配置列表
├── handle_save_request()  # POST 保存配置
├── handle_delete_saved()  # DELETE 删除配置
├── handle_get_bookmarks()   # GET 读取书签
├── handle_save_bookmarks()  # POST 保存书签（含字段校验）
├── handle_get_whiteboard()  # GET 读取白板全部页
├── handle_save_whiteboard() # POST 页级保存/删除（按 id 替换或追加，矢量 strokes 结构化校验与 2MB 上限）
├── handle_get_pomodoro()    # GET 读取番茄钟数据
├── handle_save_pomodoro()   # POST 保存番茄钟（全量覆盖，_clean_pomodoro 白名单清洗）
├── handle_get_pet_state()   # GET 读取宠物联动状态（宠物轮询）
├── handle_save_pet_state()  # POST 保存宠物联动状态（前端番茄钟上报）
├── handle_get_clipboard()   # GET 读取剪贴板历史
├── handle_clipboard_action() # POST 剪贴板操作（add / delete / clear）
└── handle_clip_file()       # GET /clipboard_files/<name>.png 图片文件服务（防目录穿越）
```

**模块级文件操作函数**：
- `load_saved_requests()` / `save_saved_requests(items)` — 接口配置读写
- `load_bookmarks()` / `save_bookmarks(data)` — 书签数据读写
- `load_whiteboard()` / `save_whiteboard(data)` — 白板数据读写
- `load_pomodoro()` / `save_pomodoro(data)` — 番茄钟数据读写（`_clean_pomodoro()` 清洗）
- `load_pet_state()` / `save_pet_state(data)` — 宠物联动状态读写（`_clean_pet_state()` 清洗，临时文件 + `os.replace` 原子写盘）
- `_clip_load()` / `_clip_save(items)` / `_clip_add(text)` / `clipboard_watcher()` — 剪贴板历史（原子写盘 + ctypes 监听线程）

### API 代理 (`/proxy?url=<target>`)

- 支持 GET / POST / DELETE / OPTIONS
- 自定义请求头通过 `X-Proxy-Headers` 请求头传递（JSON 编码 + URL encode）
- 自动过滤 `host`、`content-length`、`connection`、`x-proxy-headers` 等跳过头
- 透传目标响应状态码、Content-Type、Body
- 自动补全缺失的 `http://` 协议前缀
- 请求超时 60 秒
- 异常时返回 502 + 错误信息 JSON

### 配置文件操作

- `load_saved_requests()` — 读取 `saved_requests.json`，不存在则返回空列表
- `save_saved_requests(items)` — 写入 `saved_requests.json`
- `_migrate_items(items)` — 数据迁移（补全 type/category 字段）
- `load_bookmarks()` — 读取 `bookmarks.json`，不存在或解析失败时返回默认结构（含「未分类」）
- `save_bookmarks(data)` — 写入 `bookmarks.json`（`ensure_ascii=False` 保留中文，`indent=2` 格式化）
- `load_whiteboard()` — 读取 `whiteboard.json`（含旧单页格式迁移），不存在或解析失败时返回 `{"pages": [], "updatedAt": 0}`；每页经 `_clean_whiteboard_page()` 校验清洗
- `save_whiteboard(data)` — 写入 `whiteboard.json`
- `load_pomodoro()` / `save_pomodoro(data)` — 番茄钟数据读写（`_clean_pomodoro()` 清洗）
- `_clip_load()` / `_clip_save(items)` — 剪贴板历史读写（原子写盘）；`_clip_add(text)` 文本追加 / `_clip_add_image(png, w, h)` 图片追加（PNG 存 `clipboard_files/`）/ `_png_trim()` `_png_size()` PNG 校验裁剪与尺寸解析 / `_dib_to_png(dib)` 位图转 PNG（含 BI_BITFIELDS）/ `_clip_remove_files(items)` 文件清理 / `clipboard_watcher()` 监听线程

### 书签 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/bookmarks` | 读取书签数据，返回 `{"success": true, "data": {...}}` |
| POST | `/api/bookmarks` | 全量保存书签数据（body 为完整书签 JSON），服务端会校验并清洗字段 |

> 书签采用「整文档覆盖」的保存方式（而非单条增删），前端在内存中维护完整状态后一次性 POST。服务端对 `categories`/`bookmarks` 字段做白名单清洗，丢弃非法字段，保证文件结构稳定。

### 白板 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/whiteboard` | 读取全部页，返回 `{"success": true, "data": {"pages": [{id, strokes, updatedAt}...], "updatedAt"}}` |
| POST | `/api/whiteboard` | **页级保存**：body `{"page": {id, strokes, updatedAt}}` 按 id 替换或追加单页；body `{"deletePageId": "xxx"}` 删除指定页 |

> 白板为**页级读写**协议（避免整文档传输），存储**矢量笔画**（归一化坐标的操作序列，见 5.8 数据格式）。服务端按 id 定位替换（不存在则追加），`_clean_whiteboard_page()` 对 strokes 做结构化校验（操作类型白名单 `p/e/l/r/o/t/c`、坐标 0~1±0.1 容差、线宽/字号 0~0.5、每页 ≤5000 操作、单笔 ≤20000 点、文本 ≤500 字且仅允许 `\n` 控制字符、颜色 `#hex`），单页 JSON 序列化上限 2MB（`WHITEBOARD_MAX_BYTES`）；无 `strokes` 键的旧位图格式页直接丢弃；每次写盘更新文档级 `updatedAt`（服务器当前时间）。多设备同步由前端手动触发（💾 保存/🔄 刷新），同页冲突做**笔画级 union 合并**（见 5.8），不按时间戳整页覆盖。

### 番茄钟 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/pomodoro` | 读取番茄钟数据，返回 `{"success": true, "data": {tasks, history, settings}}` |
| POST | `/api/pomodoro` | 全量保存（body 为完整番茄钟 JSON），`_clean_pomodoro()` 白名单清洗（任务名 ≤200 字、history 按日期去重 ≤366 条、focus 1~180 / break 1~60 钳制） |

### 剪贴板 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/clipboard` | 读取全部历史（新在前），返回 `{"success": true, "data": [{id, text?, type?, file?, w?, h?, time}...]}` |
| POST | `/api/clipboard` | `{"action":"add","text":"..."}` 添加文本 / `{"action":"delete","id":"..."}` 删除单条 / `{"action":"clear"}` 清空；均返回全量列表 |
| GET | `/clipboard_files/<name>.png` | 图片文件服务（`basename` 防目录穿越 + 仅 `.png` + `no-store`） |

> 剪贴板写入线程安全（`_clip_lock`）；文本上限 200 条、单条 ≤100000 字符，与最新一条相同则跳过（双通道去重）；图片单张 PNG ≤10MB、按 md5 与上一张去重，存 `clipboard_files/`，记录删除/裁剪/清空时联动删文件；`clipboard.json` 采用临时文件 + `os.replace` 原子写盘。`clipboard_watcher()` 守护线程在 `__main__` 启动（仅 Windows 生效）。

### 宠物联动状态 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/pet-state` | 读取宠物联动状态，返回 `{"success": true, "data": {running, paused, mode, endsAt, left, note, noteAt, updatedAt}}` |
| POST | `/api/pet-state` | 保存运行态（前端番茄钟开始/暂停/停止/完成时上报）；`_clean_pet_state()` 清洗（mode 只允许 focus/break、left 钳制 ≤24h、note ≤60 字） |

> 数据流：浏览器番茄钟 → POST `/api/pet-state` → `pet_state.json` → 桌面宠物每 3s GET 轮询。`endsAt` 为运行中结束时间戳（ms），`left` 为暂停时剩余秒数；`note`/`noteAt` 为一次性通知（宠物按 `noteAt` 去重消费）。写盘采用临时文件 + `os.replace` 原子操作。

### CORS 处理

所有响应添加 `Access-Control-Allow-Origin: *`，OPTIONS 请求返回 204。

---

## 前端 UI 设计规范

### 布局
- 最大宽度 1200px 居中，顶部 Tab 导航栏，每 Tab 包含输入面板 + 结果面板
- 开发者工具 Tab 内部使用子 Tab（`.subtabs` / `.subtab-btn` / `.subtab-content`）
- Flex 布局，`flex-1` 自动填充，`flex-wrap` 响应式换行

### 配色
| 用途 | 色值 |
|------|------|
| 主色/链接 | `#409eff` |
| 成功/GET | `#10b981` |
| 警告/POST | `#f59e0b` |
| 错误/DELETE | `#ef4444` |
| 面板背景 | `#ffffff` |
| 页面背景 | `#f0f2f5` |
| 配置区背景 | `#f8fafc` |

### JSON 树形视图
| 元素 | 颜色 |
|------|------|
| 键名 | `#881391`（紫） |
| 字符串 | `#c41a16`（红） |
| 数字 | `#1c00cf`（蓝） |
| 布尔值 | `#0c7ff2`（浅蓝） |
| null | `#6b7280`（灰） |
| 括号/冒号 | `#1f2937` / `#374151` |

### 搜索高亮
- `.hl-match` — 黄色背景 `#fef08a`
- `.hl-current` — 橙色背景 `#fb923c`（当前选中项）

### 按钮样式
- `.btn-primary` 蓝、`.btn-success` 绿、`.btn-danger` 红、`.btn-secondary` 灰
- `.btn-sm` 小尺寸版本（用于 config-bar 和工具栏）

### 全局 Toast 通知
- `showToast(msg, type)` — 全局顶部中央通知（`#copySuccess` 元素，全站共用）
- **三种类型**：`success`（默认，绿渐变 ✓）/ `error`（红渐变 ✕，显示 3s）/ `info`（蓝渐变 ℹ，显示 2.6s）；成功 1.8s
- **动画**：弹性入场（`cubic-bezier(.34,1.56,.64,1)` 回弹缩放 + 上滑入场）、图标圆形徽标 `toastIconPop` 弹出动画（缩放 + 轻微旋转）、底部 `.toast-bar` 倒计时进度条（`scaleX` 收缩，时长经 CSS 变量 `--toast-dur` 注入）
- **连续调用防抖**：`clearTimeout` 重置定时器 + `void offsetWidth` 强制重排重启全部动画（避免连点闪烁/提前消失）
- 结构：`<span class="toast-icon">✓</span><span id="toastText">…</span><i class="toast-bar">`；错误提示统一传 `'error'`（无效输入/格式错误/复制失败/操作被阻止等），降级提示传 `'info'`

### 计算器
- `.calc-panel` — 计算器面板（260px 宽，浅灰背景圆角）
- `.calc-display-wrap` — 显示屏外层容器（含过程行 + 主显示屏）
- `.calc-expr` — 表达式过程行（小号灰色字，记录上一步算式）
- `.calc-display` — 显示屏（Consolas 字体，右对齐，`caret-color: #2563eb` 蓝色闪烁光标）
- `.calc-btn` — 数字按钮；`.calc-op` 运算符（橙色）；`.calc-fn` 功能键（灰色）；`.calc-eq` 等号（蓝色）
- `.base-box` — 进制结果卡片（点击复制）
- `.ts-now-box` — 时间戳实时显示（蓝色渐变背景）

### 书签管理
- `.bookmarks-layout` — 双栏布局（左侧固定宽度侧边栏 + 右侧自适应主区）
- `.bookmarks-sidebar` / `.bookmarks-sidebar-head` — 分类侧边栏及其头部（含新增分类按钮 `.bm-cat-add`）
- `.bookmarks-cat-list` / `.bm-cat-item` — 分类列表与分类项（`.active` 高亮，`.bm-cat-count` 数量徽标，悬浮显示「✎重命名」「×删除」两个 `.bm-cat-del` 按钮；重命名/删除均通过 `prompt()`/`confirm()` 弹窗完成，非内联输入框）
- `.bookmarks-main` / `.bookmarks-toolbar` — 主区域及顶部工具栏（搜索框 + 添加/导入/导出按钮）
- `.bookmarks-grid` — 书签网格（`repeat(auto-fill, minmax(160px, 1fr))` 自适应列数）
- `.bookmarks-grid.grouped` — 「全部」分组视图（改为纵向 flex 堆叠）；子元素 `.bm-group` 为单个分类区块
- `.bm-group-head` — 分组标题（蓝色竖条 + 分类名 + `.bm-group-count` 数量徽标，点击跳转该分类）
- `.bm-group-grid` — 分组内的卡片网格（与扁平网格同列宽）
- `.bm-card` — 书签卡片（白色圆角、悬浮上浮阴影；右上角悬浮显示单个 `.bm-card-edit`「✎」按钮打开编辑弹窗，删除操作在弹窗内）
- `.bm-card.dragging` — 拖拽中的源卡片（半透明）；`.bm-card.drop-before` / `.drop-after` — 拖拽悬浮时目标卡片左/右侧的蓝色插入指示线（`box-shadow` 实现）
- `.bm-card-icon` — 图标容器（favicon/emoji/首字母头像）
- `.bm-card-name` — 卡片别名（单行省略号）
- `.bm-tooltip` — 全局浮动提示框（卡片 `onmouseenter`/`onmousemove` 时跟随鼠标显示完整 URL，深色背景白字，带小三角箭头）
- `.bm-modal-overlay` / `.bm-modal` — 添加/编辑弹窗遮罩与容器（`.show` 控制显示，含 `.bm-modal-head` / `.bm-modal-body` / `.bm-modal-foot`，底部含删除按钮）
- `.bookmarks-empty` — 空状态提示（根据搜索/分类场景显示不同文案）

> 注：CSS 中存在 `.bm-cat-rename`、`.bm-card-url` 两个类的样式定义，但当前渲染逻辑未实际使用（属于预留/历史样式）。

### 在线白板
- `.wb-toolbar` — 顶部工具栏（flex wrap：工具组 + 色板 + 线宽滑块 + 操作按钮，`.wb-sep` 竖分隔线）
- `.wb-tools` / `.wb-tool` — 工具按钮组（`.active` 蓝色选中态，`data-tool` 属性标识工具类型）
- `.wb-colors` / `.wb-color` — 色板容器与色块（圆形，`.active` 蓝色描边；自定义取色为 `input[type=color]`）
- `.wb-size-wrap` — 线宽滑块区（range 1-30 + 数值显示 `#wbSizeVal`）
- `.wb-wrap` — 画布容器（白底圆角卡片，高度 `calc(100vh - 320px)` 最小 420px）
- `#wbCanvas` — 画布（`touch-action: none`，橡皮时光标 `cell`、其余 `crosshair`）
- `.wb-hint` — 空状态提示（当前页无内容时显示）
- `.wb-pager` / `.wb-page-indicator` — 画布下方翻页栏（上一页/页码/下一页/新页/删页）

### 正则测试 / 内容比对
- `.rx-flag` — flags 勾选标签（g/i/m/s，勾选即重跑）
- `.rx-highlight-box` — 匹配高亮盒（等宽字体、`pre-wrap`+`break-all`、独立滚动）；`.rx-mark` 黄色高亮、`.rx-flash` 橙色闪烁（定位反馈）
- `.rx-match-list` / `.rx-match-item` — 匹配详情列表（可点击定位，hover 蓝边）；`.rx-group` 捕获组徽标（紫底），`.rx-group-named` 命名组（粉底）
- `.jd-summary` / `.jd-badge-*` — 差异汇总与三色徽标（修改橙 / 新增绿 / 删除红）
- `.jd-item-*` — JSON 模式差异卡片（左色条区分类型）；`.jd-path` 等宽路径；`.jd-val-old` 红底旧值 / `.jd-val-new` 绿底新值
- `.jd2-grid` — 文本模式双栏网格（44px 行号 + 1fr 内容 × 两侧，表头 sticky）；`.jd2-del` 左侧红 / `.jd2-add` 右侧绿 / `.jd2-blank` 空位灰；`.jd2-chg` 行内变化加亮（左红右绿）；`.jd2-foldbar` 折叠蓝条（点击展开）

### 番茄钟
- `.pomo-layout` — 双栏布局（左侧计时面板 + 右侧任务/统计侧栏）
- `.pomo-timer-panel` — 计时面板（`.pomo-break` 休息模式整体绿色调）
- `.pomo-mode-tabs` / `.pomo-mode-btn` — 专注/休息模式切换（`.active` 选中态，`.pomo-mode-break` 休息绿色）
- `.pomo-ring-wrap` / `.pomo-ring` — SVG 圆环容器（220×220）；`.pomo-ring-bg` 灰底圆 + `.pomo-ring-fg` 渐变前景圆（`strokeDashoffset` 驱动进度，r=88）
- `.pomo-ring-center` / `.pomo-time` / `.pomo-state` — 圆环中心的倒计时（大号等宽感数字）与状态文案
- `.pomo-current-task` — 当前专注任务展示（`🎯 任务名`）
- `.pomo-controls` / `.pomo-settings` — 开始/重置/跳过按钮组 + 专注/休息分钟设置
- `.pomo-stats-card` / `.pomo-stat-num` — 今日统计卡（番茄数 + 专注分钟数）
- `.pomo-tasks-card` / `.pomo-task-input` / `.pomo-task-list` — 任务清单卡（输入框 + 列表）
- `.pomo-task-item` — 任务行（`.pomo-task-current` 蓝色高亮当前任务、`.pomo-task-done` 划线置灰）；`.pomo-task-pomo` 累计番茄徽标；`.pomo-task-btn` 行内小按钮（设当前/删除）
- `.pomo-history-card` / `.pomo-hbar-wrap` / `.pomo-hbar` / `.pomo-hbar-label` / `.pomo-hbar-num` — 最近 7 天纯 div 柱状图

### 剪贴板历史
- `.clip-panel` — 剪贴板 Tab 内白色卡片容器（flex 纵向，高度 `calc(100vh - 250px)`）
- `.clip-list` — 记录列表（响应式网格 `repeat(auto-fill, minmax(300px, 1fr))`，宽屏自动多列）
- `.clip-panel-head` / `.clip-panel-title` / `.clip-head-btn` — 标题栏与操作按钮（刷新/清空）
- `.clip-search` — 搜索框（前端内存过滤）
- `.clip-item` — 记录条目（点击整条复制回本机）；`.clip-item-text` 内容（转义）、`.clip-item-meta` 元信息行、`.clip-item-time` 相对时间、`.clip-item-del` 单条删除
- `.clip-img-thumb` — 图片条目缩略图（`object-fit: contain`、max-height 130px、懒加载、`pointer-events: none` 防点击冲突）
- `.clip-empty` — 空状态提示；`.clip-foot` — 底部状态栏（`.clip-off` 服务器不可用警告态）

### WebSocket 消息区
- 深色背景 `#1e1e1e`，终端风格
- 发送消息左边框蓝色，接收消息左边框绿色
- 时间戳灰色小字，等宽字体

### 滚动提醒
- `.dm-stage` — 黑色大屏舞台（圆角 12px + `overflow: hidden`；`:fullscreen` 时去圆角铺满全屏）
- `.dm-item` — 滚动文字（绝对定位、nowrap、特粗体、`text-shadow: 0 0 24px currentColor` 同色 LED 发光）
- `.dm-ctrl-btn` — 舞台右上角全屏按钮（半透明深底 + `backdrop-filter: blur(4px)` 毛玻璃）
- `.dm-color` — 色板圆点（22px 圆形，hover/active 放大 1.15 倍，active 蓝色双环描边；文字色与背景色两排）

---

## 数据持久化

### 服务器端（共享，局域网内所有人可见）
- `saved_requests.json` — 异步任务、接口测试、WebSocket 三个 Tab 保存的配置（数组）
- `bookmarks.json` — 书签管理的分类与书签数据（对象：`{categories, bookmarks}`）
- `whiteboard.json` — 白板画布内容（对象：`{pages: [{id, strokes, updatedAt}...], updatedAt}`，多页矢量笔画结构）
- `pomodoro.json` — 番茄钟任务、历史统计与设置（对象：`{tasks, history, settings}`）
- `clipboard.json` — 剪贴板历史（数组：`[{id, text?, type?, file?, w?, h?, time}...]`，新在前，上限 200 条，含敏感信息谨慎备份）
- `clipboard_files/` — 剪贴板图片 PNG 文件（`clip_img_<ts>_<n>.png`，与 clipboard.json 记录一一对应，记录删除时联动删除）

### 浏览器 localStorage（个人 / 缓存）
| Key | 用途 |
|-----|------|
| `jsonTool_bookmarks` | 书签数据本地缓存（即时渲染 + 服务器异步同步） |
| `jsonTool_whiteboard` | 白板多页本地缓存（`{pages, activeIndex}` 全量，即时渲染；服务器同步由「💾 保存」手动触发；旧位图格式缓存自动忽略覆盖） |
| `jsonTool_pomodoro` | 番茄钟数据本地缓存（即时渲染 + 服务器同步；计时运行态与当前任务标记不持久化） |
| `jsonTool_danmaku_settings` | 滚动提醒个人设置（速度/字号/文字色/背景色，纯本地功能） |
| `jsonTool_wsUrl` | WebSocket 地址记忆 |
| `jsonTool_apiUrl` | 异步任务 URL 自动保存 |
| `jsonTool_pollInterval` | 轮询间隔秒数 |
| `jsonTool_useProxy` | 是否使用代理 |
| `jsonTool_taskHeaders` | 异步任务自定义请求头 |
| `jsonTool_calcHistory` | 标准计算器历史记录（最多50条） |

> **持久化模式对比**：接口配置（`saved_requests.json`）采用「操作即同步」的即时写盘；书签（`bookmarks.json`）采用「本地缓存即时渲染 + 400ms 防抖批量同步」（整文档覆盖）；白板（`whiteboard.json`）采用「本地缓存即时渲染（600ms 防抖）+ **手动保存触发同步**」（💾 保存 = 拉取合并 + 全部页推送，🔄 刷新 = 仅拉取；同页冲突做笔画级 union 合并而非时间戳覆盖）；番茄钟（`pomodoro.json`）采用「本地缓存即时渲染 + 变更即同步」（无防抖，串行队列防并发）；剪贴板（`clipboard.json`）**无本地缓存**，纯服务器读写（面板打开时 2 秒轮询）；宠物联动状态（`pet_state.json`）**无本地缓存**，前端事件驱动上报 + 宠物 3 秒轮询消费。五者都以服务器文件为最终权威数据源，localStorage 仅作缓存/降级（剪贴板、宠物状态例外——仅设置存本地）。滚动提醒无任何数据持久化需求，仅设置存 localStorage。

---

## 启动方式

### Windows 双击（推荐）
双击 `启动服务器.bat`，自动执行：
1. 查找并杀掉占用 6868 端口的旧进程
2. 启动 `python server.py`
3. 自动打开浏览器访问 http://localhost:6868

### 命令行
```bash
python server.py
```
默认监听 `0.0.0.0:6868`。

---

## Nginx 部署参考

如果要替换 Python 服务用 Nginx 部署：
- **静态文件 + API 代理**：Nginx 可完全替代（`root` + `proxy_pass`）
- **配置/书签/白板/番茄钟/剪贴板/宠物状态保存 API**：Nginx 无法直接处理动态文件读写，需改用 localStorage（不共享）或 OpenResty（Lua 脚本）或独立后端（`saved_requests.json`、`bookmarks.json`、`whiteboard.json`、`pomodoro.json`、`clipboard.json`、`pet_state.json` 均依赖此能力；剪贴板的系统级监听还依赖 Python `ctypes`，Nginx 方案下该功能不可用；桌面宠物 pet.py 为独立进程，与 Nginx 方案互不影响，但失去番茄钟联动）
- **开发者工具 Tab、JSON 解析与滚动提醒**：纯前端，无需后端支持（双击 `index.html` 即可用）

---

## 扩展指引

### 新增主 Tab
1. 在 `.tabs` 中按顺序添加 `<button class="tab-btn" onclick="switchTab('xxx')">名称</button>`
2. 添加 `<div class="tab-content" id="tab-xxx">` 面板（内含 `.panel` 输入区和结果区，或自定义布局如书签的双栏）
3. 在 [switchTab()](file:///e:/project/jsonParesTools/index.html#L3006-L3019) 的 `tabs` 数组中**按按钮顺序**加入 `'xxx'`（数组索引必须与 `.tab-btn` 顺序一致）
4. 如需保存接口类配置，在 `SAVED_CONFIG` 中添加映射（指定 DOM ID、getPayload、apply 回调），页面加载时会自动调用 `refreshSavedList('xxx')`
5. 如需独立的服务器端持久化（类书签），参见下方「新增持久化数据模块」

### 新增持久化数据模块（类书签管理）
书签提供了一套「localStorage 缓存 + 服务器 JSON 文件」的可复用模式，新增类似模块时：

**后端 (`server.py`)**：
1. 定义文件路径常量，如 `XXX_FILE = os.path.join(..., 'xxx.json')`
2. 实现 `load_xxx()`（文件不存在/损坏时返回默认结构）和 `save_xxx(data)`（`ensure_ascii=False, indent=2`）
3. 在 `do_GET` / `do_POST` 中新增路由分支（如 `/api/xxx`），调用对应的 `handle_*` 方法；POST 时做字段白名单清洗

**前端 (`index.html`)**：
1. 定义内存状态对象和 localStorage key（如 `jsonTool_xxx`）
2. 实现 `xxxLoadCache()` / `xxxSaveCache()` 读写缓存
3. 实现 `xxxLoadFromServer()`：启动时拉取，处理「服务器空 + 本地有」的迁移
4. 实现 `xxxPersist()`：先写缓存，再用**防抖 + 串行队列**（参考 `bmSyncing` / `bmPendingSync`）同步服务器
5. 服务器不可用时通过标志位降级为纯本地模式

### 新增开发者工具子 Tab
1. 在 `.subtabs` 中添加 `<button class="subtab-btn" onclick="switchSubTab('xxx')">名称</button>`
2. 添加 `<div class="subtab-content" id="subtab-xxx">` 面板
3. 在 `getSubTabLabel()` 映射中加入名称对应

### 新增代理 HTTP 方法
在 `ProxyHandler` 中添加 `do_PUT` / `do_PATCH` 等方法，调用 `self.handle_proxy(parsed, 'PUT', body)`。

### 新增 JSON 树形视图到新区域
调用 `renderValue(data, null, true, 0, true)` 生成 HTML，设置到容器的 `innerHTML`。容器需要 `id` 用于展开收起和搜索。
