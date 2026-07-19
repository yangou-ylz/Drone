# 路径可视化大阶段 · 锁定摘要

**权威计划文件**：`gui/path_viz_master_plan.md`（每次开发前必读）

## 强约束
1. 阶段必须串行；未完成上一阶段验收门，**不准开下一阶段任何代码**
2. **禁止自主推进阶段**——必须等用户书面"进入 Pn+1"
3. 每阶段结束跑 `gui/test/_smoke_phase_d.py` 和 `_smoke_phase_e.py`，EXIT=0
4. 协议歧义先查 `用户手册/*.pdf`，再写代码

## 用户已拍板的 9 项决策（D1-D9）
- D1 渲染：pyqtgraph.opengl
- D2 入口：顶部"功能"菜单 → 复选项控制 Dock 显隐
- D3 门控：后台积分常驻，**仅渲染受开关控制**
- D4 坐标系：机体 FLU（前x+ 左y+ 上z+），激活瞬间快照 yaw0，世界系不再旋转
- D5 Z 源：0x05 绝对高度；X/Y 用 vx/vy 积分（去 yaw0 旋转）
- D6 指示：小球=机头(yaw)；长箭头=速度向量；**两者解耦**
- D7 路径：时间衰减 + 点数上限兜底
- D8 姿态帧：0x04 四元数（0x03 仅 fallback）
- D9 日志：仅启动/停止/重置/异常打日志，正常帧静默

## 阶段表
P0 协议语义冻结 → P1 顶部下拉栏骨架 → P2 数据通路+后台积分 → P3 最小 3D 场景 → P4 姿态/小球/速度箭头 → P5 完整参数面板 → P6 性能稳定性 → **P7 多视图 Dock（XY/XZ/YZ）** → **P8 K 段路径渲染** → **P9 HUD + 世界刻度** → **P10 扩展接口+收尾+长稳压测**

## 当前阶段
**P10 完成 (2026-05-29)，GUI 路径可视化大阶段 (P0-P10) 全部完成 ✅**

- P10 已交付：`gui/sources/__init__.py` + `gui/sources/interfaces.py`（4 ABC 接口 + 3 frozen dataclass + LingxiaoImuSource 适配器，多继承同名 latest() 用 as_attitude_source() 适配解决）；扩 `path_visualization_widget.py`（_SettingsPanel ops 条 +3 视角按钮 +1 CSV 按钮 +2 signal；PathVisualizationPlaceholder 透传 signal + 3 处 wiring + _VIEWPOINT_PRESETS 字典 + _on_viewpoint_preset + export_path_csv 方法）；扩 `main.py`（_on_path_viz_export_csv 用 QFileDialog + QMessageBox）；theme_service.py 已存在无需新增。
- smoke `_smoke_phase_p10` 5/5 PASS（interfaces+Mock / LingxiaoImuSource / 视角预设 / CSV 导出 / 长稳定性微压 200Hz×5s 内存+0.00MB）；全回归 P2/P4/P5/P5.5/P6/P7/P8/P9/P10 EXIT=0。
- 关键决策：
  - LingxiaoImuSource 多继承冲突 → 内部 _AttView 适配器；不让用户直接用 latest() 拿姿态
  - tracemalloc.get_traced_memory() 取代 psutil RSS 作内存增长门
  - 视角预设值：top elev=89/azim=0、side elev=5/azim=90、free elev=28/azim=45，dist 全 600
  - PathSnapshot 字段是 tuple（pos_cm/attitude_deg），不是散字段；CSV 用 snap.points 列表

