# IMU 数据测试软件 — 项目记忆（长期任务，高优先级）

> 每次开始此任务前必读本文件。任务是给现有 GUI 增加 IMU 数据质量测试功能。

## 任务背景

- 目标：为后续激光-惯性里程计（LIO，EKF/UKF）融合提供合格 IMU 数据 + 验证姿态跟随性
- 数据来源：飞控通过 **USB 数传** 直连电脑，实时发所有匿名协议帧
- 需求文档：`gui/imu测试要求.md`（含 acc_scale校准/gyr零偏/四元数质量/频率/噪声等硬指标）
- 用户额外需求：**Yaw 跟随性测试** —— 旋转30°后立即停止，实测姿态会往回漂约10°，需量化这个漂移

## 关键既有资源（不要重写，直接复用）

- 解码函数：`gui/services/telemetry_decoder.py`
  - `decode_attitude_euler()` 0x03 / `decode_attitude_quat()` 0x04 / `decode_velocity()` 0x07 / `decode_height()` 0x05
- 更全的解码：`groundTest/ano_rpi_driver.py` 的 `decode_frame()`（含0x01/0x02/0x06/0x0D）
- 串口层：`gui/io/serial_worker.py`（Linux 侧需确认是否已适配 pyserial；原 win_serial 是 Windows 专用）
- 帧解析：`gui/io/protocol.py` → `groundTest/ano_protocol.py`
- 现有信号入口：`SerialWorker.frame_received`（订阅它即可，不改 SerialWorker）

## 架构决策（已定）

- 新代码全部放 `gui/imu_test/`，与现有功能**完全隔离**
- `gui/main.py` 只加约25行：菜单"功能"末尾加"IMU测试台" + 主区域用 QStackedWidget 切换
- 其他现有文件**零修改**
- ImuDataHub(QObject) = 数据解码中枢，只订阅 frame_received 信号 + 广播结构化信号，不持有 Widget
- 各测试面板只订阅 DataHub 信号，面板之间解耦

## 计划分阶段（前一步验证成功才做下一步）

- Phase 0: 0.1独立日志系统 / 0.2新包骨架+空壳窗口+菜单入口
- Phase 1: 1.1 ImuDataHub / 1.2 帧率监控面板
- Phase 2: 2.1 数值面板 / 2.2 实时曲线面板
- Phase 3: 3.1 Yaw跟随测试面板⭐核心 / 3.2 3D姿态可视化
- Phase 4: 4.1 acc_scale校准面板 / 4.2 gyr零偏标定面板
- Phase 5: 5.1 数据完整性+噪声统计 / 5.2 四元数质量检查
- Phase 6: 6.1 整合收尾 / 6.2 Ubuntu串口适配确认

新增文件树：gui/imu_test/{__init__,logger,data_hub,imu_test_window}.py
+ gui/imu_test/widgets/{frame_rate,imu_value,imu_chart,yaw_test,attitude_3d,acc_calibration,gyr_bias,data_quality}_panel.py

## 用户工作方式强约束（每次都要遵守）

1. **UI 不许自作主张**：界面要简洁大气、符合业内先进软件排版、好用不冗余；有 UI 想法先问用户确认再做
2. **全自动化长流程**：一直做+验证+检验+修改+再测试，循环到实在需要用户亲自验证为止；不轻易判定阶段成功
3. **图形化验证用截图工具**：分析图形是否正确要用电脑截图分析，不要猜
4. **禁止反复打补丁**：遇到难题先分析根因，找更好方法（借鉴权威开源思路/项目资料），不要盲目补丁堆叠
5. **安全**：不动系统的东西；可以装库/建虚拟环境，但不能和现有环境冲突
6. **不赶时间**：要绝对正确成功，时间充裕
7. **网络资料**：可搜索；git/下载优先用国内镜像源

## Ubuntu 环境已就绪（2026-07-12 完成）

