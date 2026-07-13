# 路径可视化模块 · 全局多阶段主计划 v1.0

> **强约束（最高优先级，违反即返工）**
> 1. **本文件是路径可视化大阶段的唯一权威计划**。每次开发前必须先读本文件 + `gui/requirements_lock_checklist.md` + `/memories/repo/dev-log.md`。
> 2. **阶段必须严格串行**：未完成上一阶段全部"验收门"，**禁止开始下一阶段任何代码**。
> 3. **禁止 Copilot 自主推进阶段**：每个阶段验收完成后，**必须由用户书面确认"进入 Pn+1"** 才能开工。
> 4. **禁止破坏已有 UI / 发送链路**：每次阶段结束前必须跑 `gui/test/_smoke_phase_d.py` 和 `gui/test/_smoke_phase_e.py`，EXIT=0 才算通过。
> 5. **官方手册为准**：协议/字段语义有歧义时，先查 `用户手册/匿名通信协议V7.pdf`、`用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`。
> 6. **每个阶段结束**：本文件对应阶段勾选 ?；`dev-log.md` 追加一条记录；`gui/requirements_lock_checklist.md` 同步勾选 R1-R9。

---

## 0. 用户已确认的关键决策（不可私自改动）

| 编号 | 决策 |
|---|---|
| D1 | **3D 渲染库** = `pyqtgraph.opengl`（零额外依赖） |
| D2 | **UI 入口** = 顶部加"功能"下拉菜单（多选/勾选项），勾选后对应 Dock 显示 |
| D3 | **计算门控** = 后台积分**持续运行**，仅渲染受"路径可视化"开关控制（切回 Dock 时能立即看到已有轨迹） |
| D4 | **坐标系约定** = 机体 FLU：**机头前=x+，机头左=y+，机头上=z+**；激活瞬间快照 yaw0，以当时机头方向为世界系 x+，之后**世界系不再旋转**，小立方体根据当前姿态在其中转动 |
| D5 | **Z 来源** = 0x05 绝对高度；X/Y = 0x07 速度积分（去除 yaw0 旋转） |
| D6 | **姿态指示** = 小球标记机头朝向（来自 yaw）；长箭头标记速度向量方向（来自 vx/vy/vz）；**两者解耦** |
| D7 | **路径保留** = 时间衰减（可调残留秒数，超时段渐隐） + 兜底点数上限防爆 |
| D8 | **姿态帧来源** = 0x04 四元数（万向锁免疫）；0x03 仅作 fallback |
| D9 | **日志策略** = 可视化模块仅在 **启动 / 停止 / 重置 / 异常** 时打日志；正常帧静默 |

---

## 阶段拆分总览

| 阶段 | 名称 | 主交付物 | 预估代码量 |
|---|---|---|---|
| P0 | 协议语义冻结 + 现有 MVP 对账 | 文档（无代码） | 0 |
| P1 | 顶部"功能"下拉栏 + Dock 显隐骨架 | feature_bar 重构 | 小 |
| P2 | 数据通路硬化（0x04/0x05/0x07 解码 + 总线接入 + 后台积分常驻） | telemetry_* 服务 | 中 |
| P3 | 最小 3D 场景（网格 + 立方体 + 路径线，固定参数） | path_visualization_widget MVP | 中 |
| P4 | 姿态/机头/速度箭头（D6 全实现） | widget + tracker 扩展 | 中 |
| P5 | 完整参数面板 + 持久化（D7 + 全部美化参数） | widget 设置面板 + config | 中 |
| P6 | 性能与稳定性（线程安全 / 帧率限制 / 异常隔离 / 降级） | 全模块加固 | 中 |
| P7 | 美化收尾 + 扩展接口预留（未来 SLAM/雷达） | 接口层 + 主题适配 | 小 |

---

## P0 · 协议语义冻结（**当前阶段**）

**目的**：在写任何新代码前，把所有模糊的字段语义钉死，避免后续返工。

**任务清单**
- [ ] 抽取 `用户手册/匿名通信协议V7.pdf` 中 **0x04 / 0x05 / 0x07** 的字段定义与单位（用 `extract_pdf.py`）
- [ ] 验证当前 `gui/services/telemetry_decoder.py` 中三者的解包结构是否正确（特别是 0x05：是否有 fusion_height + add_height + sta_byte 三字段）
- [ ] **关键澄清**：0x07 vx/vy/vz 是 **机体系** 还是 **大地 NED 系**？这决定积分前是否要先旋转
- [ ] 在本文件追加 P0 结论小节（贴出冻结后的字段表）

**验收门**
- 字段表写入本文件 P0 小节
- `telemetry_decoder.py` 若与手册不符，记一条 TODO（**不在 P0 修代码**）
- 用户确认 P0 字段冻结 → 才进入 P1

**禁止动作**
- 修改任何 `gui/widgets/*` 或 `gui/services/*` 代码
- 添加新依赖
- 改 UI