**历史阶段：P9 HUD 三件套 + 世界坐标刻度（2026-05-29 完成）**
- P6#4 长稳压测**用户书面豁免**，推迟到 P10 末统一补回
- P9 已交付：`gui/widgets/_hud_model.py`（11 项 HUD key + 计算 vmag/h + DEFAULTS）；`gui/widgets/hud_overlay_widget.py`（GL 子浮窗 QFrame，QSS rgba，可拖拽 clamp，settings/position 双 signal）；`gui/widgets/numeric_panel_dock.py`（QDockWidget 三分组 11 行 + min/max + reset）；扩 `path_visualization_widget.py`（DEFAULTS["hud"] / _SettingsPanel 加叠加层外观/显示项目/世界刻度三子组 / _hud_overlay 子件挂 _view / _rebuild_axis_ruler GLLine+GLText / cleanup_gl 拆解）；扩 `main.py`（NumericPanelDock + 菜单 toggle + 双向 settings 桥）；扩 `config_service.py`（path_viz.hud.settings + features.numeric_panel）
- smoke `_smoke_phase_p9` 6/6 PASS（vmag/h / overlay apply+update / NumericDock min-max-reset-组隐藏 / 3D widget hud emit / 3D ruler toggle）；P2/P4/P5/P5.5/P6/P7/P8 全回归 EXIT=0（P5-6 仍是 config 漂移假失败，reset render.fps=30 后过）
- 关键决策：
  - pyqtgraph GL/2D 的线宽 **per-item 不是 per-vertex** → 想要"分段不同宽"只能拆 K 个 LineItem
  - segments[i] 末点 = segments[i+1] 首点（hi_inclusive = min(n, hi+1)）→ 视觉不断节
  - 旧测试 P5-4/P5-5/P7-2/P7-3 都用 `apply_settings({path:{render_mode:"fade"}})` 显式切回单线（最小破坏）
  - ConfigService 整树持久化（path_viz.settings 一个 key 装全部子树），P8 新字段无需 _DEFAULTS 子键
  - 默认 K=8，head_width=3 tail_width=1，head_alpha=255 tail_alpha=40
- **下阶段需用户书面"进入 P9"** 才动 HUD/numeric panel/AxisRulerItem 任何代码

**历史阶段：P5.5 代码完成（视觉已验收）**
- P0/P1/P2/P3/P4 ✅（详见 master plan）
- P5 ✅ 完整参数面板 + 持久化：
  - widget 内置 `DEFAULTS` 7 组（cube/nose/axis/vel_arrow/grid/path/render），数值等同 P4
  - `_SettingsPanel` = QScrollArea + 7×QGroupBox + QFormLayout；`⚙ 设置`按钮切显隐（默认关）
  - 信号 `settings_changed(dict)` / `reset_requested` / `refresh_requested`；`apply_settings(dict)` 深合并 + 重建
  - `_on_panel_value_changed(path,value)` 按组定向重建（_rebuild_cube/nose/axis/vel_arrow/grids/path_item），不重建整场
  - 路径渐隐：fade=True → setData(color=Nx4)；fade=False 保持单色
  - 保留 `_NOSE_OFFSET_CM` 等模块常量 → P4 测试零改动
- `ConfigService._DEFAULTS` 必须登记 `"path_viz.settings": {}`，否则白名单丢弃
- `main.py` 链路：启动 `apply_settings(config.get("path_viz.settings", {}))` → 同步 bus.set_render_fps + bus.update_config(PathTrackerConfig)；signals → `_on_path_viz_settings_changed`（写 config + 同步 bus）+ `_on_path_viz_reset`
- smoke `_smoke_phase_p5` 6/6 PASS；P1/P2/P3/P4/D 全回归 EXIT=0
- 关键决策记录（沿用 + 新增）：
  - quat V0 默认=w 标量；若实测错以 `_QUAT_W_INDEX=3` 一行翻
  - yaw 反旋转用 `R(-yaw0)`；方向反在 `PathTracker._yaw0_sin/cos` 翻号
  - D5：Z 是"相对 enable 时刻"，非绝对高度
  - widget 类名沿用 `PathVisualizationPlaceholder` 不改
  - offscreen 平台 OpenGL context 失败属正常，视觉验收必须真桌面
  - Transform3D post-multiply 顺序：translate→rotate(z)→rotate(y)→rotate(x) = OpenGL ZYX
  - **新**：ConfigService 加新 key 必须同时改 `_DEFAULTS`，白名单设计会静默丢弃未登记 key
  - **新**：GLLinePlotItem.color 支持 Nx4 numpy 数组做逐点 alpha；单色传 tuple/list 即可
  - **新**：widget `apply_settings` 走"外部灌入不回发信号"语义；`_on_panel_value_changed` 走"用户改 → 必回发"语义；两者别混