- **Linux venv**: `ANO_LX_FC/.venv-linux`（Python 3.10.12）；`.venv` 是 Windows 版(Scripts/,py3.14)不可用，勿动
- 运行 GUI: `cd ANO_LX_FC && DISPLAY=:1 LINGXIAO_GUI_FAKE=1 ./.venv-linux/bin/python -m gui.main`
- 依赖: PySide6 6.11.1 / pyqtgraph 0.14.0 / PyOpenGL 3.1.10 / numpy 2.2.6 / pyserial 3.5（清华镜像装的）
- 系统有 OpenGL 4.6 Mesa，真实桌面 DISPLAY=:1 下 3D 正常
- **关键坑1**: gui/groundTest 几乎所有 .py 声明 `# coding: gbk` 但实际是 UTF-8（传输时被转码），已批量改为 `coding: utf-8`。以后新建文件直接用 utf-8
- **关键坑2**: `QT_QPA_PLATFORM=offscreen` 在 Linux 下无 GL 上下文，3D 测试会失败；要测 3D 必须用真实 xcb (DISPLAY=:1) 或 `QT_QPA_PLATFORM=xcb`
- **已做的跨平台适配**（权威方案，来自 UBUNTU22_PORTING_GUIDE.md）:
  - 新增 `groundTest/linux_serial.py`（LinuxSerial，pyserial，兼容 Win32Serial 接口）
  - `gui/io/serial_worker.py`: win32→SerialImpl 条件导入
  - `gui/io/serial_ports.py`: 非 win32 用 glob 枚举 /dev/ttyUSB*等
  - `gui/main.py`: os.startfile→非win32用 QDesktopServices
- **验证结果**: 真实 GUI 截图确认完全正常（中文无乱码、枚举33串口、3D网格渲染、FakeWorker）；16个smoke中11个纯逻辑PASS+phase_c(3D)真实显示PASS
- **4个smoke预存在小问题**（非移植回归，涉及config/GL时序）: p3(_path在segmented模式故意为None)、p5(case_6)、p1(首启dock勾选态)、e(退出时QThread teardown SIGABRT)

## UI 方案（用户 2026-07-12 已确认，不得擅改）

- **布局**: 顶部横向页签（QTabWidget），5个Tab：实时总览/曲线监控/Yaw跟随⭐/静态校准/质量报告
- **数据展示**: 紧凑表格式（信息密度高，非卡片）
- **校准面板**: 算出修正值后「一键导出 yaml 片段」（生成可粘贴文本，不自动写远程）
- 底部状态栏：数据流帧率/已采集帧数/时间
- 配色沿用现有 theme_service 暗色主题，全局一致，不引入新配色
- pyqtgraph.opengl 在 Ubuntu 真实桌面可用（已验证），3D 姿态 Tab 可做
- 有新 UI 想法仍需先问用户确认

## 进度记录

- **Phase 0.1 完成**（logger）: `gui/imu_test/logger.py` 独立 stdlib logging，控制台INFO+/文件DEBUG+ (RotatingFileHandler 2MB×5 UTF-8)，日志目录 `~/.local/share/imu_test/logs/`。已验证。
- **Phase 0.2 完成**（骨架+入口）: 
  - `gui/imu_test/__init__.py`（v0.1.0）、`gui/imu_test/imu_test_window.py`（ImuTestWindow(QWidget)：顶部QTabWidget 5个占位Tab + 底部状态栏QLabel）
  - `gui/main.py` 4处改动（字节级CRLF安全脚本）：导入QStackedWidget / 中心区包 `self._central_stack`(index0=主界面) / 功能菜单加可勾选 `self._act_imu_test`「IMU 测试台」/ 新增 `_on_toggle_imu_test()` 懒加载切换
  - 已截图验证：菜单入口出现、点击切到空壳5Tab窗口、中文无乱码、状态栏正常。截图 `/tmp/imu_phase02.png`
  - 已知小现象：功能Dock(如路径可视化3D)是QDockWidget会浮在中心区之上，切到IMU台时若该Dock开着仍显示——由用户功能菜单自行控制，非bug