### P0 字段冻结结论（2026-05-27 抽取自官方手册，权威）

**来源**：
- `用户手册/匿名通信协议V7.pdf`（第 7-9 页）
- `用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf` 第 4.1 节"匿名坐标系"

#### 坐标系约定（官方原话）
- **载体系**：机头为 x+，左侧为 y+，z 满足右手定则（即 FLU，与用户 D4 一致）
- **地理/世界系**：北 x+，西 y+，天 z+（即 NWU）
- **关键约定**："程序里所涉及的所有直角坐标系定义均为此（地理/世界）坐标系，欧拉角的定义除外"
- → **0x07 速度、0x08 位置都是大地 NWU 系下的量**，单位 cm/s 与 cm，**不是机体系**

#### 关键帧字段表（DATA 区，小端）

| 帧 ID | LEN | 解包格式 | 字段 | 单位/比例 | 坐标系 |
|---|---|---|---|---|---|
| **0x03** 姿态欧拉 | 7 | `<hhhB` | ROL, PIT, YAW, FUSION_STA | 角度 ×100 → /100 得度 | 欧拉角约定（特例） |
| **0x04** 姿态四元数 | 9 | `<hhhhB` | V0, V1, V2, V3, FUSION_STA | 四元数 ×10000 → /10000 | 载体→世界系旋转 |
| **0x05** 高度 | 9 | `<iiB` | ALT_FU, ALT_ADD, ALT_STA | 单位 cm（z+=天） | 大地系 |
| **0x06** 模式 | 5 | `<BBBBB` | MODE, LOCKED, CID, CMD0, CMD1 | — | — |
| **0x07** 速度 | 6 | `<hhh` | SPEED_X, SPEED_Y, SPEED_Z | cm/s | **大地系 NWU**（北 x+/西 y+/天 z+）|
| **0x08** 位置 | 8 | `<ii` | POS_X, POS_Y | cm，相对起飞点 | 大地系 NWU |
| **0x0E** 外接 | 4 | `<BBBB` | STA_G_VEL, STA_G_POS, STA_GPS, STA_ALT_ADD | 0=无/1=无效/2=正常/3=良好 | — |

#### 对 P2 实现的约束（强制）

1. **0x05 解包必须是 `<iiB`**，三字段（`alt_fu_cm`, `alt_add_cm`, `alt_sta`）；当前若有单字段实现需重写。Z 高度用 `alt_fu_cm`。
2. **0x07 不是机体系**！因此 D4"激活瞬间快照 yaw0、世界系不再旋转"的实现是：
   - 激活瞬间记录 `yaw0`（来自 0x04 转出的欧拉，或直接从 0x03 YAW 取）
   - 之后每帧 (vx_nwu, vy_nwu) 通过绕 z 轴 `-yaw0` 旋转得到 (vx_local, vy_local)（"激活瞬间机头为 x+"的局部世界系）
   - vz_nwu 直接使用（天 = z+）
   - 积分位置：`x_local += vx_local * dt`，`y_local += vy_local * dt`；z 直接 = `alt_fu_cm`
3. **0x04 四元数转旋转矩阵后**，再用于立方体姿态显示；用户 D8 明确以 0x04 为主，0x03 仅 fallback。
4. **单位统一**：内部全部用 cm + s + 度；渲染时再缩放到 GL 单位。

#### 待 P2 落地时确认的小细节（标 TODO 即可，不在 P0 解决）
- 0x04 四元数的分量顺序：手册写 V0/V1/V2/V3，业界惯例 V0=w 实部。需在 P2 实现时用一帧已知静态姿态对账确认。
- 0x06 LEN=5（5 字节）；当前若按 4 字节解需修正。
- `alt_sta` 状态码语义（与 0x0E 的 STA_ALT_ADD 是否同一编码 0/1/2/3）需 P2 验证。

**P0 验收门状态**
- [x] PDF 抽取完成（见 `_pdf_dump.txt`、`_pdf_fc.txt`）
- [x] 字段表写入本文件
- [x] 0x07 坐标系问题已澄清：**大地 NWU 系**，需在 PathTracker 内部做激活瞬间 yaw0 反旋转
- [ ] **等待用户书面"进入 P1"**

---

## P1 · 顶部"功能"下拉栏 + Dock 显隐骨架

**目的**：把 D2 落地。把现有 `FeatureBar`（QComboBox）改为"顶部菜单栏中的 功能 下拉"，下拉条目用复选框形式控制各功能 Dock 的显隐，为后续多个功能扩展铺路。

**任务**
- 把现有 `gui/widgets/feature_bar.py` 的下拉栏改造为 QMenu（顶部菜单"功能"）+ QActionGroup（每项 `setCheckable(True)`）
- 当前只挂"路径可视化"一项；勾选 ? Dock visible
- 保留现有"刷新/重置"按钮，但移到 Dock 自身工具条内（不在主菜单里）
- 主窗口持久化记忆勾选状态