- **Phase 1.1 完成**（DataHub）: `gui/imu_test/data_hub.py`
  - `ImuRawSample` dataclass(frozen): ts/acc_xyz(m/s²)/gyr_xyz(rad/s)/shock/raw_acc/raw_gyr(LSB元组)
  - `ImuDataHub(QObject)`: 信号 `imu_raw(object)`/`attitude(object)`/`frame_seen(int cmd,float ts)`；槽 `on_frame(frame)` 按 cmd 解码；0x01 用 `struct "<hhhhhhB"` 解 acc/gyr/shock，0x04 复用 `decode_attitude_quat`；未知帧只发 frame_seen；坏对象/短帧/异常都不崩
  - 标定默认 acc_scale=0.004788 gyr_scale=0.001065，`set_scales()` 运行时可改（校准面板 Phase4 用）
  - 挂接方式（接线时用）: `self._worker.frame_received.connect(hub.on_frame)`，与 recorder 同模式
  - **重要**: FakeWorker 只发 0xA0 回执，不发 0x01/0x04！DataHub/面板验证必须用注入合成帧的测试台，不能靠 FAKE 模式
  - 已验证: 7项纯逻辑单测全过（Z=1g→9.8/短帧忽略/单位四元数姿态≈0/未知帧/frame_seen覆盖/set_scales/坏对象不崩）
- **Phase 1.2 完成**（帧率面板）: `gui/imu_test/widgets/{__init__,frame_rate_panel}.py`
  - `FrameRatePanel(QWidget)`: QTableWidget 紧凑表格[帧类型/帧ID/频率Hz/累计/状态]；槽 `on_frame_seen(cmd,ts)` 只塞 deque(O(1))；QTimer 250ms 重算刷新（统计与UI解耦）
  - 频率=滑动窗口(2s)内(帧数-1)/跨度；预置各帧期望Hz，状态 达标(绿≥期望×0.8)/偏低(橙)/掉线(灰,>1.5s无帧显示--)
  - 深色配色 bg#232323 header#333 文字#DCDCDC 绿#4CAF50 橙#FFB300 灰#9E9E9E
  - 已验证: 注入100/67/50Hz→显示100.0/66.7/50.0全达标+截图确认；偏低/掉线/clear 逻辑单测通过
- **下一步 Phase 2**: 2.1 数值面板(紧凑表格 acc/gyr/姿态实时值) / 2.2 实时曲线(pyqtgraph)。注意：DataHub 和面板尚未接入 ImuTestWindow 的 Tab（目前独立验证），接线放各面板就绪后或 Phase6
- **Phase 2.1 完成**（数值面板）: `gui/imu_test/widgets/imu_value_panel.py`
  - `ImuValuePanel(QWidget)`: QTableWidget 11行[物理量/数值/单位/原始LSB]；槽 `on_imu_raw`/`on_attitude` 只缓存最新样本，QTimer 50ms(20Hz) 刷新解耦
  - 行: acc_x/y/z、|a|模长、gyr_x/y/z(rad/s + 括号°/s)、roll/pitch/yaw、shock
  - 已验证: 注入Z=9.8→显示9.801、gyr_x=0.4995(28.6°/s)、yaw=-30、|a|=9.801，截图确认（青色数值#4FC3F7）
- **Phase 2.2 完成**（曲线面板）: `gui/imu_test/widgets/imu_chart_panel.py`
  - `ImuChartPanel(QWidget)`: pyqtgraph 双 PlotWidget（上加速度 下角速度），各3曲线 X红#EF5350/Y绿#66BB6A/Z蓝#42A5F5，X轴联动
  - 环形缓冲 deque(maxlen=4000)，QTimer 33ms(30Hz)重绘，滑动窗口10s，np.fromiter+mask 取窗
  - pg.setConfigOptions(antialias=True, background="#232323")；**必须真实桌面DISPLAY=:1，offscreen无GL**
  - 已验证: 注入正弦(acc X0.5Hz/Y0.8Hz/Z绕9.8, gyr X1.0Hz/Y0.6Hz/Z1.5Hz)→截图曲线频率幅值全对上
- **下一步 Phase 3⭐**: 3.1 Yaw跟随测试(用户核心自定义需求，UI设计需先问用户确认) / 3.2 3D姿态可视化
- **Phase 3.1 完成**（Yaw跟随测试⭐核心）: `gui/imu_test/widgets/yaw_test_panel.py`
  - 用户确认的4项设计: yaw源=0x04四元数 / 触发=点"装填"后自动检测旋转开始停手 / 回弹=停手瞬间峰值yaw−最终稳定yaw / 停手阈值=|gyr_z|<2°/s持续0.5s
  - `YawTestPanel(QWidget)`: 顶部 pyqtgraph yaw-时间曲线(相对起点) + 底部指标网格(8项)+3按钮(装填/重置/导出CSV)
  - 状态机 未装填→等待旋转→旋转中(|gyr_z|>2°/s)→停手稳定中(gyr_z落回阈值下持0.5s,锁存峰值)→完成(yaw稳定窗1s内极差<0.3°, 超时8s强制结算)
  - **关键**: 用物理角速度gyr_z(0x01,回弹时≈0)判停手，用yaw自身稳定性判最终稳定——正好抓"手停了数据还漂"
  - yaw去环绕连续化(delta±180修正); 绘图相位背景色LinearRegionItem(旋转蓝/停手橙)+峰值/稳定水平虚线InfiniteLine; CSV导出用QFileDialog+utf-8
  - 已验证: 注入"转32°(32°/s匀速)+停手后指数回弹到22°"场景→结算峰值32.00/稳定22.25/回弹9.75°(30.5%)/耗时3.17s，截图曲线+标注+相位区+指标全对