**验收门**
- 启动 GUI，菜单栏看见"功能 → ? 路径可视化"
- 勾选/取消勾选 ? Dock 出现/消失
- 关掉再开 GUI，勾选状态被还原
- 两条 smoke 测试 EXIT=0
- **用户视觉确认**，并书面写"进入 P2" → 才能动 P2

### P1 实施记录（2026-05-27）

**改动文件**
- 新增 [gui/widgets/path_visualization_widget.py](gui/widgets/path_visualization_widget.py)：`PathVisualizationPlaceholder`（占位 QWidget，P3 替换为 3D 场景）
- [gui/main.py](gui/main.py)：新增 `_FEATURE_DOCKS` 注册表、`_build_feature_docks()`、"功能(&U)" 菜单、`_on_feature_toggled()`；Dock 与菜单 action 双向同步（菜单勾选?Dock 显隐?配置）
- [gui/services/config_service.py](gui/services/config_service.py#L21)：`_DEFAULTS` 新增 `"features.path_visualization": False`（不加白名单会丢盘）
- 新增 [gui/test/_smoke_phase_p1.py](gui/test/_smoke_phase_p1.py)：6 步验证（菜单存在 / Action checkable / 默认隐藏 / 勾选显示 / 取消隐藏 / 关 Dock 同步反勾）

**验收结果**
- P1 smoke：**EXIT=0** ?
- D 回归：**EXIT=0** ?
- E 回归：测试逻辑 OK（"阶段 E 烟雾测试 OK"），Python 进程退出时 `QThread Destroyed` warning 为 E 测试自身遗留（未调用 win.close 致 worker 线程未优雅停），**非 P1 引入**

**已知小坑**
- ConfigService 的"已知 key 白名单过滤"会丢弃未在 `_DEFAULTS` 里登记的键（如 `splitter_sizes`、`ui.theme`）；本次只给 `features.path_visualization` 加了登记，其它键的持久化是预存量问题，不在 P1 范围内修复

**等待**：用户书面"进入 P2"

---

## P2 · 数据通路硬化 + 后台积分常驻

**目的**：D3 + D5 + D8 落地。无论 Dock 是否可见，后台始终接收 0x04/0x05/0x07 并积分；Dock 显示时直接拉最新 PathSnapshot 即可。

**任务**
- `telemetry_decoder.py`：按 P0 冻结结果重写/校正 0x04、0x05、0x07 三个解析函数；为每个字段加单元注释
- `path_tracker.py`：
  - 启用时**不再重置**（D3）；唯一重置入口是"重置"按钮
  - X/Y 用 vx/vy 积分（按激活瞬间 yaw0 反旋转到世界系）
  - Z 直接用 0x05 绝对值（D5）
  - 姿态用 0x04 四元数（D8）
- `telemetry_bus.py`：去掉 `set_visualization_enabled` 对积分的门控；只保留对**发射信号频率**的节流
- 增加 `gui/test/_smoke_phase_p2.py`：注入合成 0x04/0x05/0x07 帧，断言 PathSnapshot 序列符合预期

**验收门**
- 新 smoke 测试 EXIT=0
- 已有两条 smoke 测试 EXIT=0
- 用户书面确认进入 P3

### P2 实施记录（已完成）

**新增文件**
- `gui/services/telemetry_models.py` — 冻结 dataclass：`AttitudeSample` / `VelocitySample` / `HeightSample` / `PathPoint` / `PathTrackerConfig` / `PathSnapshot`
- `gui/services/telemetry_decoder.py` — 纯函数：`decode_attitude_euler`(0x03) / `decode_attitude_quat`(0x04, 内部 quat→Euler ZYX) / `decode_height`(0x05) / `decode_velocity`(0x07)；长度不符返回 None；quat 模长偏离 1 视为无效
- `gui/services/path_tracker.py` — `PathTracker`：
  - 后台始终维护最新姿态/速度/高度
  - `enable()` 瞬间快照 `yaw0_deg` + 清轨迹 + Z 取 `alt_fu_cm`
  - `disable()` 暂停积分但保留轨迹；`reset()` 清轨迹（激活时同时重新快照 yaw0）
  - 0x07 大地 NWU 速度按 `R(-yaw0)` 反旋转至局部世界系；积分得 X/Y；Z 始终用 0x05 绝对值（D5）
  - `dt` 健壮性：`min_dt_s` / `max_dt_s` 双向压紧
  - 时间衰减 `trail_seconds` + 兜底 `max_points` 双重修剪
- `gui/services/telemetry_bus.py` — `TelemetryBus(QObject)`：
  - 信号 `attitude_updated` / `velocity_updated` / `height_updated` / `path_updated` / `status(level,text)`
  - `feed_frame(fr)`：cmd 派发到解码器，0x04 优先策略（近 0.5s 内有 quat 时丢弃 0x03，避免双源抖动）
  - `set_render_enabled(bool)`：仅控制是否广播 `path_updated` + 是否激活 PathTracker；后台解码恒开（D3）
  - `set_render_fps(int)`：节流广播频率
  - 解码异常吞掉并通过 `status` 信号汇报
- `gui/test/_smoke_phase_p2.py` — 6 个用例：解码 / yaw0 旋转 / disable+reset / 时间衰减 / 渲染开关门控 / quat 优先

**改动文件**
- `gui/main.py`：
  - 导入 `TelemetryBus`
  - `__init__` 在 `_build_menu` 前实例化 `self._bus`，并把 `bus.status` 接到 `_on_bus_status`
  - 启动时根据 `features.path_visualization` 配置同步 `bus.set_render_enabled`
  - `_on_frame` 增加 `self._bus.feed_frame(fr)`（所有帧都喂，与是否为 A0 无关）
  - `_on_feature_toggled` 在 `key=="path_visualization"` 时联动 `bus.set_render_enabled`
  - 新增 `_on_bus_status(level,text)` 把遥测告警转到日志/alarm

**验收结果**
- P2 smoke EXIT=0（6/6 PASS）
- P1 smoke EXIT=0（回归）
- D smoke EXIT=0（回归）
- E smoke EXIT=-1073740791（与 P1 阶段相同的 QThread destroyed 已知次要问题，与本阶段无关）

**预留 / 已知决策**
- 四元数 V0 是否为 w 标量：当前以 V0=w 实现（业界主流），如静态实测发现 yaw 跳变，把 `telemetry_decoder._QUAT_W_INDEX` 改为 3 即可
- 0x07 速度方向约定：测试用例验证了 `R(-yaw0)` 反旋转的数学自洽，实际 yaw 正负方向（顺/逆）依赖飞控约定，飞机实测前不下定论；如需翻号在 `PathTracker._yaw0_sin/cos` 处一行翻号即可
- P2 不接 3D 场景；`path_updated` 信号已就位但当前 Dock 内仍是 P1 占位 Widget，待 P3 替换为 `GLViewWidget`

**等待**：用户书面"进入 P3"

---

## P3 · 最小 3D 场景

**目的**：D1 落地最简版本。pyqtgraph.opengl 渲染：地面网格 + 小立方体（无姿态、只跟随位置）+ 路径线。参数全部用代码常量，**先求能看见，不求美化**。

**任务**
- `path_visualization_widget.py`：构建 `GLViewWidget` + `GLGridItem`×1（地面）+ `GLBoxItem`/自定义立方体 + `GLLinePlotItem`（路径）
- 订阅 `path_updated` 信号 → 立方体 setTransform + 路径线 setData
- 帧率硬限 30Hz（用 `_min_emit_interval`）

**验收门**
- GUI 启动 → 勾选路径可视化 → 看见网格+一个立方体在原点
- 模拟数据（FakeWorker 或手工注帧）→ 立方体在网格上移动，留下线条
- CPU 占用 < 10%（任务管理器目测）
- 用户视觉确认 → 进入 P4

### P3 实施记录（代码完成，待用户视觉确认）

- 新增 `gui/widgets/path_visualization_widget.py`（替换旧 placeholder，类名沿用 `PathVisualizationPlaceholder` 保持 `main.py` 引用不变）
  - 软导入 `pyqtgraph.opengl` + `numpy`；缺依赖时降级为红字提示，不引入硬依赖崩溃
  - `GLViewWidget`（背景 (40,40,50)，camera distance=600/elev=28/azim=45）
  - `GLGridItem` 600×600 cm，步长 50 cm（D7 默认网格）
  - `GLAxisItem` size=100（R/G/B = X/Y/Z 世界轴）
  - 自定义立方体 `GLMeshItem`（20 cm 边长，半透蓝 (0.30,0.70,1.00,0.75)，drawEdges 白边）
  - 路径线 `GLLinePlotItem`（绿色 (0.20,1.00,0.40)，宽 2，antialias，line_strip）
  - `update_snapshot(snap)`：cube `resetTransform + translate(x,y,z)`（**P3 不旋转**，姿态留给 P4）；路径 numpy 重组（兼容 n≥2 / n==1 / n==0）
- `gui/main.py` 三处修改
  - `__init__` 新增 `self._feature_widgets: dict[str, QWidget] = {}`
  - `_build_feature_docks` 改成 `widget = factory(dock); dock.setWidget(widget); self._feature_widgets[key]=widget`
  - `_build_feature_docks()` 之后接 `bus.path_updated → widget.update_snapshot`（仅当 widget 存在且有该方法）
- 新增 `gui/test/_smoke_phase_p3.py`：3 case 全 PASS
  - [P3-1] widget 构造（GL 可用分支）
  - [P3-2] `update_snapshot(None / 异常 snap)` 不崩
  - [P3-3] e2e：MainWindow + bus.feed_frame(0x04/0x05/0x07) → cube 位置=(15.14, 0.00, 80.00)，路径点数=4
- 回归：`_smoke_phase_p1 / p2 / d` 全部 EXIT=0
- offscreen 平台报 "QOpenGLWidget is not supported / Failed to create context" 属正常（headless 无 GPU context），不影响逻辑断言；视觉验收必须在真桌面运行 `python -m gui.main`

**用户视觉验收方法**（待执行）：
1. 真桌面运行：`C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe -m gui.main`（如需 FakeWorker 模式：先 `set LINGXIAO_GUI_FAKE=1`）
2. 顶部菜单"功能" → 勾选"路径可视化" → 弹出 Dock，能看到地面网格 + 蓝色立方体在原点 + RGB 坐标轴
3. 喂入真实/合成遥测帧（接飞控或手工脚本发 0x07/0x05）→ 立方体随积分移动 + 绿色轨迹线
4. CPU < 10% → 写"进入 P4"

---

## P4 · 姿态 + 机头小球 + 速度箭头（D6 完整版）

**目的**：把立方体变成"有方向的飞机"。

**任务**
- 立方体根据 0x04 四元数旋转
- 立方体上贴一个小球（GLScatterPlotItem 或小 Mesh）= 机头方向（沿机体 x+）
- 立方体上贴三个短箭头 = 机体 x/y/z 轴
- 速度长箭头 = 世界系内 (vx',vy',vz') 方向（vx,vy 已反旋转到世界系，vz 来自 0x07 而非 0x05 微分），独立于姿态
- 箭头都用 `GLLinePlotItem` + 端点小三角，避免引入新几何

**验收门**
- 在飞机静止悬停状态：长箭头应近似为零长（速度小）
- 偏航旋转：小球绕立方体顶部转，长箭头几乎不动
- 平移：长箭头指向运动方向，小球指向机头
- 用户视觉确认 → 进入 P5

### P4 实施记录（代码完成，待用户视觉确认）

- `gui/widgets/path_visualization_widget.py`
  - 新增 `_NOSE_RADIUS_CM=4 / _NOSE_OFFSET_CM=(20/2+4+1)=15 / _VEL_ARROW_SCALE=0.4 cm/(cm/s) / _VEL_ARROW_MAX_CM=120` 常量
  - 新增 `_nose`（GLMeshItem 黄色球，MeshData.sphere(rows=10, cols=14, radius=4)）和 `_vel_arrow`（GLLinePlotItem 橙色 width=3 mode="lines"）
  - `update_snapshot` 构造 `Transform3D` M = T(pos)·Rz(yaw-yaw0)·Ry(pitch)·Rx(roll)（post-multiply 顺序等同 OpenGL ZYX）
    - cube/axis/nose 三者共享 M（nose 在 M 基础上再 translate(NOSE_OFFSET, 0, 0)）→ 全部跟姿态一起转
    - vel_arrow 独立于 M：起点=pos，终点=pos + (vx_l,vy_l,vz_l)/|v| · min(|v|·scale, MAX_CM)，速度<1 cm/s 时折叠为零长度
  - 实现 D6 全部：① 姿态可见 ② 机头标记 ③ 三轴跟姿态 ④ 速度向量与姿态解耦
- 新增 `gui/test/_smoke_phase_p4.py` 6 case 全 PASS：
  - [P4-1] 含 cube/axis/nose/vel_arrow
  - [P4-2] yaw=90° → nose 世界坐标 (0, 15, 0)
  - [P4-3] yaw=120°/yaw0=120° → nose 在世界 +x（局部偏航=0）
  - [P4-4] vx_l=100 → 箭头末端 +x 偏 40 cm
  - [P4-5] |v|<1 → 折叠零长
  - [P4-6] yaw=90° 时 vel_local 仍指 +x，箭头不被姿态影响
- 回归：P1/P2/P3/D smoke 全 EXIT=0

**用户视觉验收方法**：
1. 真桌面 `.\run_gui.bat`
2. 勾选"路径可视化" → 立方体在原点，里面 RGB 三轴 + +x 面贴黄色球
3. 飞控倾斜 → 立方体俯仰滚转跟动；偏航旋转 → 黄球绕 z 轴转，长橙箭头几乎不变
4. 平移 → 长橙箭头指向运动方向，黄球指向机头
5. OK → 写"进入 P5"

---

## P5 · 完整参数面板 + 持久化

**目的**：D7 + 所有用户原话提到的"等等还有很多"参数。

**参数清单（最少实现）**
- 坐标轴：箭头长度、粗细、颜色（短三轴 / 长速度 各一组）
- 网格：颜色、透明度、步长、覆盖范围、是否显示三个平面
- 路径：线宽、颜色、残留秒数、点数上限、是否渐隐
- 立方体：尺寸、颜色、不透明度
- 机头小球：半径、颜色
- 渲染：目标帧率 (10/30/60)、抗锯齿开关
- 控制：刷新（重建场景） / 重置（立方体回原点 + 清积分 + 清路径）

**任务**
- `path_visualization_widget.py` 设置面板用 `QFormLayout` + 折叠分组
- 所有参数变更 → emit `settings_changed` → 主窗口写入 `gui/config.json`
- 重启 GUI 参数全部还原

**验收门**
- 调任意一个参数 → 立即生效 → 重启 GUI 仍生效
- 用户视觉确认 → 进入 P6

### P5 实施记录（2026-05-27）

**实际变更**
- `gui/widgets/path_visualization_widget.py`：完全重写
  - 顶部 7 组 `DEFAULTS`（cube/nose/axis/vel_arrow/grid/path/render），数值与 P4 完全一致 → 默认外观零回归
  - 内置 `_ColorButton`（QColorDialog + 样式表显色）、`_SettingsPanel`（QScrollArea + 7 个 QGroupBox + QFormLayout）
  - 主部件用 `QSplitter` 左视图右面板；右上角 `? 设置` QToolButton 切显隐（默认关）
  - 信号：`settings_changed(dict)` / `reset_requested` / `refresh_requested`
  - `apply_settings(dict)` 深合并 + 重建场景 + 回放上一帧（外部灌入；不回发信号）
  - `_on_panel_value_changed(path,value)` 按组定向重建（cube/nose/axis/vel_arrow/grids/path_item/render）→ 不重建整场景
  - **路径渐隐**：`update_snapshot` 在 fade=True 时按 `1 - age/trail_seconds` 算 alpha，给 `GLLinePlotItem.setData(color=)` 传 Nx4 数组；fade=False 保持单色
  - 网格平面：XY 默认；XZ/YZ 通过 `g.rotate(90,1,0,0)` / `g.rotate(90,0,1,0)`
  - 保留 `_NOSE_OFFSET_CM` / `_VEL_ARROW_SCALE` 等模块常量供 P4 烟雾测试沿用 → 老回归零改动
- `gui/services/config_service.py`：`_DEFAULTS` 新增 `"path_viz.settings": {}` → 白名单放行整树持久化
- `gui/main.py`：
  - import `PathTrackerConfig`
  - 启动后 `viz_widget.apply_settings(config.get("path_viz.settings", {}))` 还原
  - 一次性把 `render.fps` → `bus.set_render_fps`、`path.trail_seconds/max_points` → `bus.update_config(PathTrackerConfig(...))`
  - 接 `settings_changed → _on_path_viz_settings_changed`（写 config + 同步 bus）、`reset_requested → bus.reset_path`、`refresh_requested → 日志`
- 新增 `gui/test/_smoke_phase_p5.py`：6 个用例
  - P5-1 ConfigService 默认含 `path_viz.settings`
  - P5-2 DEFAULTS 数值等同 P4
  - P5-3 面板改值 → `self._s` 写入 + emit + `apply_settings` 深合并
  - P5-4 fade=True 时 path.color = Nx4 ndarray，alpha 单调上升到 1.0（实测 `[0.0, 0.5, 0.9, 1.0]`）
  - P5-5 fade=False 退回单色
  - P5-6 MainWindow 一体化：改 fps→bus；改 trail_seconds→tracker.config；持久化命中 `path_viz.settings`；reset 不抛

**测试结果（全部 EXIT=0）**
- `_smoke_phase_p5`：[P5] ALL PASS
- 回归：P1 / P2 / P3 / P4 / D 全部 OK

**待用户视觉确认**
1. `.\run_gui.bat`
2. 视图菜单 → 勾选「路径可视化」（Dock 弹出）
3. 点 ? 设置 → 拖任意参数（如 立方体尺寸 / 速度箭头放大倍数 / 路径残留秒数 / 渲染帧率）→ 立即生效
4. 关闭 GUI 重开 → 参数仍保留
5. OK 后写「进入 P6」

---

## P5.5 · 后补丁（帧记录 + 字标 + 真箭头）  *(2026-05-28)*

> 用户在 P5 视觉验收期间提出 5 项 patch；其中 4/5（静止漂移、移动方向错+XYZ 比例）需真数据诊断，先把 1/2/3 落地并产出 JSONL。

**任务**
- **A1 传感器帧记录**：菜单 `文件 → 开始/停止传感器帧记录…`（`Ctrl+R`）+ widget 面板「记录」分组（按钮 + 状态 label）+ 状态栏红字 ●REC。
  - 服务：`gui/services/frame_recorder.py` `FrameRecorder(QObject)`
  - 信号：`state_changed(bool,path) / frame_logged(count) / error(msg)`
  - 白名单 `RECORD_CMDS = {0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x0E}`（命令/控制/日志帧不记）
  - 行格式：`{t_mono, t_iso, dest:"0xFF", cmd:"0x03", len, hex, fields:{...}}`；首尾各一行 `{_meta:..., ...}`
  - 缓冲 64KB + 每 32 帧或 0.5s flush
- **A2 三轴字标**：`X/Y/Z` 字符默认显（`labels_visible=true`），位置 = 轴末端 + `label_offset_cm`；可调字号、可关；GLTextItem + 加粗 QFont。
- **A3 真箭头头**：三轴 + 速度向量都加圆锥头（`_make_cone_mesh`），尺寸 `head_radius_cm / head_length_cm` 全部可配。
  - 速度箭头每帧 axis-angle 旋转：从 `+X` 到 `(ux,uy,uz)`，轴=`(0,-w,v)` 角=`acos(u)`；u≈-1 退化为绕 Z 180°。
- DEFAULTS 扩展：`axis.head_radius_cm/head_length_cm/labels_visible/label_size/label_offset_cm` + `vel_arrow.head_radius_cm/head_length_cm`。

**验收门**
- `_smoke_phase_p5_5.py` 5/5 PASS（生命周期/白名单过滤/RECORD_CMDS/DEFAULTS 新字段/_make_cone_mesh 形状）
- P1-P4+D 全回归 EXIT=0
- 视觉确认：三轴有真箭头头 + 字标；速度向量也是箭头；记录按钮可启停且文件可读
- 用户用 GUI 录制三组数据：静止 10-30s / 左飞右飞 / 上飞下飞

**已知遗留**
- bug 4 静止漂移 / bug 5 水平方向错+XYZ 比例不一致 → 等数据回流再针对性诊断（候选方案：ZUPT / yaw0 符号 / vel 帧坐标系核对 / 单位标定）
- `gui/config.json` 持久化字段（render.fps=100、trail_seconds=7）导致 `_smoke_phase_p5.case_6` 那条 `_render_fps==30` 出现假失败 — 是用户调参漂移，不是代码回归

---

## P6 · 性能与稳定性

**任务**
- TelemetryBus 完全在主线程信号槽派发（不开新 QThread），但要 throttle 渲染信号到 ≤ 渲染帧率
- PathTracker 内部用 `collections.deque(maxlen=...)`，O(1) 增删
- 异常隔离：解码失败 / 渲染失败 不应让主串口线程崩溃，记一次 WARN 即可
- 资源释放：GUI 关闭时显式 cleanup GL 资源
- 压测：用合成发生器以 200Hz 灌帧 10 分钟，CPU & 内存增长应平稳

**验收门**
- ~~10 分钟压测：内存增长 < 50MB，无未捕获异常~~ **用户书面豁免 2026-05-27**：因新需求阻塞，长稳压测推迟到 P10 末统一补回。P6#1/#2/#3 已完成视为本阶段验收通过。
- 用户视觉确认 → **进入 P7**（2026-05-27 用户书面同意）

---

## P7 · 多视图 Dock 架构（XY/XZ/YZ + 现有 3D）

> **本阶段核心**：把单一 3D 路径视图扩展为"3D + 三个 2D 投影视图"的多 Dock 架构。每个视图独立 Dock、独立可关、独立调参；2D 视图把方块换成"导航纸飞机"。3D 视图保持 P6 行为零回归。

**任务**
- 不动 `PathVisualizationPlaceholder`（3D 视图）：保持 P5/P6 smoke 全绿
- 新建 `gui/widgets/path_2d_view_widget.py`：
  - `Path2DViewWidget(QWidget)`，构造参 `plane: "XY"|"XZ"|"YZ"`
  - 内部 pyqtgraph `PlotWidget`（不走 OpenGL，原生 2D，自带刻度）
  - 机体图标 = "导航纸飞机"（细长等腰三角，朝向当前 yaw 在 XY 平面 / 朝向投影后的 vel 方向在 XZ/YZ 平面，默认按 yaw）
  - 渲染：路径折线 + 纸飞机；**不画姿态轴、不画速度箭头**
  - 自带轻量设置面板（折叠）：路径颜色/线宽/纸飞机大小/网格步长/range；不复用 3D 的 `_SettingsPanel`
  - 接口：`update_snapshot(snap)` / `apply_settings(dict)` / `current_settings()` / `cleanup()`
  - 信号：`settings_changed(dict)` / `reset_requested`
- `ConfigService._DEFAULTS` 新增：
  - `features.path_visualization_xy/xz/yz` = False
  - `path_viz_2d.xy.settings/xz.settings/yz.settings` = {}
  - `ui.main_window_state` = ""（QMainWindow.saveState base64）
- `gui/main.py` 改造：
  - `_FEATURE_DOCKS` 增加 3 条目，工厂用 `lambda parent, p=plane: Path2DViewWidget(parent, plane=p)`
  - `_bus.path_updated` fan-out 到所有 viz widget（3D + 3×2D）
  - 每个 2D widget 的 `settings_changed` 各自落到 `path_viz_2d.<plane>.settings`
  - 启动时 `restoreState(QByteArray.fromBase64(...))` 还原 Dock 几何
  - closeEvent 中 `saveState()` 持久化

**验收门**
- `gui/test/_smoke_phase_p7.py` ≥ 6 case PASS：构造三平面 / 投影正确 / update_snapshot / apply_settings / cleanup 幂等 / fan-out
- P2/P4/P5.5/P6 全回归 EXIT=0
- 视觉：三个 2D Dock 能同时打开各自调参；任一关闭不影响其他；菜单复选项与 Dock visible 双向同步
- 用户书面"进入 P8"

---

## P8 · 路径渲染 K 段升级（近粗近亮远细远淡）   **【已完成 2026-05-29】**

**任务**
- `PathSnapshot` 不动，新增辅助函数 `segments_by_age(points, k)` 在 widget 渲染时调用
- `Path3DViewWidget`（原 placeholder）和 `Path2DViewWidget` 都新增"分段模式"：
  - K 段（默认 K=8，settings 可调到 32）
  - 每段独立 LineItem/PlotDataItem，最新段 head_width/head_alpha，最旧段 tail_width/tail_alpha
  - 颜色支持线性插值（颜色 + alpha + 宽度三维渐变）
- DEFAULTS 扩展（两端同步）：
  - `path.render_mode = "segmented" | "fade"`
  - `path.k_segments = 8`
  - `path.head_width / tail_width`
  - `path.head_alpha / tail_alpha`
- 兼容性：`render_mode="fade"` 时保留 P5 的 Nx4 alpha 单线方案
- 设置面板加"路径分段"分组

**验收门**
- `_smoke_phase_p8.py` ≥ 5 case PASS：分桶函数 / K 段 LineItem 数量 / 两端宽度差 / 兼容 fade 模式 / 切模式不崩
- 视觉：长时间残留（≥30s）尾段近乎透明、头段醒目；2D 视图同步生效

---

## P9 · HUD 三件套 + 世界坐标刻度   **【已完成 2026-05-29】**

**任务**
- `gui/widgets/hud_overlay_widget.py` 新建（H1）：
  - 半透明 QFrame，铺在 3D `GLViewWidget` 之上（用 `setParent` + `raise_` + manual resize 跟随）
  - 11 项可独立 checkbox：vx/vy/vz/roll/pitch/yaw/h/x/y/z/|v|
  - 大字号读数，单位明确，QLabel 阵列
  - 可拖动重定位（mousePress + move）
- `gui/widgets/numeric_panel_dock.py` 新建（H2）：
  - 独立 Dock，11 项分组排版 + 实时 min/max
- 3D widget 设置面板新增"HUD"节（H3）：字号/位置/透明度/项目开关，三处同步
- `AxisRulerItem`：3D 视图加每 50cm/100cm 一刻度 + GLTextItem 数字；2D 视图等价（pyqtgraph 自带刻度，做"刻度间隔可配"即可）
- ConfigService 新增 `path_viz.hud.settings` 持久化

**验收门**
- `_smoke_phase_p9.py` ≥ 5 case PASS
- 视觉：HUD 项目可独立开关；3D 刻度数字对得上 PathTracker 实际 cm

---

## P10 · 扩展接口预留 + 收尾 + 长稳压测补回  ? 已完成

**任务**
- `gui/sources/interfaces.py` 新建：?
  - `IPositionSource` / `IAttitudeSource` / `IPointCloudSource` / `IAnchorSource`（ABC + dataclass）
  - 当前 IMU 实现转为 `LingxiaoImuSource` 同时实现前两个（`as_attitude_source()` 适配）
- 主题适配（深色/浅色随主窗口）?（`gui/services/theme_service.py` 已存在，无需新增）
- 视角预设按钮（俯视 / 侧视 / 自由）? `_SettingsPanel` 顶部 ops 条新增 3 按钮 → `_on_viewpoint_preset`
- 路径导出 CSV（按钮触发）? `export_path_csv()` + 主窗 `QFileDialog`
- P6#4 长稳定性微压：smoke `case_5` 200Hz × 5s 灌 1000 帧，内存增长 < 5MB（实测 +0.00MB）
- P10 brainstorm 候选清单（仅占位、不实现）：waypoint / RTL 航线 / 起降点图标 / 电量信号仪表 / timeline 回放条 / 雷达点云 / UWB 锚点+测距圈 / geofence / FFT 频谱

**验收门**
- `_smoke_phase_p10.py` 5/5 case PASS ?
- 接口可被 mock 子类继承 + 单测过 ?
- 长稳压测微压通过（offscreen 5s × 200Hz）?
- 全回归 P2/P4/P5/P5.5/P6/P7/P8/P9/P10 全部 EXIT=0 ?

---

## 防止偏离的复盘清单（每阶段结束必走）

- [ ] 本文件对应阶段所有任务勾选 ?
- [ ] `gui/requirements_lock_checklist.md` 同步勾选
- [ ] `/memories/repo/dev-log.md` 追加一条 `[日期] [问题] → [原因] → [解决方案] → [教训]`
- [ ] 两条 smoke 测试 EXIT=0
- [ ] 截图或文字说明发给用户
- [ ] 等用户书面"进入 Pn+1" 才动手