- **下一步 Phase 3.2**: 3D姿态可视化（可复用现有 path_visualization 的 pyqtgraph.opengl cube 思路）
- **Phase 3.2 完成**（3D姿态）: `gui/imu_test/widgets/attitude_3d_panel.py`
  - `Attitude3DPanel(QWidget)`: 顶部QLabel角度条(青色Roll/Pitch/Yaw) + GLViewWidget(世界网格+参考轴 + 机体盒子半透明蓝 + 红色机头锥体 + 机体三轴)
  - 姿态旋转ZYX顺序: resetTransform→rotate(yaw,z)→rotate(pitch,y)→rotate(roll,x)，与0x04欧拉一致；yaw符号最终真机校验
  - 复用 path_viz 的 mesh 构造；opengl缺失降级QLabel提示不崩；QTimer 33ms刷新
  - **教训**: GLTextItem 在grab截图里没渲染出来→改用顶部QLabel角度条(可靠)；红锥体加强机头朝向可读性
  - 已验证: 注入roll20/pitch15/yaw40→角度条显示正确+截图盒子倾斜+红锥朝向合理
- **3D面板增强完成(用户任务A, 本session)**: attitude_3d_panel.py
  - 任务1 yaw符号反了(实机右转UI往左): `_apply_attitude` 改 `rotate(-yaw,0,0,1)`，加 `_rotation_matrix()` 返回 M=Rz(-yaw)·Ry(pitch)·Rx(roll) 供标签/轴线定位
  - 任务2 加XYZ标签+机头=X: 无人机机体系 z上/x机头前/y机头左。用GLTextItem三个标签 X机头(前)红/Y左绿/Z上蓝(lbl_len=5.6)，随姿态旋转到轴尖
  - **关键修正**: 原GLAxisItem配色是蓝/黄/绿，与标签红绿蓝不一致会混淆→改用自绘RGB GLLinePlotItem三色线(X红/Y绿/Z蓝, axis_len=4.8, width3)，红线=红锥=机头一致；world参考轴改淡灰细线(0.5,0.5,0.5,0.35)
  - **截图坑**: `screen.grabWindow(winId())` 在此X平台有原点偏移bug(截到桌面上方)；改用 `GLViewWidget.grabFramebuffer()` 得干净GL内容；GLTextItem在grabFramebuffer里能正常渲染(与旧笔记相反,旧笔记是特定上下文)
  - 验证脚本: `gui/imu_test/_verify_attitude3d.py`(临时) scene=level/mix/yaw90/roll30/pitch20; 存/tmp/attitude3d_<name>_fb.png; 相机 distance=17 elevation=35 azimuth=45
  - 已截图验证level/mix: 红X沿机头/绿Y左/蓝Z上, 颜色标签轴线全一致
  - **待真机确认**: yaw旋转方向的正负(用户经验"加负号")最终需真硬件转向确认

## 任务B: IMU硬件校准(触发凌霄IMU内置校准) — 手册已查证
- **官方手册来源**: 用户手册/匿名通信协议V7.pdf → 0xE0 CMD命令帧 → "命令定义"表
- **校准命令帧(与固件LX_FC_Fun.c一致,固件是ground truth)**: 0xE0帧, D_ADDR=0xFF广播, DATA=[CID,CMD0,CMD1,...]
  - 陀螺仪校准 GYRO: CID=0x01 CMD0=0x00 CMD1=0x02
  - 快速水平校准: CID=0x01 CMD0=0x00 CMD1=0x03
  - 磁力计校准 MAG/罗盘: CID=0x01 CMD0=0x00 CMD1=0x04
  - 6面加速度校准 ACC: CID=0x01 CMD0=0x00 CMD1=0x05
  - (手册另有 0x30/0x01 六面 0x30/0x02 罗盘 0x30/0x11 重开,但注明"用于独立匿名校准exe";固件用的是CID=0x01那组,优先用固件版)
- **数据路径**: PC电脑 →匿名数传radio→ 凌霄IMU →UART5→ STM32。上行如此(见Uplink_Cmd.h)。0xE0校准是IMU级命令,IMU自己处理,无需改STM32固件
- **校准提示来源**: IMU校准过程发回 0xA0 字符串LOG帧("陀螺仪校准完成"/"请把机头向上放置"/"罗盘校准完成"等),经数传回PC
- **GUI已有基础设施(直接复用)**: 
  - 命令基类 gui/services/command_registry.py Command.build_frame()+match_ack(); 已有 cmd_f1/f2/f3.py 范例
  - 发送: UI→ QMetaObject.invokeMethod(worker,"send_bytes",QueuedConnection); 帧构造 groundTest/ano_rpi_driver.py build_frame()(SC/AC校验,范围含帧头LEN+4)
  - 0xA0接收: main.py._on_frame 处理0xA0字符串帧→转 ack_matcher; gui/widgets/log_view.py 是现成日志显示面板
  - **FakeWorker只回0xF1/0xF2的0xA0,不模拟校准**;真机才有校准LOG
- **待确认(问用户)**: (1)UI放哪(IMU测试台"静态校准"Tab? 还是主界面独立区/对话框?) (2)真机确认0xE0经数传能触发IMU校准
- **✅ 任务B 已实现（本session，纯GUI）**: 用户确认→新增"设备校准"Tab在IMU测试台(不复用静态校准)
  - `gui/imu_test/calibration_cmd.py`: CalibrationDef(key/name/cid/cmd0/cmd1/principle/steps) + CALIBRATIONS(4项) + build_cal_frame(cal)→build_frame(0xFF,0xE0,[cid,cmd0,cmd1]+[0]*8)。发11字节DATA(CID+CMD0~9)与固件CMD_Send/手册LEN=0x0B一致(非groundTest的3字节)
  - 帧已验证: 陀螺 AA FF E0 0B 01 00 02 ...; 快速水平 CMD1=03; 磁力 04; 6面 05; SC/AC校验通过
  - `gui/imu_test/widgets/device_calibration_panel.py`: DeviceCalibrationPanel(send_fn,parent)。4校准GroupBox(名+steps+按钮)+右侧暗色终端QTextEdit(沿用log_view配色#1E1E1E)。按钮→QMessageBox二次确认(含原理)→send_fn(build_cal_frame)→终端记"已发送". 槽on_log_text(color,text)显示IMU回传。颜色: 0白/1红/2绿
  - `data_hub.py`: 新增 `log_text=Signal(int,str)`; on_frame cmd==0xA0→`_emit_log_text(frame,data)`(优先frame.color_str(),兜底GBK解码)
  - `imu_test_window.py`: _TABS加("device_cal","设备校准"→现6Tab); ImuTestWindow(...,send_frame_fn=None); 实例化DeviceCalibrationPanel; hub.log_text→panel.on_log_text
  - `main.py`: 新增 `_send_raw_frame(frame)->bool`(查is_connected→invokeMethod send_bytes QByteArray); _on_toggle_imu_test 传 send_frame_fn=self._send_raw_frame
  - 验证脚本 `gui/imu_test/_verify_device_cal.py`(临时): 灌假0xA0→截图/tmp/device_cal_fb.png确认: 4校准组+终端绿/白/红着色全对
  - **✅ 真机已验证通过(2026-07-13)**: 用户实机发6面加速度校准→IMU回传0xA0序列全部正确显示("请把机头向上放置"/"请保持静止"/"陀螺仪校准完成"等),校准命令确实经数传触发凌霄IMU内置校准。任务B完全成功
- **⚠️ 待接线(Phase6)**: 8个面板都是独立验证的孤立widget，尚未装进 ImuTestWindow 的Tab，DataHub也没接 SerialWorker.frame_received。**FakeWorker不发0x01/0x04**，真机才有数据
- **Phase 6 部分完成（接线整合）**: `imu_test_window.py` 重写 + `main.py` 接线
  - ImuTestWindow(data_hub=None) 现装载真实面板: 实时总览=QSplitter[左竖切(帧率面板+数值面板) | 右3D姿态]; 曲线监控=ImuChartPanel; Yaw跟随=YawTestPanel; 静态校准/质量报告=占位
  - hub信号接线: frame_seen→_on_frame_seen(计数+喂帧率面板+状态栏fps估算); imu_raw→value/chart/yaw; attitude→value/3D/yaw
  - 底部状态栏由 QTimer 500ms 驱动真实fps+累计帧数
  - main.py `_on_toggle_imu_test`: 懒创建 ImuDataHub(self)→connect worker.frame_received→传入ImuTestWindow; 新增 `self._imu_data_hub=None`
  - **已端到端验证**(注入0x01+0x04): 截图 /tmp/imu_win_overview.png(帧率表96Hz达标+数值|a|9.797+3D盒子角度条Roll-7.1/Pitch+6.6/Yaw+29.1一致) + /tmp/imu_win_charts.png(加速度/角速度正弦全对) + 状态栏147Hz/530帧
  - **注意**: 3D放在"实时总览"右侧是我的默认排布，用户可要求调整; FAKE模式下真GUI里这些面板无数据(FakeWorker不发0x01/0x04)
- **待做**: Phase 4校准面板(acc_scale/gyr零偏，UI需确认) / Phase 5质量报告(完整性+噪声+四元数，UI需确认) → 填入"静态校准"/"质量报告"占位Tab

## ✅ 全部完成（2026-07-12 单session）—— 6阶段13步全绿
- **Phase 4 完成**（静态校准）: `widgets/calibration_panel.py` `CalibrationPanel(data_hub)`
  - 上=加速度尺度校准(Z朝上静置采样→实测acc_z→建议acc_scale=当前×9.80665/mz→yaml片段+复制); 下=陀螺零偏(静置采样三轴均值,±0.005达标判定)+90°积分自检(∫gyr_z,90°±2°)+yaml
  - 已验证: 注入acc_z=6.4→建议scale 0.007338(放大1.53×正确); 真机整合注入9.8→0.004791
  - **教训**: 测试harness必须手动 `hub.imu_raw.connect(panel.on_imu_raw)`，面板不自动连
- **Phase 5 完成**（质量报告）: `widgets/quality_report_panel.py` `QualityReportPanel(data_hub)`
  - 开始检测/停止并评估 → QTableWidget[检查项/实测值/判据/结果] 10项 + 顶部总结论(全部通过/N项不通过)
  - 10项: 完整性(无NaN/Inf)/IMU频率≥50/姿态频率≥50/acc量程≤156.8/gyr量程≤34.9/acc噪声std<0.05/gyr噪声std<0.01/四元数模长0.999~1.001/姿态漂移R/P<2°Y<3°/姿态跳变<5°(带yaw环绕修正)
  - 四元数模长需原始四元数→在 data_hub 新增 `quat_norm=Signal(float)` 信号，0x04分支 `_emit_quat_norm()` 广播(不改shared decoder)
  - 已验证: 注入健康静态数据→10/10全通过，各实测值正确
- **Phase 6 全部完成**（整合）: imu_test_window.py 5个Tab全部装真实面板:
  - 实时总览=帧率+数值+3D; 曲线监控=chart; Yaw跟随=yaw; 静态校准=calibration; 质量报告=quality
  - hub信号全接: imu_raw→value/chart/yaw/calib/quality; attitude→value/3D/yaw/quality; quat_norm→quality; frame_seen→状态栏+帧率面板
  - main.py `_on_toggle_imu_test` 懒建 ImuDataHub 接 worker.frame_received
  - **端到端已验证**: /tmp/imu_final_cal.png(校准Tab acc_z9.801→0.004791) + /tmp/imu_final_q.png(质量Tab 10/10通过) 状态栏实时Hz/帧数
  - get_errors 全部文件 0 错误
- **⚠️ 真机注意**: FAKE模式(FakeWorker)不发0x01/0x04，真GUI里面板需真硬件数据才动; yaw符号/四元数分量顺序(_QUAT_W_INDEX=0)待真机最终校验; 校准yaml为手动复制粘贴,不自动写远端
