
# 开发日志 — 匿名凌霄室内四旋翼无人机

> **规则（强约束）**：
> 1. **每次开发会话开始前必须读取此文件**，了解当前进度和未解决问题。
> 2. **每次解决问题后必须立即追加记录**，格式：`[日期] [问题] → [原因] → [解决方案] → [教训]`
> 3. **每次完成一个功能后必须更新"当前进度"节**，标明已完成/进行中/待做。
> 4. **思考和回答必须紧贴当前任务目标**，禁止偏离目标做无关扩展。
> 5. 若本次修改涉及飞行安全，必须在记录中注明"⚠️ 安全影响"。


## 最高优先级纠错提示（2026-07-24）

- 光流/激光/外部传感无数据的最终现场根因已确认：异常 UART2 DAP/UART 复合串口模块接入树莓派 USB 后导致 `0x0D` 电池电压数据归零/消失，随后外部传感数据一起消失，并触发 `[A0 红] 运动解算失效复位`；拔掉后出现 `[A0 绿] 运动解算启动`。
- 旧记录中关于“IMU不采纳0x33/0x34/0x51”“0x34方向字段/0x33触发节奏可能错误”的判断，保留为坏硬件条件下的中间排查记录，但不再作为最终根因。
- 以后排查 G_VEL/ALT/0x33/0x34 无数据：先查 `0x0D` 电压、供电线、地线、UART2 USB-TTL/DAP-UART 反灌电和 5V/3.3V 电平，再查光流协议或 STM32 转发代码。完整记录见本文件 2026-07-24 “最终纠错”条目。


## 烧录/调试器环境 (2026-07-20)

[2026-07-20 J-Link被误用CMSIS-DAP脚本烧录] [用户运行`bash scripts/flash-dap.sh`报`unable to find a matching CMSIS-DAP device`] → [现场`lsusb`显示当前接入的是`1366:0105 SEGGER J-Link`, 没有CMSIS-DAP设备; 原`flash-dap.sh`固定加载`adapter driver cmsis-dap`, 因此必然找不到匹配DAP; 改用J-Link接口后OpenOCD进一步报`LIBUSB_ERROR_ACCESS`, 说明普通用户还没有J-Link USB访问权限] → [新增`openocd/stm32f407-jlink-low-speed-no-srst.cfg`, `scripts/probe-jlink.sh`, `scripts/flash-jlink.sh`; 保留原DAP脚本不动; `scripts/suggest-udev-rule.sh`的规则文件名提示改为通用`60-debug-probe-local.rules`] → [教训: 烧录失败先看`lsusb`实际探针类型, 不要默认DAP; J-Link需要`interface/jlink.cfg`/`adapter driver jlink`和SWD传输; 若报`LIBUSB_ERROR_ACCESS`, 先装/刷新udev规则或临时sudo验证, 再查SWD接线/供电; 若烧录阶段出现`Reduced speed from 8000 kHz`后读内存失败, 说明`target/stm32f4x.cfg`的reset-init自动提速触发链路不稳, J-Link脚本需覆盖reset-start/reset-init并保持100kHz; 若进一步报`timeout waiting for algorithm`, 烧录脚本改为`init; reset halt; sleep; halt; flash probe; flash write_image erase build-gcc/ANO_LX.hex; verify_image build-gcc/ANO_LX.hex; reset run`, 优先保证目标复位停稳并用HEX写入; ⚠️ 安全影响: 本次只改烧录脚本和本地工具链配置, 未改飞控运行逻辑]


## 树莓派位置测试 GUI 插播阶段 (2026-07-19)

[2026-07-19 位置测试第一阶段:0xF6镜像+GUI实时页] [用户暂停主线PID/SLAM推进,要求先做GUI“位置测试”,并明确推荐方案:不改树莓派已跑通的0xF5,新增STM32→IMU→数传→GUI标准下行调试帧; GUI采用工程仪表盘+坐标标定向导方案] → [根因: 树莓派0xF5走USB-TTL↔STM32 UART2链路, GUI数传接的是IMU/UTI链路,所以GUI不能直接看到完整0xF5; 若强行改0xF5会破坏树莓派已验证链路,最稳妥是STM32解析后重新按匿名协议自定义帧镜像下发] → [实现: 备份到`记忆迁移/codex记忆迁移/backups/20260719-205628-position-test-f6/`; 固件新增`UPLINK_F6_CMD=0xF6`, DATA长37B=`cur/tar(6*s32 cm)+flags+rx_cnt+len_err_cnt+checksum_err_cnt`, 总帧43B; `ANO_DT_LX.c`增加0xF6打包/发送入口, `Uplink_Cmd_Tick()`在收到新合法0xF5后按5tick节流镜像,约10Hz,不接PID/0x41; GUI新增`RpiPositionMirrorSample`和`decode_rpi_position_mirror()`, 新增`gui/position_test/position_test_window.py`, 主菜单`功能→位置测试`懒加载, 与数据帧监视/IMU测试台互斥, 页面只在激活时解析0xF6并刷新; 当前仅“实时数据”页可用, 坐标标定/稳定性/轨迹回放为下一阶段占位; 文档`数据帧.md`和`树莓派飞控对接文档.md`同步0xF6定义] → [验证: `.venv-linux/bin/python -m py_compile`通过; 合成0xF6 payload离线解码校验通过(DATA=37B, cur=(0,0,80), tar=(100,0,80), flags=0x03); Qt offscreen生成`artifacts/gui_position_test/position_test_realtime.png`并目视确认字段显示正确; `LINGXIAO_GUI_FAKE=1`主窗口离线切到位置测试生成`artifacts/gui_position_test/main_position_test_entry.png`; `bash scripts/build.sh`固件构建通过, 输出`build-gcc/ANO_LX.hex/bin/elf`] → [教训: 先分清链路所有权再决定协议, GUI要看的是“STM32实际解析结果”而非树莓派本地日志; 调试镜像必须限频且只在页面打开时GUI侧计算; 截图验证发现了首帧未立即刷新和浅色主题表格可读性问题, 修为`on_sample()`立即刷新并固定表格行底色; ⚠️ 安全影响: 本阶段只新增调试下行镜像和GUI显示, 不写PID、不改rt_tar、不触发0x41、不改变飞行输出。主线状态仍停在树莓派真实SLAM cur测试中, 用户回传后再恢复阶段闸门]


## 外部传感器资料库 (2026-07-19)

[2026-07-19 匿名光流V4官方资料本地化] [用户要求联网抓取匿名光流官方手册/原理/使用流程并写入记忆] → [本地此前只有凌霄/协议手册，缺少光流模块自身的官方字段和工作流程，容易把0x51 MODE语义、0x34测距语义和当前0x33转发链路混为一谈] → [从匿名科创官方Wiki抓取《匿名光流v4.0》HTML/正文/9张图片到`用户手册/匿名光流/`；抓取官方《资料下载汇总》HTML/正文并保留V4固件/手册百度网盘入口；新增`project_docs/sensors/ano-optical-flow-v4.md`记录核心结论：光流必须融合加速度/角速度/高度才可解耦，MODE0=原始像素速度，MODE1=地面速度观测但噪声大，MODE2含DX_FIX/DY_FIX更适合积分；当前工程只用MODE1的`of1_dx/of1_dy`转0x33，MODE2已解析但未用于0x33；同时标注光流Wiki的0x34字段与凌霄V7通用测距0x34语义存在差异，后续改转发前必须复查接收方协议] → [教训: 外部传感器必须先看“传感器自身手册+凌霄接收协议+当前源码”三者交集，不能凭同属匿名生态就假设字段完全同义；⚠️ 安全影响: 本轮未改飞控代码，但后续定点/高度/速度转发修改若误解MODE或0x34方向字段，会直接影响IMU传感器有效性和定点安全]

[2026-07-19 姿态/位置基准语义确认] [用户追问姿态角/四元数零度基准、是否可发命令修改基准、0x08位置偏移为何出现1386cm/375cm] → [协议手册定义0x03为ROL/PIT/YAW*100、0x04为V0~V3*10000、0x08为POS_X/POS_Y S32且单位cm“相比起飞点的位置偏移量”；源码仅把0x08 DATA按小端s32拷贝到`fc_pos`，GUI也按`<ii`显示cm；截图原始DATA `6A 05 00 00 77 01 00 00`解析确为X=1386cm、Y=375cm，不是GUI比例换算错误] → [结论: 姿态零点由凌霄IMU闭源融合/校准/启动对准决定；可用CMD触发GYRO校准、快速水平校准、MAG校准、加速度六面校准和姿态融合复位对准，但不应把它当作建图原点任意重写接口；建图/定位应在上层软件记录任务开始时的`yaw0`和`pos0`，之后用差分/旋转得到地图坐标；0x08原始大数只能说明IMU内部位置状态/起飞点基准与当前建图基准不一致或融合漂移，不能直接当室内真实位移闭环] → [教训: 凌霄IMU输出基准属于闭源融合状态，STM32/GUI只能按协议触发校准和解析输出；室内建图必须建立软件坐标原点，避免把0x08 raw值误当绝对房间坐标；⚠️ 安全影响: 飞行中不要频繁重置姿态/位置基准，校准应在上锁、水平、静止、远离磁干扰时完成]

[2026-07-19 0x04四元数姿态符号对齐] [用户发现GUI数据帧监视姿态与树莓派解析姿态大小相等但方向相反，要求判断哪边错] → [对比GUI、树莓派脚本和历史JSONL抓包，发现树莓派`groundTest/ano_rpi_driver.py`按常规右手系公式直接把0x04四元数转欧拉，得到的pitch/yaw与凌霄IMU直接输出的0x03欧拉角符号相反；GUI通用解码器此前只把yaw翻号，pitch仍与0x03相反。用历史抓包近邻对账：不翻号时yaw平均误差约50°、pitch约5°；翻pitch+yaw后roll/pitch/yaw平均误差约0.10°/0.10°/0.03°] → [以凌霄0x03官方直出欧拉角为显示/上层语义基准，修改`gui/services/telemetry_decoder.py`让0x04解码统一翻转pitch/yaw；`gui/widgets/frame_monitor_dock.py`的0x04行复用统一解码器并显示Roll/Pitch/Yaw，同时保留原始V0~V3；同步修正`groundTest/ano_rpi_driver.py`和`groundTest/Raspberry_Pi_IMU_Driver_Guide.md`中的树莓派0x04参考解算公式] → [教训: 0x04四元数不能只套通用公式就直接当凌霄欧拉角，必须与0x03同源欧拉帧对账；后续任何树莓派/GUI/SLAM姿态解析都应以“0x04常规公式后pitch/yaw翻号，roll不翻”为当前项目约定；⚠️ 安全影响: 本次只修上位机/树莓派参考解析，不改STM32发送给IMU的控制链路]

[2026-07-19 IMU总览3D长方体Roll显示方向修复] [用户指出GUI IMU功能总览中的3D长方体roll视觉方向与现实刚好相反] → [姿态数值解析已与0x03/0x04对齐，问题在`gui/imu_test/widgets/attitude_3d_panel.py`显示层：pyqtgraph右手系绕+X正向旋转与实机横滚视觉方向相反，旧代码`m.rotate(roll,1,0,0)`导致长方体roll反向；轴标签矩阵`_rotation_matrix()`也沿用同一错误符号] → [只修改IMU总览3D渲染变换：`_apply_attitude()`改为`Rx(-roll)`，`_rotation_matrix()`同步用`r=math.radians(-roll)`，数值栏Roll/Pitch/Yaw和解码器不变；验证compileall通过，矩阵检查roll+30时Y轴tip z=-0.5方向已反转，`python -m gui.test._smoke_phase_p2`全通过] → [教训: 姿态“数值语义”和3D“视觉旋转方向”必须分层处理，不能为了修视觉去改0x03/0x04解码；后续若用户反馈pitch/yaw视觉方向，也应先判断是渲染坐标系还是数据解析；⚠️ 安全影响: 仅改GUI显示层，不影响STM32固件、IMU输入帧或树莓派姿态数值]


## Codex 记忆迁移清理 (2026-07-18)

[2026-07-18 Codex迁移包混入非飞控内容] [用户指出迁移包里保留了非飞控项目的混合记忆, 会误导Codex] → [迁移时把含其他项目片段的用户级混合记忆放进迁移包, 虽然标注不要导入, 但对目标迁移包来说只要存在就可能被误读] → [删除混合来源目录、历史迁移目录和所有`.bak`备份; `review.md`/`AGENTS.md`去掉其他项目具体名称和旧目录引用; 重新grep确认迁移包内无非飞控项目关键词, 核心飞控repo记忆8个和drone skill 6个保留完整] → [教训: 迁移给另一个AI的包必须“物理上不包含”非目标项目材料, 不能只靠文字标注“不要读”; 关键词审查必须覆盖说明文档本身]

[2026-07-18 数据帧.md 0xF3总长残留15B错误] → [早期阶段2b文档把0xF3总长写成15B, 但2026-05-26实链路记录已确认0xF3单帧总长=4B帧头区+12B数据+2B校验=18B] → [将`project_docs/数据帧.md`的0xF3总长改为18B并补公式] → [教训: 发现项目文档与已验证dev-log冲突时, 必须同步修正文档, 不能只依赖历史纠错记录]

[2026-07-18 dev.md后续扩展帧号与现有私有帧冲突] → [`project_docs/dev.md`旧扩展建议仍写`0xF3 SAVE`/`0xF4 LOAD`和`0xF5 READ`, 但0xF3已用于三轴目标同帧写入, 0xF5已在树莓派位置帧规划中使用] → [改为要求后续重新分配未占用私有帧ID, 并明确不得复用0xF1/0xF2/0xF3且需核对0xF5规划] → [教训: 预留帧号会随项目演进变成已占用帧, 文档中的“后续扩展点”也必须参与冲突检查]

[2026-07-18 Codex完整继承流程未显式固化] → [仅靠当前会话读完迁移包不能保证后续新会话自动恢复全部开发经验, 需要把任务路由、专项文档、skill调用和审计状态写入仓库级规则] → [完整读取`CODEX_FIRST_PROMPT.md`清单、GUI/IMU/path-viz/groundTest/验收/VSCode配置/6个drone skill; 更新`AGENTS.md`任务固定自用流程和任务类型自动路由; 更新`CODEX_MEMORY_INDEX.md`和`CODEX_SESSION_START.md`; 新增`CODEX_INHERITANCE_AUDIT.md`; 自检入口文件齐全、无`.bak`、repo记忆8个、drone skill 6个] → [教训: “继承记忆”必须落成可重复读取的项目规则和审计文件, 不能只存在于一次聊天上下文]


---
## GUI 三项修复 + 位置测试规划 (2026-07-17)

[2026-07-17 数据帧监视单位换算修复] [用户发现0x02帧温度显示415/492℃、气压高126米明显错误] → [抓真机串口数据:0x02温度raw=4880稳定→协议写×10得488℃错,实测应×0.01得48.8℃;ALT_BAR raw≈12907波动±8cm/6s→是绝对气压海拔(本地海拔~129m)不是相对高度(相对高度在0x05);又实测0x01静止加速度合成模=1363.4 LSB=1g,原±16g因子(9.80665*16/32768)给出0.666g错误] → [`frame_monitor_dock.py`:①加速度改实测标定`_ACC_LSB_PER_G=1363.4`,`_ACC_LSB_TO_G=1/1363.4`,`_ACC_LSB_TO_MS2=9.80665/1363.4`;②`_fmt_mag_baro`温度`tmp/10`→`tmp/100`,气压改标注"气压海拔={alt_bar/100:.1f}m(绝对/海平面基准)"] → 验证:离线offscreen截图气压海拔=129.23m/温度=47.7℃/Az=+1.00g全对 → [教训:①单位换算别信协议文档标称,抓真机静止数据反推最可靠;②"气压高"是绝对海拔不是相对高度;③抓串口数据要临时kill占用串口的GUI,但用户正在测试时严禁kill——offscreen离线渲染不需串口不打扰运行中GUI]

[2026-07-17 IMU概览面板加三轴速度] [用户要在实时总览左侧数值模块(加速度/角速度/欧拉角)后追加三轴速度显示,界面可滚动] → [`imu_value_panel.py`:_ROWS在shock后加("vx","速度 Vx","cm/s")等三行;__init__加`self._last_vel=None`;加`@Slot(object) on_velocity(sample)`;clear()清速度;_refresh()写`self._set("vx",f"{v.vx_cmps:+.1f}","")`(字段是vx_cmps不是vx!);⚠️关键修复:imu_test_window原来只连了_vel_panel/_pos_panel,漏连`_value_panel.on_velocity`→值面板永远收不到0x07→速度行不显示。补`self._hub.velocity.connect(self._value_panel.on_velocity)`] → 验证离线渲染vx=+12.0/vy=-5.0/vz=+2.0 cm/s正确 → [教训:①加了UI行还必须确认信号真的连到该widget,imu_test_window用_value_panel直连(非overview_panel);②VelocitySample字段是vx_cmps/vy_cmps/vz_cmps;③之前summary说Task3完成是假的,行和连接都没落地,必须看真机截图验证]

[2026-07-17 串口连接栏全局化] [用户要连接栏从主页内部提到最外层顶部常驻,跨所有功能页可见,排版风格不变,别改坏其它] → [`main.py`:①从central的QVBoxLayout(margins0)移除`layout.addWidget(self._connection_bar)`;②`self.setCentralWidget(self._central_stack)`改为包一层_outer(QVBoxLayout margins0 spacing0)含[connection_bar, central_stack],`setCentralWidget(_outer)`。connection_bar对象/信号不变,仅换挂载点] → py_compile通过。改动需用户重启GUI才可见 → [教训:连接栏原本在central(stack页0)内,提到包裹stack的外层容器即可跨页常驻,margins都设0保证外观零变化]

📋 Task4 已完成:位置测试功能(2026-07-17)。用户拍板:方案A(策略模式+注册表)/多算法并行对比/机体系前X-左Y-上Z/CSV全列。文件:`gui/imu_test/position/estimator_base.py`(抽象基类PositionEstimator:key/label/input_kind(POSITION/VELOCITY/ACCEL)/color,reset()/update(t,x,y,z)->位移cm,params_spec()声明可调参自动生成SpinBox;@register+_REGISTRY;create_all());`estimators.py`(3算法:DirectPositionEstimator 0x32转发/VelocityIntegrator 0x07梯形积分+死区/AccelDoubleIntegrator 0x01二次积分+bias_n帧零偏估计+vel_leak泄漏抑漂);`widgets/position_test_panel.py`(三轴X/Y/Z各独立图不合并,每图下方对齐多算法实时位移标签,QScrollArea可滚,装填/停止/清除/导出CSV,全局判据保持时长0=手动+稳定窗口+容差,各算法参数SpinBox,on_velocity/on_imu_raw/on_position按input_kind路由);data_hub加position信号(0x32)+CMD_GEN_POS;imu_test_window加"位置测试"Tab+_pos_panel+连三信号。验证:速度积分10cm/s×1s=10cm精确;离线渲染direct_pos+79/vel+15.8/acc+0(前50帧估零偏)全对。教训:input_kind声明输入类型让面板自动路由;params_spec声明式参数UI自动生成,加算法零UI改动;二次积分静止必发散靠零偏估计+速度泄漏抑漂。

[2026-07-17 位置测试面板bug修复] [用户报"X图一直不更新、一堆功能没实现,你没看图验证"] → [真实事件循环+模拟运动测试发现3个真bug:①pyqtgraph自动SI前缀→小位移时纵轴显示"mcm"(毫厘米)误导;②`_settle_win`/`_settle_tol`声明了但从未使用→稳定检测功能根本没实现;③默认`_hold_dur=5.0`→装填5秒后自动停止记录,图冻结,用户以为"不更新"] → [position_test_panel.py:①_build_axis_block每个plot加`getAxis("left").enableAutoSIPrefix(False)`+bottom同样;②默认`_hold_dur=0.0`(手动模式,不自动停);③实现`_is_stable()`:所有有数据算法在末尾settle_win秒窗口内三轴位移极差<settle_tol判稳,_feed里实时更新相位标签"记录中·运动中/已稳定",hold_dur>0才时间阈值自动结算] → 验证:真实QTimer事件循环喂0x07模拟前向运动(vx sin到40cm/s再停),X图green速度积分曲线S形升到+79.9cm正确更新,Y因死区噪声保持0,单位显示"cm"不再mcm,稳定检测实时"运动中"生效 → [教训:①声明的参数必须真的接入逻辑,否则就是假功能;②默认自动停止时长会让图"冻结",默认应手动;③pyqtgraph setLabel带units会自动加SI前缀,位移这种小值要enableAutoSIPrefix(False);④离线offscreen+真实QTimer事件循环能完整验证动态刷新,必须看截图不能只跑通] ⚠️真机注意:direct_pos(0x32)需外部位置传感器(光流/激光/UWB)发0x32才有数据,裸IMU无0x32该曲线恒平;vel_integral需0x07速度帧;acc_double_integral受data_hub加速度标定错误(±4g假设vs实测1g=1363.4LSB)影响,幅值不准。

[2026-07-17 位置测试面板重构:单轴切换+惰性门控+曲线显隐] [用户要:①三轴不再挤一个窗口,顶部下拉选X/Y/Z只显示一个轴;②惰性:切到别的Tab就停止该面板一切计算,不占后台线程;③每条曲线(直接位置/速度积分/加速度积分)加复选框可显隐,默认全开] → [position_test_panel.py:①`_build_ui`用QStackedWidget`_axis_stack`装3个轴块+`_build_view_row`(QComboBox`_axis_combo`选轴接`_on_axis_changed`切stack;每算法一个QCheckBox存`_algo_vis`接`_apply_visibility`);②`__init__`加`_cur_axis="x"`/`_active=False`/`_algo_vis`/`_disp_cells`,定时器不再__init__自启;③`showEvent`置_active=True+timer.start,`hideEvent`置False+timer.stop(QTabWidget切页自动触发hideEvent);④`_feed`开头`if not self._active:return`+只刷当前轴标签`d_cur={"x":dx...}[cur]`;⑤`_refresh_plots`开头不需active判断(timer停就不调),只画`self._cur_axis`且`if not _algo_vis[key].isChecked():continue`;⑥`_apply_visibility`同时setVisible曲线+底部cell标签容器] → 验证:真实QTimer事件循环+offscreen,show后active=True/timer活;喂0x07模拟前向运动X图速度积分S形到+79.92cm;取消direct/acc复选框→direct曲线isVisible=False+底部只剩速度积分标签;`_axis_combo.setCurrentIndex(1)`切Y轴标题变"Y轴位移(左+)";hide()后active=False/timer停,再喂50帧buffer保持174不变(后台零计算)。三张截图/tmp/pos_x_all|velonly|y.png全部符合 → [教训:①QTabWidget只显示当前页,非当前页自动触发hideEvent,是惰性门控的天然钩子;②惰性门控要三管齐下:_feed入口拦截+timer停+showEvent/hideEvent切_active;③复选框显隐要同时管曲线setVisible和底部标签cell的setVisible才视觉一致;④切轴/切复选框时面板正可见所以_refresh_plots正常执行]

[2026-07-17 统一加速度标定:修正data_hub→IMU概览+位置测试acc积分曲线幅值] [用户问"±4g假设 vs 实测1g=1363.4 LSB不一致"的影响链条;确认树莓派不受影响后要求统一] → [data_hub.py:`DEFAULT_ACC_SCALE`从0.004788(±16g假设,协议手册标称)改为`9.80665/1363.4`≈0.007193(实测标定,2026-07-17 frame_monitor真机静止Az=1363.4 LSB≈1g,反推固件实配约±24g量程);添加注释说明协议手册与固件实际量程不符,以实测为准] → 验证:Az=1363 LSB×新因子=9.80 m/s²(误差0.003),旧因子=6.53 m/s²(偏小50%) → 影响:①imu概览面板加速度显示从偏小50%变正确;②位置测试·加速度二次积分曲线幅值从缩水变正常,可与速度积分对比。**不影响**:①0x01帧字节不变(依然发LSB原始值);②树莓派等外部程序直连飞控串口,收字节不变,各自用各自的转换因子(GUI改的只在GUI内生效);③frame_monitor已有独立正确标定不受影响 → [教训:①满量程配置以实测为准,协议手册标称值可能过时;②data_hub是GUI内部转换,不改协议字节流,外部程序零影响;③链路独立性:飞控→串口字节流(LSB)→各接收方自己转物理量,互不干扰]

[2026-07-17 修正加速度二次积分死区:2分钟6031样本统计] [用户报0.06死区仍然漂移+18cm,要求采集2分钟大样本量做正态分布分析] → [采集2分钟静止数据(6031样本~50Hz):X轴峰值0.079/Y轴0.072/Z轴0.053 m/s²,99.9%分位0.072,观测最大值0.079(之前3秒177样本只测到0.043,样本不足!);原deadband=0.06<最大值0.079→长时间必漏] → [estimators.py `AccelDoubleIntegrator.params_spec`:deadband从0.06改**0.12**(最大值0.079×1.5,非常保守);vel_leak/bias_n保持0.04/100不变] → 验证:①真实静止噪声(峰值0.079)×600帧→0.00cm(完全滤除);②0.5m/s²运动→21.12cm(保留21%);③边界0.15m/s²→6.34cm(能检测) → [教训:①短时采样(3秒)严重低估噪声峰值,必须长时间(≥2分钟)采集;②IMU噪声非稳态,峰值会随时间增大(3秒0.043→2分钟0.079);③死区设为长时观测最大值×1.5才保险;④正态分布假设对IMU不适用,用百分位数更可靠]

[2026-07-18 0x33光流速度帧从未上报:固件逻辑bug] [用户发现0x09风速Wx/Wy有数据(=0)但0x33通用速度(光流)一直"等待数据",质疑是GUI显示错误还是真的没收到] → [排查:`frame_monitor_dock.py`的0x33显示逻辑+`FrameParser`解析器均正确;回查`LX_FC_EXT_Sensor.c`的`General_Velocity_Data_Handle()`:XY速度更新时(line41-48)只打包`ext_sens.gen_vel.st_data.hca_velocity_cmps[0/1]=ano_of.of1_dx/dy`,**未触发发送**;发送触发器`dt.fun[0x33].WTS=1`只在line58**高度数据更新时**设置(`of_alt_update_cnt!=ano_of.alt_update_cnt`)。光流模块若无高度传感器或高度不更新→`of_alt_update_cnt`永不变→0x33帧永不发送,即使XY速度已打包入buffer] → [LX_FC_EXT_Sensor.c:把line52-60的高度更新分支注释掉,把`ext_sens.gen_vel.st_data.hca_velocity_cmps[2]=0x8000`+`dt.fun[0x33].WTS=1`+`dT_ms=0`三行上移到line48(XY速度更新分支末尾),确保XY更新即发送;注释说明"原代码只在高度更新时触发0x33发送,导致无高度传感器时XY速度永不上报"] → 验证:编译通过。待用户重新烧录固件后确认0x33帧能收到 → [教训:①发送触发器(WTS)必须紧跟**主数据源更新**放置,不能分离到别的条件分支;②光流模块功能分离:XY速度≠高度,触发逻辑不该耦合;③固件bug排查优先级:协议解析器→GUI显示逻辑→固件打包逻辑,越靠近数据源越可能是根因;④"A功能有数据但B功能没数据"且AB来自同一传感器→很可能是打包/发送条件写错而非传感器本身坏] ⚠️安全影响:修复后0x33帧发送频率=光流XY更新频率(~100Hz),不影响飞控姿态/控制回路,仅增加串口流量;GUI新增光流速度积分曲线和停止抑制功能供用户对比0x07飞控融合速度

[2026-07-19 0x33光流速度触发逻辑实际落地] [用户追问0x51 MODE=0/1/2如何转发及最合理修复方式] → [确认当前工程只把0x51 MODE=1的`of1_dx/of1_dy`作为光流速度源转成0x33；MODE=0原始像素量和MODE=2惯导融合量只解析保存、不参与转发；旧代码仍把0x33发送触发绑在高度`alt_update_cnt`上] → [`FcSrc/LX_FC_EXT_Sensor.c::General_Velocity_Data_Handle()`改为:速度更新`of_update_cnt`变化时更新X/Y、Z轴置0x8000无效、立即置`dt.fun[0x33].WTS=1`并复位`dT_ms`;`General_Distance_Data_Handle()`继续只负责0x34测距，不改0x34逻辑、不改0x51解析、不改凌霄IMU协议] → [验证:`bash ./scripts/build.sh`通过，生成`build-gcc/ANO_LX.bin/.elf/.hex`;仅有既有pragma/static声明警告] → [教训:0x33通用速度的触发条件必须跟速度主数据源一致；0x34测距和0x33速度是两个独立外设输入帧，不能因同属光流/激光模块就耦合发送条件]

---
## GUI 主界面通用数据面板 — 阶段C 完成 (2026-07-13)

[2026-07-13 阶段C 主界面通用数据面板] [用户要求主界面(非IMU测试)显示常用数据：飞行模式+锁定、通用速度/高度、传感器工作状态(通用位置0x32/通用速度0x33/测距0x34)，无数据显示NO，有数据显示值+单位；且通用数据来自专用外部传感器(光流/激光)非IMU推算] → [查匿名通信协议V7.pdf(用pdfplumber装到.venv-linux)确认权威帧定义：0x06飞控运行模式`<BBBBB`=MODE,LOCKED(1解锁/0锁定),CID,CMD0,CMD1；0x0D电压电流`<HH`(×100)；0x0E外接模块工作状态`<BBBB`=STA_G_VEL,STA_G_POS,STA_GPS,STA_ALT_ADD(值0无数据/1不可用/2正常/3良好);0x05高度`<iiB`;0x07速度`<hhh`;0x32通用位置`<iii`cm(无效0x80000000);0x33通用速度(光流)`<hhh`cm/s(无效0x8000);0x34通用测距`<BHI`=方向(0水平/1垂直),角度,距离cm(无效0xFFFFFFFF)。飞行模式映射(查User_Task.c确认):0自稳/1定高/2定点/3程控] → [新建 `gui/widgets/flight_data_dock.py`(FlightDataDock(QDockWidget) title"飞行数据"，3组QGroupBox:①飞行状态[模式/锁定/电压/电流]②飞控融合估计[融合高度/附加测高/速度XYZ]③通用外部传感器[通用位置+状态/通用速度(光流)+状态/通用测距(激光)+状态]，_ValueLabel带set_no/set_value/check_stale，_STALE_S=2.5，QTimer 500ms检查过期)；`telemetry_models.py`加6个frozen dataclass；`telemetry_decoder.py`加6解码器(含无效值常量)；`telemetry_bus.py`加6信号+feed_frame的0x06/0x0D/0x0E/0x32/0x33/0x34分支；`main.py`加FlightDataDock+addDockWidget(Right)+setVisible(False)+连8信号+功能菜单"飞行数据面板"QAction；`config_service.py`加`features.flight_data:False`] → 验证：6解码器终端单测输出全部正确；灌真实字节帧走TelemetryBus→Dock截图三组渲染+着色+NO+无效轴"—"正确；完整MainWindow(FAKE)截图Dock停靠右侧集成无崩溃。get_errors全清。 → [教训：① 传感器工作状态权威来源是0x0E帧而非仅判断0x32/33/34是否收到——结合两者；② 帧字段定义以官方PDF手册为准，pdfplumber提取比猜测可靠；③ 飞行模式/命令字节查固件User_Task.c作ground truth；④ Dock遵循numeric_panel_dock.py既有模式保持一致。] **阶段C完成✅  阶段D完成✅**

[2026-07-13 线速度观测测试面板] [用户在 IMU 测试台内需要对 vx/vy/vz 进行类似姿态轴测试的稳定性观测，发现：vz 静止永不为 0（±2cm/s 噪声），vx/vy 停止后出现反向脉冲（ZUPT 残差）] → [① `data_hub.py` 加入 `decode_velocity` 导入 + `CMD_VEL=0x07` 常量 + `velocity = Signal(object)` 信号 + on_frame 分支解码 0x07 帧；② 新建 `gui/imu_test/widgets/velocity_test_panel.py`：三轴曲线（pyqtgraph）+ 装填/停止/重置/导出 CSV 四按钮 + 统计指标表（最大/最小/均值/标准差/峰峰值）+ 状态/帧数标签；③ `imu_test_window.py` 新增 "velocity"/"线速度观测" Tab，创建 `_vel_panel = VelocityTestPanel`，连接 `hub.velocity` 信号] → 验证：合成 vz 噪声(±2cm/s) + vy 正向运动(~49cm/s) + 停止反向脉冲(-5cm/s) 131帧注入，截图确认三轴曲线/统计全部正确，get_errors 全清。 → [教训：① 0x07 帧在 telemetry_decoder 里已有 decode_velocity，data_hub 原先只解 0x01/0x04 未接入 0x07，加 Signal 和 CMD 常量即可复用；② 速度测试不需要状态机（无"旋转/停手"等触发条件），直接装填→记录→停止三态足够，统计信息批量在每10帧算一次避免每帧 np 开销。]

[2026-07-13 阶段D 性能优化 + IMU单位转换] [用户报"加了数据帧监视后原来数据一下有一下没有、卡死"，且IMU加速度/角速度显示LSB不是日常单位；强调Windows匿名上位机显示更多数据都不卡=代码没优化，要求"点开功能才计算、优化线程调度、别把CPU耗满"] → [根因：①`frame_monitor_dock._FrameRow`每行2个常驻QTimer(闪烁+Hz)×25行=50个定时器空转，`on_frame`在100Hz下每帧`_header.setStyleSheet(闪绿)`触发整块QSS repolish(Qt昂贵操作)+setText，即使Dock隐藏也在跑；②`telemetry_bus.feed_frame`对0x03/0x04姿态帧(~100Hz)每帧`_tracker.on_attitude`后台积分，即使路径可视化没开(注释写"后台积分常驻"就是病根)；③`main._on_frame`每帧`datetime.now().strftime`+setText状态栏+构造debug日志f-string] → [解决：①重写`frame_monitor_dock.py`为"惰性+定频"：`FrameMonitorWidget`加`showEvent/hideEvent`控`_active`(在QStackedWidget里非当前页=隐藏→`on_frame`直接return零算力)；`on_frame`只`row.note_frame(fr)`缓存最新帧(O(1)不碰UI)；单个共享`_refresh_timer`(66ms≈15Hz)统一`render(now)`所有行，UI刷新率与数据速率彻底解耦；活动灯用单个`_dot`QLabel(●绿/灰)只在状态翻转时setStyleSheet(替代每帧repolish整块header);Hz改滑动1s窗口计数;折叠行不构建详情字符串(仅展开行`_fill_detail`);删掉deque import。②`telemetry_bus.py`把0x03/04/05/07的`_tracker.on_*`+`_maybe_emit_path`用`if self._render_enabled:`包住(仅路径可视化开启时才积分),`*_updated.emit`仍常发(喂飞行数据面板)。③`main._on_frame`状态栏"最后接收"节流到1Hz(`_last_rx_ui_ts`),删非A0帧的逐帧debug日志。IMU单位:frame_monitor加常量`_ACC_LSB_TO_G=16/32768`(±16g量程)`_ACC_LSB_TO_MS2=16*9.80665/32768≈0.004788``_GYR_LSB_TO_DPS=2000/32768≈0.06104`(±2000dps),`_fmt_imu`摘要显示g+°/s,详情加速度显示g和m/s²、角速度°/s] → 验证:合成帧~900Hz推流截图确认Az=8192LSB→+4.000g(+39.227m/s²)、Gz=300LSB→+18.31°/s正确;15Hz UI平稳无卡顿;活动灯绿/灰翻转正确。get_errors仅PySide6误报。 → [教训:①**反模式:高频信号槽里直接改UI**——100Hz帧率下逐帧setText/setStyleSheet会打爆主线程,正解是"槽里只缓存最新值+定时器定频刷UI"把刷新率与数据率解耦(匿名上位机就是这么做的);②**Qt的setStyleSheet触发整个widget子树样式repolish**,是重量级操作,绝不能每帧调,活动指示用独立小label且只在状态翻转时改;③**per-widget QTimer会累积**(25行×2定时器),能用1个共享定时器就别N个;④后台积分/解码要按"功能是否打开"gate,别信"常驻"的旧注释;⑤QStackedWidget非当前页自动触发hideEvent,是天然的惰性开关点。] **阶段D性能优化完成✅**

[2026-07-13 姿态轴测试面板泛化+判据可调] [用户问yaw测试"是不是固定三秒?怎么结束的?为什么不能手动调?感觉好快"+要求"加roll和pitch测试和yaw一样"] → [结束机制解释:不是固定3s,是状态机(装填→等待旋转→旋转中(gyr阈值)→停手稳定中→完成),停手后角度在SETTLE_WIN_S=1s滑窗内极差<SETTLE_TOL_DEG=0.3°即结算,或SETTLE_TIMEOUT_S=8s超时;"好快"根因=这些判据是写死模块常量UI没法调,回弹小时1s内极差就<0.3°秒结束] → [泛化`gui/imu_test/widgets/yaw_test_panel.py`:类`YawTestPanel`加`axis="yaw"/"roll"/"pitch"`参数+`_AXIS_CFG`(name/ang属性/gyr属性/颜色):yaw取yaw_deg+gyr_z,roll取roll_deg+gyr_x,pitch取pitch_deg+gyr_y(attitude sample有roll_deg/pitch_deg/yaw_deg/ts,ImuRawSample有gyr_x/y/z单位rad/s→math.degrees转°/s);去环绕连续化逻辑三轴通用(pitch±90不环绕也无害);模块常量改DEF_前缀默认值+实例变量`_rotate_thresh/_stop_hold/_settle_win_s/_settle_tol/_settle_timeout`;`_build_ui`加QGroupBox"判据参数(可调)"含5个QDoubleSpinBox(valueChanged→setattr实例变量)+新增"手动结算"按钮(`_on_manual_settle`:PH_ROT时把当前当峰值+停手时刻立即结算,PH_SETTLE时用窗口均值结算);状态机`_step`所有常量换实例变量;标题/标签/日志/CSV文件名用self._axis_name;val_lbl颜色用轴色。`imu_test_window.py`:_TABS加("roll","Roll跟随")("pitch","Pitch跟随"),建`_roll_panel=YawTestPanel(self,axis="roll")`+`_pitch_panel`,`_build_tab`加roll/pitch分支,hub的imu_raw+attitude信号各connect三个panel] → 验证:合成旋转0→30°→回弹22°注入roll面板截图确认三页签齐全、曲线+旋转区高亮、峰值+30.00/当前+22.00正确、5参数spinbox+手动结算按钮到位。get_errors全清。 → [教训:①类名保留YawTestPanel加axis参数默认"yaw"→window原`YawTestPanel(self)`零改动仍工作,新增只多传axis,最小侵入泛化;②三轴角速度分量映射:横滚gyr_x/俯仰gyr_y/偏航gyr_z(机体系NED);③判据类参数别写死模块常量,做成实例变量+UI spinbox用户才能现场调,"感觉太快/太慢"这类主观反馈=参数该暴露;④getattr(sample,self._ang_attr)按轴名动态取字段,比if-else三分支干净。] **阶段D三轴测试完成✅**

[2026-07-13 GitHub上传清理 / .gitignore] [用户要把整个`ANO_LX_FC`上传到GitHub,强调不要把编译垃圾/本机文件带上,但也不能删过头导致别的电脑clone后不完整] → [排查发现仓库根本没有`.gitignore`,且历史上已经把大量本机产物纳入跟踪: `.venv-linux` 单独就 14112 个文件,另外还有 `build-gcc/`、Keil `.uvguix.*`、`Project*/build|Objects|Listings|DebugConfig`、`gui/logs/*.txt`、`logs/*.log` 等] → [新增仓库根`.gitignore`: 仅忽略 OS/编辑器本地目录(`.vscode/.idea/.agents`)、Python venv/缓存(`.venv-linux`,`__pycache__`,`*.pyc`,`.pytest_cache`)、日志与临时输出(`logs/*.log`,`gui/logs/*.txt`,`out.txt`,`groundTest/out.txt`,`extracted_text.txt`)、CMake/Ninja/GCC 产物(`build-gcc/`,`CMakeFiles/`,`*.elf/*.bin/*.hex/*.map`等)、Keil/J-Link 用户态文件(`*.uvguix.*`,`Project*/build`,`Objects`,`Listings`,`DebugConfig`,`JLinkLog*.txt`,`JLinkSettings.ini`)；明确保留源码、文档、`requirements.txt`、`gui/data/*.jsonl`、`*.uvprojx`、`*.uvoptx`、脚本与手册。随后执行`git ls-files -ci --exclude-standard -z | xargs -0 git rm -r --cached --ignore-unmatch --`把“已被新规则命中但之前已跟踪”的垃圾从索引移除,本地文件保留不删] → 验证: `git ls-files -ci --exclude-standard | wc -l` = 0, 说明所有“该忽略却还被跟踪”的垃圾已清干净; 暂存区现为新增`.gitignore` + 大量索引删除(主要是`.venv-linux`)。 → [教训:①**没有`.gitignore`时先别急着push**, 否则本机venv和编译目录会把仓库污染到无法协作; ②**仅写`.gitignore`不够**——对已经被跟踪的垃圾,必须配合`git rm --cached`; ③忽略规则要“保守删垃圾”: 优先只删编译产物/缓存/用户态文件, 共享配置(`uvprojx/uvoptx`)、文档、样例数据、依赖清单要保留,这样换电脑clone后才能完整复现。]

[2026-07-13 阶段D 数据帧监视面板] [用户要求新增"数据显示"功能：所有数据帧折叠单行→点击展开，有新数据流入时变绿] → [新建 `gui/widgets/frame_monitor_dock.py`(FrameMonitorDock(QDockWidget) title"数据帧监视"，底部Dock；_FrameRow(cmd,name,fmt_fn) 含折叠头部+可展开详情；头部点击切换▶/▼；闪绿=setStyleSheet(rgba(0,200,80,90))+QTimer(800ms)复位；Hz统计=deque(maxlen=200)时间戳+500ms QTimer统计1s内数量；13个已知帧预建行(0x01/02/03/04/05/06/07/0D/0E/0xA0/0x32/0x33/0x34)，未知CMD动态追加；详情区=plain text多行+完整帧hex)；`main.py`加FrameMonitorDock+addDockWidget(Bottom)+setVisible(False)+frame_received常驻订阅+功能菜单"数据帧监视"QAction+_on_frame_monitor_toggled；`config_service.py`加`features.frame_monitor:False`] → 验证：灌入12类已知帧+1个未知帧截图确认折叠/展开/闪绿/摘要/字段明细/完整帧hex全部正确；完整MainWindow集成无崩溃。get_errors全清。 → [教训：① frame_received常驻订阅比延迟连接更简洁，row.update在隐藏时也廉价；② 详情用单个多行QLabel而非动态QFormLayout行增减，避免removeRow/insertRow异步抖动；③ Hz用deque时间戳+fixed-interval QTimer而非update()里每帧重算。]

---
## GUI 路径可视化 — 大阶段全局计划锁定 (2026-05-27)

[2026-05-27] [用户开启路径可视化"新大阶段"需求；担心多轮开发后细节遗失] → [已有 Phase 1 MVP 但缺少"必经验收门 + 串行阶段 + 禁止自主推进"的硬约束] → [研究 Foxglove/QGC/MissionPlanner/Cesium/three.js/pyqtgraph 主流方案；用 askQuestions 锁定 9 项关键决策 D1-D9；写入 `gui/path_viz_master_plan.md`（P0-P7 串行计划+每阶段验收门+禁止动作清单）；摘要锁进 `/memories/repo/path-viz-plan.md`；`.github/copilot-instructions.md` 增加"开发前必读主计划"约束] → [教训：长周期大阶段必须先固化"决策+阶段+验收门"三件套，不能直接写代码；用户原话"如果我不主动说要进行下一个步骤，你就不能私自的做决定"是硬约束。]

**当前阶段：P10 完成 (2026-05-29)，GUI 路径可视化大阶段全部完成 (P0-P10)；2026-05-30 补丁修复 7 项 UI bug**。

[2026-05-30 GUI 7-bug 修复批次] [用户报 7 个 GUI bug：(1) 4 个视图都没有"保留路径秒数"按钮 (2) 单平面视图纸飞机太大、希望默认关闭自动缩放并用鼠标滚轮缩放 (3) 3D 与单平面共开时一个会消失 (4) 日志 0xA0 中文显示为 `��������`乱码 (5) 设置按钮太小+多了"?"占位字符 (6) 日志横向滚动条只有左右点击键无可拖动滑块 (7) HUD 中取消勾选某项(如vx)后整个数值面板消失] → 根因：(1) `_Mini2DSettingsPanel` 缺 trail_seconds spinbox，且 main.py 2D 路径未把 trail_seconds 透到 PathTracker (2) `DEFAULTS_2D["view"]["auto_range"]=True`+`_apply_auto_range` 每帧调 setXRange 覆盖用户滚轮缩放 (3) QMainWindow 未启用 DockNestingEnabled，多 dock 同 area 默认 tabify，OpenGL+raster 混杂时 Qt 隐藏一个 (4) `Frame.color_str` 用 `decode("ascii", errors="replace")`，STM32 端 GBK 中文高字节全变 `?` (5) 两处 QToolButton text 写死 `"? 设置"`（"?" 实为不可显示字符的占位）且未设 minimumSize (6) QTextEdit 默认 QScrollBar 在暗色背景下滑块无独立颜色，与 add-line 同色看不见 (7) `_build_rows` 用 deleteLater 异步删旧 QLabel + 重建 + adjustSize 早于 deleteLater 处理，导致 sizeHint 偶发 0/_reposition 把 overlay 移到不可见位置；apply_settings 末尾 setVisible(True) 不够，缺 show()/raise_()/update() → 解决方案：① `ano_protocol.py:Frame.color_str` decode 改 gbk + utf-8 fallback；② `path_2d_view_widget.py`：DEFAULTS_2D["path"] 加 `"trail_seconds": 20.0`；DEFAULTS_2D["view"]["auto_range"]=False；`_Mini2DSettingsPanel` 路径组新增 "保留秒数" QDoubleSpinBox emit `path.trail_seconds`；`_apply_auto_range` 非自动模式仅 disableAutoRange 不再 setXRange/Y；新增 `_apply_view_range_initial()` 只在 `_build_scene` 启动时 + `view.auto_range` 切换时 + `view.fixed_range_cm` 改时调用一次；3 处 settings 按钮文字 `"? 设置"` → `"设置"` + setMinimumSize(72,26) + QSS padding/font-size；③ `path_visualization_widget.py` 设置按钮同样处理；④ `log_view.py` QTextEdit stylesheet 追加完整 QScrollBar QSS（横/竖滑块 #5A5A5A + min-width/height 30 + hover #7A7A7A + pressed #9A9A9A + add/sub-line #3A3A3A）；⑤ `main.py`：构造函数 `setDockNestingEnabled(True)` + `setDockOptions(AnimatedDocks|AllowNestedDocks|AllowTabbedDocks)`；`_build_feature_docks` 改用 `splitDockWidget(prev, cur, Qt.Horizontal)` 串接 docks（除首个仍用 addDockWidget）；新增 `_on_path_viz_2d_settings_changed(cfg_key, settings)` 替换原 `_config.set` lambda，检测 `path.trail_seconds` 变化 → 写主 `path_viz.settings` + `_apply_path_viz_settings` 推 PathTracker + 同步到 3D widget + 同步到其它 2D widgets；⑥ `hud_overlay_widget.py:_build_rows` 删旧 widget 时增加 `w.hide()`；新加 QLabel 都显式 `show()`；末尾增加 `self._grid.activate(); self._grid_host.updateGeometry(); self._grid_host.adjustSize(); self.updateGeometry(); self.adjustSize()`；`apply_settings` 末尾 visible=True 分支增加 `_grid_host.show(); self.show(); self.raise_(); self.update()` → 验证：P7/P8/P9/P10 smoke 全绿 → [教训：① 协议 0xA0 字符串帧上位机解码 STM32 端中文必须用 GBK 不是 ASCII，源码 ASCII 默认行为是写代码时未考虑中文日志的历史遗留；② pyqtgraph PlotWidget 想要"用户自由缩放"必须确保每帧渲染回调里不再 setXRange/Y，否则鼠标滚轮缩放会被下一帧重置——这是新手常见陷阱；③ QMainWindow 多 dock 默认 tabify 是默认行为，OpenGL widget 作为 Dock 内容时与普通 raster widget 同 area 极易触发"另一个变不可见"问题，必须 setDockNestingEnabled+splitDockWidget 显式拆分；④ QFrame 内含动态构建 QGridLayout 时，takeAt+deleteLater 是异步的，重建后 adjustSize 可能拿到陈旧 sizeHint，必须 `_grid.activate()` 强制立即重算 + 末尾 show()/raise_()/update() 三连；⑤ Qt 暗色主题下 QScrollBar 默认 QSS 滑块与轨道同色看不见，必须显式给 handle 设 background+hover+pressed 颜色 + min-width/min-height 才能拖动；⑥ Mini 设置面板"? 设置"那个 "?" 是历史代码写死的占位字符（开发者本想用图标后忘换），不是编码问题。]

[2026-06-21 GUI README 环境说明补齐] [用户指出 `gui/README.md` 没写清楚怎么进环境] → [原 README 只有 `python gui/main.py` 和单条 `pip install PySide6`，缺少虚拟环境创建/激活、从仓库根目录启动、`python -m gui.main` 推荐入口，以及 2D/3D 可视化真实依赖；同时 `gui/requirements.txt` 也未覆盖 `numpy/pyqtgraph/PyOpenGL`] → [补充 README：Windows PowerShell 下 `python -m venv .venv`、`.\\.venv\\Scripts\\Activate.ps1`、`python -m pip install -r gui\\requirements.txt`、`python -m gui.main`、Fake 模式启动与常见激活失败/缺依赖排查；同步补全 `gui/requirements.txt` 为 `PySide6==6.11.1`、`numpy`、`pyqtgraph>=0.14,<0.15`、`PyOpenGL`] → [教训：文档里写启动命令不等于写了“如何进环境”；凡是 GUI/工具类仓库，README 至少要覆盖 4 件事：在哪个目录执行、怎么建 venv、怎么激活、怎么按依赖文件安装，否则新环境复现一定出错。]

[2026-06-21 GUI 运行环境纠偏] [用户指出之前给出的 `.venv` 激活命令是错的，启动可视化仍报缺库] → [我只看到了仓库里存在 `.venv`，但没先核对历史成功运行路径；而仓库根 [run_gui.bat](run_gui.bat) 已明确写着“锁死用 Python 3.13 启动 GUI（默认 python 是 3.14 缺依赖）”，说明历史上实际可用环境一直是 `C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe`，不是 `.venv`] → [执行 Python 3.13 导入核验 `import PySide6, numpy, pyqtgraph, OpenGL` 通过；修正文档 [gui/README.md](gui/README.md)，明确推荐 `run_gui.bat` 或直接 `C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe -m gui.main`，并标明仓库 `.venv` 是 Python 3.14、当前不可作为 GUI 可视化环境] → [教训：判断“正确环境”不能只凭目录里有没有 `.venv`，必须先查现有启动脚本、已验证测试解释器和历史成功命令；对 GUI/工具链类项目，`run_gui.bat` 这类 launcher 往往比 README 更接近事实。]


[2026-05-29 P10 完成] [用户书面"进入 P10"，要求实现：数据源抽象接口（IPositionSource/IAttitudeSource/IPointCloudSource/IAnchorSource）+ LingxiaoImuSource 适配器、视角预设按钮（俯视/侧视/自由）、轨迹 CSV 导出按钮、主题适配验证、P6#4 长稳压测补回] → 新建 `gui/sources/__init__.py` + `gui/sources/interfaces.py`（# -*- coding: gbk -*- 头）：4 个 ABC 接口 + 3 个 frozen dataclass（PositionReading/AttitudeReading/AnchorPoint）+ LingxiaoImuSource(IPositionSource, IAttitudeSource) 包装 bus.tracker.snapshot()，`as_attitude_source()` 返回内部 _AttView 适配器解决多继承同名 latest() 冲突；扩 `path_visualization_widget.py`：`_SettingsPanel` 顶部 ops 条新增 3 视角按钮（俯/侧/自由）+ 1 CSV 按钮 + 2 新 Signal（viewpoint_preset_requested(str) + export_csv_requested()），PathVisualizationPlaceholder 同名 2 Signal 透传 + 在 3 处 wiring 站点（non-GL fallback + GL splitter + new_panel 替换）全部连接，新增 `_VIEWPOINT_PRESETS` 字典（top: elev=89/azim=0、side: elev=5/azim=90、free: elev=28/azim=45 全 dist=600）+ `_on_viewpoint_preset(name)` 写 self._s["render"] + setCameraPosition + emit settings_changed，新增 `export_path_csv(path)` 写 `t_mono,x_cm,y_cm,z_cm` header + N 行返回点数；扩 `main.py`：viz_widget.export_csv_requested → `_on_path_viz_export_csv()` 用 QFileDialog.getSaveFileName(filter="CSV") + QMessageBox.information 成功提示；主题适配已存在 theme_service.py，无需新增。新建 `gui/test/_smoke_phase_p10.py` 5 case：①interfaces dataclass + Mock IPositionSource 子类（含验证 ABC 不可直接实例化）②LingxiaoImuSource is_available/latest/latest_attitude + as_attitude_source 适配器 ③视角预设 top/side/free 字段更新 + emit 计数 ④export_path_csv 写入 N+1 行 + 空 snap 只写 header ⑤长稳定性微压 200Hz×5s=1000 帧 tracemalloc 内存增长 <5MB（实测 +0.00MB、1700+ fps、peak 0.06MB）。全回归 P2/P4/P5(reset fps=30)/P5.5/P6/P7/P8/P9/P10 全绿。 → [教训：① 接口包 `__init__.py` 必须把 dataclass（PositionReading 等）也 re-export，否则 smoke `from gui.sources import X` 报 ImportError；② 多继承 IPositionSource+IAttitudeSource 时两者都有 latest() 方法名冲突——选择策略：让 LingxiaoImuSource 的 latest() 实现 IPositionSource，另开 latest_attitude() + as_attitude_source() 返回内部 _AttView(IAttitudeSource) 适配器；③ PathSnapshot 字段是 `pos_cm: tuple[float,float,float]` 和 `attitude_deg: tuple` 不是 `x_cm`/`roll_deg` 散字段，写适配器前必读 telemetry_models.py；④ ConfigService 是扁平 dot-key（`d['path_viz.settings']` 一整树），不是嵌套 `d['path_viz']['settings']`——重置 fps 必须用扁平 key 否则 KeyError；⑤ pyqtgraph GLViewWidget.setCameraPosition(distance=, elevation=, azimuth=) 即时生效，elevation=89 接近俯视（90 时 gimbal lock 风险，留 1° 余量）、5° 接近侧视（0° 在某些版本会平面退化）；⑥ tracemalloc 测内存增长比 psutil 更准——单元测试场景下 RSS 噪声太大，tracemalloc.get_traced_memory() 只计 Python 对象分配；⑦ 顶部 ops 条放预设/CSV 比塞进折叠组组合体验更好——用户一眼能看见。] **大阶段完成：GUI 路径可视化 P0-P10 全部 ✅**。

[2026-05-29 P9 完成] [用户书面"开始 p9"，要求实现 HUD 叠加层 + 数字面板 Dock + 3D 世界刻度尺：3D 视图角落浮窗实时显示 vx/vy/vz/vmag/roll/pitch/yaw/x/y/z/h 11 项；可独立开关每项；可拖拽改位置；可调透明度/字号/颜色；可同时通过 QDockWidget 数字面板显示+追踪 min/max；可加 3D 坐标系刻度尺] → 新建 `gui/widgets/_hud_model.py`（HUD_ITEM_KEYS/META/DEFAULTS + extract_hud_values 计算 vmag=sqrt(vx²+vy²+vz²)、h=z + deep_merge_hud）；新建 `gui/widgets/hud_overlay_widget.py`（HudOverlayWidget(QFrame) GL 子浮窗，QSS rgba 半透明，等距字体，11 行 QGridLayout，eventFilter 监听宿主 Resize 重定位 clamp，鼠标拖拽 globalPosition 映射 + 位置/设置变更 signal）；新建 `gui/widgets/numeric_panel_dock.py`（NumericPanelDock(QDockWidget) 三分组 速度/姿态/位置 × 11 行，_Row 记录 min/max，全部清零按钮，按组隐藏空组）；扩 `path_visualization_widget.py`：DEFAULTS 加 hud 子树（items/overlay/ruler），_SettingsPanel 新加 `_build_group_hud`（叠加层外观/显示项目11/世界坐标刻度 三子组），_view 创建后挂 _hud_overlay 子件 + 双向 settings sync，新增 `_rebuild_axis_ruler`（GLLinePlotItem 三轴 minor tick + GLTextItem major label，跟 grid.size_cm 联动），_on_panel_value_changed 新加 hud 分支（路径起 hud.ruler 时重建尺），update_snapshot 末调 overlay.update_snapshot，cleanup_gl 拆 overlay+_ruler_items；扩 `main.py`：实例化 NumericPanelDock 加 Dock + 菜单 toggle，path_updated→update_snapshot，settings_changed↔viz_widget 双向桥；扩 `config_service.py` _DEFAULTS 加 `path_viz.hud.settings` + `features.numeric_panel`。新建 `gui/test/_smoke_phase_p9.py` 6 cases：vmag/h 计算、overlay apply/update、NumericDock min/max+reset+组隐藏、3D widget hud 分支 emit、3D ruler toggle（_gl_ok 不在时跳过）。 P2/P4/P5(reset 后)/P5.5/P6/P7/P8/P9 全绿。 → [教训：① **新 Python 源文件含中文字符串必须开头 `# -*- coding: gbk -*-`**——本仓默认 GBK/CP936，缺声明 Python 用 UTF-8 解析中文 docstring 抛 SyntaxError；② multi_replace 插入多个新方法时容易把相邻方法的局部变量声明吃掉（本次 `_build_group_render` 的 `gb = QGroupBox(...)` 被前次 P9 编辑遗失），插入后必须 read_file 校验前后边界完整；③ HUD 浮窗最干净的实现是 QFrame 直接 setParent(GLViewWidget)，eventFilter 监听 host Resize 重定位——避免重写 GLViewWidget 的 paintGL 干扰 pyqtgraph 内部；④ 拖拽用 mouseMoveEvent + globalPosition().toPoint() 映射到宿主 mapFromGlobal，clamp 在 host.rect() 内防止漂出视野；⑤ pyqtgraph GLViewWidget 在 QT_QPA_PLATFORM=offscreen 下走 fallback，_gl_ok=False，所有需要 GL item 的 smoke case 必须先 `if not w._gl_ok: skip`；⑥ 持久化配置漂移会反复破坏依赖默认值的 P5-6 case_6（fps==30 假设），不是回归——重置 config.json.path_viz.settings.render.fps=30 后即过；⑦ `_on_panel_value_changed` 局部用 `path.split(".")` 得 keys，子句重建条件应用 `path.startswith(...)` 而非误用未定义的 key。]


[2026-05-29 P7 遗留两 bug 修复] [P8 验收时用户报告：① 2D 导航视图纸飞机看不见；② 路径只保留 7s 太短，希望可调] → ① 根因：`Path2DViewWidget._rebuild_icon_item` 用 `self._plot.plot(..., fillLevel=None, fillBrush=brush)`，fillLevel=None 实际不填充，只画 outline；而 outline 默认色 `[40,40,50]` 与 bg `[40,40,50]` 完全同色 → 视觉完全不可见。② 根因：`残留秒数`按钮自 P5 起就存在于 3D widget 面板（1–600s，默认 20s），但 `gui/config.json` 持久化了早期开发期写入的 `trail_seconds=7.0`，覆盖了默认值。→ 修复 ①：`_rebuild_icon_item` 改用 `QGraphicsPolygonItem`（QBrush 真填充 + QPen cosmetic outline），直接 `vb.addItem(self._icon_item)`；`_update_icon` 改用 `QPolygonF.append(QPointF)` + `setPolygon`；`cleanup` 加 `vb.removeItem` 释放（因为不是 PlotItem 子项，plot.clear() 不会清）；DEFAULTS_2D["icon"] outline_color 改 `[10,10,15,255]` + outline_width 1.5→2.0 提高对比度。修复 ②：`gui/config.json` `trail_seconds 7.0 → 60.0`；告诉用户调节入口在 3D 视图 ⚙ 设置 → 路径 → 残留秒数（同步影响所有 viz）。回归 P7 6/6 + P8 7/7 全绿。 → [教训：① pyqtgraph PlotDataItem 的 fillLevel 是"沿 y 方向填到该水平线"，不是"闭合多边形填充"——画封闭图形该用 QGraphicsPolygonItem 而不是 plot()；② 直接挂到 ViewBox 的 QGraphicsItem 不会被 plot.clear() 清，cleanup 必须显式 vb.removeItem；③ "看不见"≠"没渲染"——颜色与背景同色是常见隐 bug，默认调色板应预留对比度；④ 持久化配置的旧值会盖默认值，每次"功能似乎没用"先排查 config.json 是否漂移了。]

[2026-05-29 P8 完成] [用户书面"进入 P8"，要求 3D/2D 路径都改为 K 段渲染：近粗近亮远细远淡，K 默认 8 段] → 新建 `gui/widgets/_path_segments.py` (3 函数：segments_by_age 等长切分+端点续接、lerp_scalar、lerp_alpha_byte)；3D widget DEFAULTS["path"] 扩 6 字段(render_mode/k_segments/head_width/tail_width/head_alpha/tail_alpha)，_rebuild_path_item 改造为 segmented 分支建 K 个 GLLinePlotItem 各带 prebaked width / fade 分支保留 P5 单线 Nx4 alpha，update_snapshot 按桶 setData(pos+color)，cleanup_gl 加 _path_segments 清理，_SettingsPanel 加"路径分段"6 行；2D widget 同模式镜像（K 个 PlotDataItem 各带 mkPen(width=)）；_smoke_phase_p8.py 7 case 全绿（分桶 / 3D K=8 段数 / 切模式不崩 / 段宽单调 1→4 / 2D 投影一致 / cleanup 幂等 / DEFAULTS 字段全）；P5/P7 老测试因默认 mode 变 segmented 报"_path is None"，加 apply_settings({render_mode:"fade"}) 切回单线后绿；P2/P4/P5.5/P6/P7/P8 全绿（P5-6 是已知 config 漂移假失败非回归）。 → [教训：① pyqtgraph GL/2D 的线宽都是 per-item 不是 per-vertex，要"分段不同宽"只能拆 K 个 LineItem 各自固定 width，per-frame 只 setData(pos+color)；② 等长切分 K 段+端点续接是关键，segments[i] 末点 = segments[i+1] 首点，否则视觉断节；③ K 段架构默认接管后，旧测试访问 `_path/_path_item` 直接 NoneError，需 apply_settings 显式切回 fade 模式而不是改测试断言（前者最小破坏）；④ ConfigService 是整树持久化（path_viz.settings 一个 key 存全部 path.* 子树），P8 新字段无需登记 _DEFAULTS——白名单设计的红利；⑤ render_mode 切换必须触发 _rebuild_path_item，已有的 panel _on_panel_value_changed grp=="path" 分支自动覆盖。]

[2026-05-28 P7 完成] [用户书面"进入 P7" + "Start implementation"，要求 XY/XZ/YZ 三平面 2D 投影视图与 3D 视图并列，Foxglove 风格浮窗+QDockWidget 可吸附] → 新建 `gui/widgets/path_2d_view_widget.py` (~530 行)：DEFAULTS_2D（path/icon/grid/view 四组）+ _PLANE_TABLE（投影轴索引）+ _Mini2DSettingsPanel（独立设置面板，不复用 3D 的 _SettingsPanel 避免耦合）+ Path2DViewWidget（PlotWidget 而非 GLViewWidget，原生 2D 自带缩放/平移/网格；纸飞机多边形含尾凹 5 顶点；apply_settings/current_settings/cleanup 三 API 对齐 3D widget 接口）；`config_service.py` _DEFAULTS 加 6 个白名单 key (features.path_visualization_xy/xz/yz + path_viz_2d.*.settings + ui.main_window_state)；`main.py` 扩 _FEATURE_DOCKS 加 3 项 + 新增 _PATH_VIZ_KEYS / _PATH_VIZ_2D 注册表；`__init__` 遍历 3 个 2D widget 各自接 path_updated/apply_settings/settings_changed（闭包 ck=cfg_key 防 late-binding）/reset_requested；`_on_feature_toggled` 用 `_any_path_viz_enabled()` 替换单 key 判断（任一 viz feature 开启则启动 PathTracker 广播）；__init__ 末加 restoreState(base64)，closeEvent 加 saveState→base64 持久化 Dock 布局；新建 `gui/test/_smoke_phase_p7.py` 6 case：三平面构造/投影一致性 XY=(x,y)·XZ=(x,z)·YZ=(y,z)/点数一致/apply_settings 深合并+current_settings 深拷贝/cleanup 幂等/注册表完整。P2/P4/P5.5/P6 回归全绿。 → [教训：① 不抽 _BaseVizWidget 基类是对的——GLViewWidget 与 PlotWidget 渲染栈差异太大，YAGNI 直到 P9 共享代码确实多再抽；② ConfigService 白名单设计要先扩 _DEFAULTS 再写读写代码，否则 set 静默丢失；③ for 循环里 connect 闭包必须用默认参数绑当前 key（`lambda s, ck=cfg_key: ...`），否则 4 个 widget 全写到最后一个 key；④ QMainWindow.saveState 返回 QByteArray，用 toBase64() 转 str 落 JSON 配置；restoreState 必须在所有 Dock add_dock 完成之后调；⑤ restoreState 会覆写 Dock 可见性回上次值，要再用 features.* 校准一次保持菜单/Dock 同步；⑥ Path2DViewWidget 用 plotitem.getData() 拿回数据做投影断言，比拦截 setData 信号更直接；⑦ DEFAULTS_2D 必须用 _deep_merge 不是 dict.update，避免 path 子树被整段覆盖丢失字段。]

[2026-05-28 P6#3 完成] [Dock 反复打开/关闭或主窗口关闭时担心 GL VBO 残留泄漏] → 在 PathVisualizationPlaceholder 类加 `cleanup_gl()` 幂等方法 + `closeEvent` hook：先标 `_gl_ok=False`（防 update_snapshot 在拆解中访问 _view），遍历清 _grid_items + axis 杆/圆锥头/字标/_nose/_cube/_path/_vel_arrow/_vel_head 共 12 个 GL item 引用置 None，最后兜底扫一遍 view.items 防漏。新增 P6-6 smoke：实测 view.items 13 → 0，多次调用幂等。P2/P4/P5.5 回归全绿。 → [教训：① pyqtgraph.opengl 没有公开"释放 GL"接口，只能 removeItem + 断 Python 强引用让 GC 回收 VBO；② cleanup 第一步必须先把 `_gl_ok=False`，否则信号槽残留触发 update_snapshot 会访问已半拆的场景；③ 用 getattr+setattr 循环置 None 比逐字段写更耐"未来加新 item 忘记同步"——但要兜底处理某些环境根本没该字段的情况；④ P6-6 smoke 必须用 QApplication 而非 QCoreApplication，否则 QWidget 创建失败；统一 main 入口的 app 类型简化了。]

[2026-05-28 P6#1+#2 完成] [需要在数据通路上确保高频帧不撑垮渲染、并且任意一环异常不让 bus 崩] → 方案 A 时间窗节流（用户选）：emit `path_updated` 受 1/render_fps 窗口限制；窗口内的所有调用都被 drop；过期才发，发的是 tracker.snapshot() 当下最新值（自动 coalesce）。→ TelemetryBus 新增 `_emit_count/_drop_count` + `reset_throttle_stats()/get_throttle_stats()` 接口；`_maybe_emit_path` 包 try/except，snapshot 抛错时仍推进 `_last_emit_ts` 防 retry 风暴，status 发 WARN。新建 `gui/test/_smoke_phase_p6.py` 5 个 case：①200Hz×1s emit 上限验收（实测 28 emit / 172 drop ≤ upper 33）②渲染关时不进 emit/drop ③reset 计数清零 ④坏帧（长度错/未知 cmd）不入节流 ⑤snapshot 抛异常时 status 收 WARN + 恢复后能继续 emit。P2/P4/P5/P5.5 回归全绿（P5 case_6 已知 config 漂移非回归）。 → [教训：① 节流验收要量化（emit ≤ render_fps × dur + 容差），不能只看"没崩"；② 异常路径要让计数照样推进，否则下一帧立刻又试又抛——递归风暴；③ 摘要里看到"throttle 已存在"不等于"已验收"，缺验证 smoke 就等于没节流；④ 用 `(_ for _ in ()).throw(Err)` 替换方法是 monkey-patch 抛异常的最干净写法。]

[2026-05-28 第三轮真机+用户洞察] [冷却补强方案离线 OK 但用户直接洞察："IMU 0x07 本身是 a 积分而来的 v，再用 v 积分出 xy 是双重漂移，GUI 补丁无法救"] → 决策：买光流传感器，等接入后融合 v 才会准，路径漂移问题**冻结**不再迭代。 → 修复：path_tracker.py 砍掉所有冷却状态机字段（_was_high/_in_cooldown/_cooldown_until_ts/_yaw_lock_deg）和常量（_V_ENTER/_V_EXIT/_COOLDOWN_S），on_velocity 退回到"死区→反旋转→直接积分"三段；snapshot 退回到直接读 IMU yaw。文件头注释更新为"等光流接入"。P2/P4/P5/P5.5 smoke 全绿（P5 case_6 已知 config.json 配置漂移假失败，非回归）。 → [核心教训：① IMU 0x07 = a∫dt 来的 v，本身就漂；再 ∫v dt 得 xy 是双重漂移，**任何不引入新传感器的 GUI 端补丁都治标不治本**——这是物理事实，不是算法不够好；② 用户工程经验比算法迭代更值钱——两轮失败 + 一句洞察就定了方向；③ 不要在传感器没就位前堆补丁刷里程，"等光流"比"再调一版冷却"更省工时；④ master plan 强约束起作用了：用户书面进入 P6 才动 P6 代码，避免了"补丁滚到 P7"。]

[2026-05-28 第二轮真机] [用户报告：动态期方向都对了 ✓ / 任何运动停下瞬间 UI 都会反向漂移] → 根因：纯极简版没压 ZUPT 反弹（停下后 0x07 输出反向脉冲 5-10cm/s × 0.5s）和 IMU 0x03 yaw 自校正（停下后 -2.9°/s × 19s）。 → 修复：path_tracker 加入"运动→停止"过渡冷却状态机，新增字段 `_was_high/_in_cooldown/_cooldown_until_ts/_yaw_lock_deg`，常量 `_V_ENTER_CMPS=5.0 / _V_EXIT_CMPS=3.0 / _COOLDOWN_S=2.0`。on_velocity 用**原始** |v_body|（非死区后）跑状态机，触发冷却时锁住当前 IMU yaw；冷却期完全不积分、速度箭头清零；snapshot 冷却期 yaw 用锁定值，roll/pitch 实时。关键：只用 |v|，不用 yaw_rate（后者在 enable 前已被 0x03/0x04 噪声预积累，是上轮 5 层补丁的致命坑）。 → 离线验证：向前末位 0.5→−0.4cm、向左 1.0→0.4cm（ZUPT 反弹被吞）；cw90 66.8→63.5cm（旋转期累积仍在，冷却只压停下后）；P2/P4 全绿。 → [教训：① 用户"反向漂移"投诉本质是 ZUPT 反弹 + IMU 自校正双尾巴，集中在停下后 0.5-2s 释放；② 用 `|v_body|` 而非 `yaw_rate` 检测过渡是关键安全点——速度死区+滞回可靠，角速度信号在初始化前会被噪声污染；③ 离线 replay 末 5s 统计冷却"锁定帧=0"是正常的，冷却 2s 早过期，应看末位/最远值是否变小判断反弹被压；④ 旋转期 |v_body|=5-8cm/s 噪声会让 was_high=True，停下后噪声落 1-2cm/s 触发冷却 → 旋转停下也能锁 yaw，符合用户诉求。]

[2026-05-28] [用户对 BUG9+10"5 层补丁方案"反馈：①cw90 停下后 cube 平滑慢慢转回去 100°（说明 yaw lock 真机没生效）②位移延迟特别高③每次变化不一样④越改越烂] → **根因**：5 层补丁互相打架——|v|EMA 增加 200ms 滞后；方向一致性把缓慢方向变化误判为反弹丢弃；yaw lock 在真机 `_yaw_rate_dps` 被噪声累积 → 进入 MOVING 后回不来；用户表现为"延迟+不可预测"。 → **决策**：用 askQuestions 给用户三选项（A 极简 / B 中间 / C 砍位置），用户选 A "所见即所得"，位移仅死区 2cm/s。 → **修复**：path_tracker.py 删除所有运动检测器/yaw 锁定/EMA/方向一致性逻辑；on_attitude 仅 `_latest_attitude=sample`；on_velocity 仅 `|v_body|<2 死区 + body→local 反旋转 + 直接积分`；snapshot.yaw 直接给 IMU 值。删除字段 `_is_moving/_static_pending_since/_vmag_ema_cmps/_dir_x/_dir_y/_last_att_ts/_last_att_yaw/_yaw_rate_dps/_locked_yaw_deg/_yaw_lock_active`；删除常量 `_V_ENTER/_V_EXIT/_YAW_RATE_*/_STATIC_HOLD_S/_V_DIR_DOT/_YAW_RATE_GATE/_VMAG_EMA_ALPHA`；仅留 `_V_DEADBAND_CMPS=2.0`。 → **离线 replay 验证**：静止 0cm（与门控版一样）/ 向前 0.5cm（一致）/ 向左 1.0cm（更小，因为没有方向 EMA 复杂行为）/ **cw90 66.8cm（旋转中 0x07 噪声反旋转积分，与门控版前 +5.6cm 差很大）**。P2-P5.5 全绿。 → [教训：① IMU 0x07 在旋转中本身就有几 cm/s 噪声，**不加角速度门控 cw90 必然漂 60+ cm**——这是 IMU 物理事实不是 GUI bug；② 多层补丁互相干扰会让用户看到"不可预测+延迟"，比单一物理偏差更难接受；③ 真机 `_yaw_rate_dps` 在 enable() 前已被 0x03/0x04 噪声累积成非零（即使 dt>5ms 守门），enable 后第一帧 on_velocity 检查角速度 > 5°/s → 立即解锁 → 永远 MOVING；④ 算法越简单越能解释给用户听，"哦旋转就是会飞出去"用户能懂，"为什么这次方向对那次方向反"用户没法忍；⑤ askQuestions 必须给用户决策权而不是替他决定算法，这是用户原话"越改越烂"的潜台词。]

[2026-05-28] [BUG9 cw90 旋转停下后 cube 自己慢慢逆转 120° + BUG10 横移停下后 cube 反向拉回 + 渲染端 yaw 改善需求] → **根因 1 (BUG9)**：IMU 0x03 yaw 在机械停止后会持续自校正漂移 **19s 共 -54°（约 -2.89°/s）**——光靠 |yaw_rate| 阈值过滤不掉，因 IMU 自校正速率 < 5°/s。**根因 2 (BUG10)**：0x07 ZUPT 反弹段虽然被方向一致性丢弃，但**渲染端速度箭头**直接显示原始 vx/vy 仍有视觉拉回。**根因 3 (隐藏)**：on_attitude 用任意 dt 计算 yaw_rate，但 0x03/0x04 yaw 解码有 0.003° 差异、时间间隔仅 0.4ms → inst = -7.5°/s 假角速度被 EMA 拉成 -20°/s，触发误 MOVING 后回不来 STATIC。→ **三件套修复**：① path_tracker.py 引入 **Motion Detector + Static Yaw Lock 架构**：联合 |v| EMA + |yaw_rate| EMA + 0.4s 滞回窗判 STATIC/MOVING；ENTER (5cm/s 或 5°/s)、EXIT (2cm/s 且 4°/s)；进入 STATIC 瞬间 snapshot 当前 IMU yaw 为 `_locked_yaw_deg`，snapshot() 输出锁定值（roll/pitch 保持实时不锁）；② on_velocity STATIC 时积分=0 且 `_vx_local=_vy_local=0`，速度箭头自然消失（消除 BUG10 视觉拉回）；③ on_attitude **dt < 5ms 时跳过 yaw_rate 估算**（防 0x03/0x04 解码差异放大）→ 离线 4 场景验证（gui/replay_fix.py 扩展末 5s 锁定统计）：静止 402/402 锁定、向前 402/402、向左 383/401、cw90 392/402；render yaw 末 5s 极差从原 IMU 漂移 -54° 降到 0~13°；P2~P5.5 smoke 全绿 → [教训：①IMU yaw 自校正速率可达 -2.9°/s，单纯角速度门控阈值卡 2°/s 会"永远 MOVING"，必须设 ≥ 4°/s 让自校正速率落入 STATIC；②on_attitude 计算瞬时角速度必须设 dt 下限（≥5ms），否则 0x03/0x04 双源同时进 PathTracker 会用 0.4ms 间隔放大 0.003° 差异成 7.5°/s 假角速度；③"现实停下=UI停下"需要 GUI 端主动 snapshot yaw 锁定，不能指望 IMU 0x03 自己稳；④调试 IMU 漂移不要急于改阈值，先把 dt 退化场景验证清楚；⑤验证脚本应同时打印 IMU 原值 + 渲染值 + lock 帧数比，单看末位 pos 无法发现 yaw lock 失效。]

[2026-05-27] [真机验证后用户报 4 个 GUI 视觉 BUG：①cube yaw 方向反 ②静止漂移更严重 ③横移停下后 cube 回退 ④横移时 cube 还伴随线速度漂] → **真实数据离线分析（gui/data/2026-05-27 4 个 JSONL）**：①0x07 在静止时 vx/vy 全 ≡ 0（不可能漂，用户描述②实际指其他症状）②向左测试 vy 时序铁证：主动段 [+5,+9,+13,+16,+15,...] 0.56s 后**反弹段持续 1.4s [-6,-6,-7,...]**——IMU 0x07 内部 ZUPT/卡尔曼滤波器的减速虚拟速度估计③CW90 旋转测试不加门控积分末位 (-58.9, -29.8) cm = **66 cm 漂移**！0x07 旋转中仍报 ±5~8 cm/s 假速度被变化中的 delta_yaw 反旋转疯狂积分 → **修复三处**：① path_tracker.py 加角速度门控：on_attitude 内 EMA 计算 _yaw_rate_dps（0.3旧+0.7新），on_velocity 内若 |yaw_rate|>5°/s（静止噪声底 ~0.6°/s）则 vx_l=vy_l=0；② path_tracker.py 加"主导方向一致性"运动状态机：IDLE→MOVING 阈值 5cm/s，进入时记录单位方向(_dir_x,_dir_y)；MOVING 时若 v·dir≤0（反向）或 |v|<deadband(2cm/s) → 立即停积分，连续 0.4s 才退回 IDLE；同向积分同时 EMA(0.85/0.15) 更新主导方向；③ widget path_visualization_widget.py cube yaw 渲染翻号：`m.rotate(-yaw_local,0,0,1)` —— IMU NWU yaw 经 pyqtgraph CCW 正约定+默认相机斜视角导致视觉反向，渲染端取负即可；④ P4 case_2 断言更新：yaw=90° 机头从 +y 改为 -y（与新约定一致）→ 离线 replay 验证 4 场景全部符合预期：静止 (0,0)、向前 1.3cm、向左 +2.1cm、CW90 漂 3.8cm；P1-P5.5 全绿 → [教训：①IMU 0x07 在减速段会产生持续 1.4s 的反向虚拟速度（ZUPT 残差），单纯 deadband+迟滞过滤不掉，必须用"主导方向一致性"丢弃反向值；②旋转中 0x07 自身就有几 cm/s 噪声，必须用 yaw 角速度门控（>5°/s 冻结）才能压住，否则 33s 转 90° 漂 66cm；③pyqtgraph rotate() 是 CCW 正但用户视觉期望与 IMU NED-like 体感不符，渲染端翻号是最干净修复，不动数据层；④IMU 输出"速度"≠物理位移积分；ZUPT 设计使整段积分→0，用户期望 GUI 显示位移则必须主动忽略反弹段，承担"位移略偏小"的代价；⑤数据驱动诊断 > 假设驱动：先录真机 JSONL 看 vx/vy 时序再改代码，避免又错方向]

[2026-05-28] [用户列出 5 项 P5 后补丁需求：①传感器帧记录给 AI 诊断 ②机身轴默认显示 X/Y/Z 字符 ③三轴+机头+速度向量改"真箭头"非裸线 ④静止漂移 ⑤水平移动方向错 + XYZ 比例不一致] → [4/5 必须真数据才能诊断；先把 1/2/3 做完，并通过 1 产出 JSONL 喂回 4/5] → [① `gui/services/frame_recorder.py`：FrameRecorder(QObject)、RECORD_CMDS = {0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x0E}、JSONL 行格式 {t_mono, t_iso, dest:"0xFF", cmd:"0x03", len, hex, fields(decode_attitude_euler/quat 等)}，_meta 头尾标记，64KB 缓冲 + 每 32 帧/0.5s flush；② main.py 接入：菜单 File → "开始/停止传感器帧记录" toggle（Ctrl+R）+ QFileDialog 选 .jsonl 路径，状态栏 ●REC N 帧 红字（隐藏式 permanent widget），SerialWorker.frame_received→recorder.on_frame；③ widget _SettingsPanel 新增"记录"分组（开始/停止按钮 + 状态 label），signal record_toggle_requested 转发给主窗口的 QAction.setChecked（单一源），公共 set_recording_state(active,path,count) 双向同步；④ widget DEFAULTS["axis"] 加 head_radius_cm/head_length_cm/labels_visible/label_size/label_offset_cm；DEFAULTS["vel_arrow"] 加 head_radius_cm/head_length_cm；⑤ _make_cone_mesh 沿 +X 顶点在原点的圆锥（apex+base_center+rim×cols 顶点；侧面 cols 三角 + 底面 cols 三角）；⑥ _rebuild_axis：3 个 GLMeshItem 圆锥头（X 红、Y 绕 Z+90°变绿、Z 绕 Y-90°变蓝）+ 3 个 GLTextItem 字标（QFont 加粗 14pt）；⑦ _rebuild_vel_arrow 加圆锥头，每帧 axis-angle 算从 +X 到 (ux,uy,uz) 旋转：cross=(0,-uz,uy)，angle=acos(ux)；⑧ update_snapshot 给每个 cone 头/字标设 Transform3D（cube 同款 M 上 translate(L+off,0,0)），字标用 m.map() 算世界坐标后 setData(pos=)；⑨ _smoke_phase_p5_5.py 5 case 验证生命周期/白名单过滤（0xE0/0xA0/0x41 全被丢）/RECORD_CMDS 内容/DEFAULTS 新字段/_make_cone_mesh 形状] → [教训：① pyqtgraph.opengl 0.14 起 GLTextItem 可用，font 参数若环境不支持需 try/except 退化；② QAction 在 `__init__` 排序晚于 widget wiring 时，widget→action 的 connect 必须延迟到 menu 创建后再绑；③ 圆锥 mesh 用 axis-angle 旋转最稳：(1,0,0)→(u,v,w) 的旋转轴 = (0,-w,v)，角度 = acos(u)，逆向 (-X) 时退化为绕 Z 180°；④ Frame dataclass 字段是 `dest`（不是 addr），新代码访问必须用 `fr.dest`；⑤ 配置已被用户改过（render.fps=100、trail_seconds=7），导致 P5 case_6 那条 `assert _render_fps==30` 假失败 — 不是回归，配置漂移；⑥ 0x03 帧 LEN=7（含 1 字节 fusion_sta），写测试不要漏；⑦ JSONL "_meta" 头尾标记对离线诊断脚本很关键，便于多文件拼接区分。]

[2026-05-27] [P5 完整参数面板 + 持久化（D7 + 用户提到的"等等还有很多"参数：坐标轴/网格/路径/立方体/机头球/速度箭头/渲染/控制按钮）] → [P4 widget 是写死常量；要让 7 组共 30+ 参数都能拖动且持久化，必须把常量提到 dict 顶部 + 右侧设置面板 + 信号回路 + ConfigService 持久化整树] → [① 完全重写 `path_visualization_widget.py`：顶部 7 组 `DEFAULTS`（数值等同 P4 → 默认零回归），新增 `_ColorButton`（QColorDialog 弹色 + 样式表显色）/`_SettingsPanel`（QScrollArea+7×QGroupBox+QFormLayout），主部件 QSplitter 左视图右面板，⚙ 按钮切显隐默认关；信号 `settings_changed(dict)`/`reset_requested`/`refresh_requested`；`apply_settings(dict)` 深合并+重建（不回发信号），`_on_panel_value_changed(path,value)` 按组定向重建（_rebuild_cube/nose/axis/vel_arrow/grids/path_item/render，避免重建整场）；路径渐隐 fade=True 时 setData(color=Nx4 ndarray)，fade=False 单色；保留 `_NOSE_OFFSET_CM/_VEL_ARROW_SCALE` 等常量供 P4 测试沿用；② `ConfigService._DEFAULTS` 新增 `"path_viz.settings": {}` 放白名单；③ `main.py` 加 PathTrackerConfig import，启动后 `viz.apply_settings(config.get("path_viz.settings",{}))` 还原，一次性同步 `bus.set_render_fps`+`bus.update_config(PathTrackerConfig)`；接 settings_changed → `_on_path_viz_settings_changed`（写 config + 同步 bus）+ reset_requested → `bus.reset_path`；④ 新增 `_smoke_phase_p5.py` 6 case 验证默认 key 登记/默认值等同 P4/面板改值 emit+self._s 写入+apply_settings 深合并/fade Nx4 alpha 单调（实测 [0.0,0.5,0.9,1.0]）/fade=False 退单色/MainWindow 一体化（改 fps→bus._render_fps、改 trail_seconds→tracker.config、持久化命中、reset 不抛）] → [教训：① ConfigService 是白名单设计，加新 key 必须同时改 `_DEFAULTS`，否则 set/get 不报错但落盘丢失；② GLLinePlotItem.color 支持 Nx4 numpy 数组做逐点 alpha，渐隐用 `1 - age/trail_seconds`；③ widget 双向数据流必须分清两路：`apply_settings`=外部灌入不回发，`_on_panel_value_changed`=用户改必回发，否则启动还原时会立刻把还原值回写 config 触发死循环；④ 定向重建（按组）远胜重建整场，否则每拖一下 QDoubleSpinBox 就闪屏；⑤ 重写前必须 PowerShell `Remove-Item` 删旧文件，`create_file` 不覆盖；⑥ 渐隐颜色数组用 `np.ones((N,4))` + 第 4 列乘 alpha；⑦ 模块常量加注 "向后兼容 P4 测试" 注释，否则下次重构容易误删。]

[2026-05-27] [P4 姿态旋转 + 机头小球 + 速度箭头（D6 完整版）；中途修了 P3 的两个视觉问题：①三轴是世界轴没跟立方体走；②方块启动时悬在半空] → [P3 的 GLAxisItem 是世界系画的，没绑过 transform；D5 原文 "Z=0x05 绝对高度" 在飞控报 80cm 高度时方块直接飞 80cm 看起来"飞到半空"——用户期待"启用瞬间为零点"] → [① path_tracker：D5 微调，新增 `_z_offset_cm`，enable() 时记 `_z_offset=latest_height.alt_fu_cm`，_z_cm=0；on_height: `_z_cm = alt - _z_offset`；同步改 reset()；P2 case_2 断言改为 z=0 + 增量子断言；② widget P3：保存 self._axis 引用，update_snapshot 里同步 translate；轴长从 100→30cm；③ widget P4：导入 pyqtgraph.Transform3D，新增 _NOSE_RADIUS=4/NOSE_OFFSET=15/VEL_ARROW_SCALE=0.4 cm/(cm/s)/MAX_CM=120 常量；新增 _nose（GLMeshItem MeshData.sphere 黄色）和 _vel_arrow（GLLinePlotItem 橙色 width=3 mode=lines）；update_snapshot 构 M=T(pos)·Rz(yaw-yaw0)·Ry(pitch)·Rx(roll) post-multiply 顺序，cube/axis 共享 M，nose 在 M 上再 translate(NOSE_OFFSET,0,0)；vel_arrow 独立用 vel_local 方向，|v|<1 折叠零长；④ 新增 `_smoke_phase_p4.py` 6 case 验证 nose 在 yaw=90° 处于世界 (0,15,0)、yaw=yaw0 时机头在世界 +x、vel_arrow 末端 vx_l=100 偏 40cm、|v|<1 折叠、姿态不影响 vel_arrow] → [教训：① GLAxisItem/GLMeshItem 都接 setTransform，要让"跟随姿态"的元素共享同一 Transform3D；② pyqtgraph.Transform3D（=QMatrix4x4）的 translate/rotate 是 post-multiply，写顺序 T→Rz→Ry→Rx 等同于点先做 Rx→Ry→Rz→T，与 OpenGL ZYX 体外旋转习惯一致；③ "贴在某个面外侧"的子元素，最干净做法是父 transform 上再 translate，不要把局部偏移塞进 mesh 顶点；④ 速度箭头方向必须用已经反旋转过的 `vel_local`，不要用世界 vx/vy，否则启用之初机头朝东和朝北的飞机箭头方向解释会不一致。]

[2026-05-28] [BUG4 静止漂移 + BUG5 水平移动方向错] → **BUG4根因**：0x07 vx_cmps 静止偏置 ~+0.5 cm/s，积分 60s → 30cm 漂移 → **BUG5a根因**：0x07 是机体系速度（FLU），PathTracker 错误地当世界系处理并做 yaw0 反旋转，导致"向前飞→GUI 显示向后" → **BUG5b辅助根因**：0x04 四元数 yaw 符号相反（匿名 IMU NED 旋转，z负；解码公式 NWU 未取反）。TelemetryBus 0x04 优先使 PathTracker 全程用错误负 yaw，delta_yaw 差 285° 方向翻转 → **修复三处**：① telemetry_decoder.py decode_attitude_quat：yaw_deg 取负；② path_tracker.py on_velocity：改为机体系 delta_yaw 旋转（归一化±180°边界）+ 2cm/s 速度死区，删 _yaw0_cos/_yaw0_sin；③ smoke_phase_p2.py：_quat_data z分量取反，case_2 sub-B 断言从"世界系(0,-100)"改为"体系(100,0)"；P1-P2-P3-P4-P5.5 回归全绿 → [教训：①用 vx/vy ratio 验证坐标系假设比代码走读可靠；②0x04 yaw 与 0x03 不一致会悄悄破坏 delta_yaw，加新 IMU 必须先验证一致性；③TelemetryBus"0x04 优先"无降级，建议未来加 source=="euler" 白名单；④速度死区 2cm/s 消除静止漂移不影响动态运动]


---


---


---
## GUI 路径可视化 — 大阶段全局计划锁定 (2026-05-27)

[2026-05-27] [P1 顶部"功能"菜单 + 路径可视化 Dock 显隐 + 持久化] → [发现 ConfigService 用 `_DEFAULTS` 白名单过滤加载，未登记的 key 会被丢盘] → [新建 PathVisualizationPlaceholder Widget；main.py 加 `_FEATURE_DOCKS` 注册表 + `_build_feature_docks` + 功能菜单 + `_on_feature_toggled`；`_DEFAULTS` 增加 `features.path_visualization: False`；新写 `_smoke_phase_p1.py` 6 步验证全 OK] → [教训：用 ConfigService 持久化新键时必须先登记到 `_DEFAULTS`；GUI 测试中验证 Dock 显隐前必须先 `win.show()` + `processEvents()`。]

---
## GUI 路径可视化（旧 Phase 1 骨架完成 — 已作为 P3-P5 的起点保留）(2026-05-26)

[2026-05-26] [在不影响原 GUI 的前提下启动路径可视化实现] → [原入口只处理 0xA0，缺少解耦遥测通道与功能门控] → [新增 `gui/services/telemetry_models.py`、`gui/services/telemetry_decoder.py`、`gui/services/path_tracker.py`、`gui/services/telemetry_bus.py`；MainWindow 旁路接入 TelemetryBus；新增 `gui/widgets/feature_bar.py` 功能下拉和 `gui/widgets/path_visualization_widget.py` 右侧 Dock 可视化面板（pyqtgraph 可用时 3D，缺依赖时自动降级）；仅在选中“路径可视化”时启用积分/渲染；参数可调并持久化到 config] → [教训：可视化必须“旁路接入+可停用零负担”，并保持 Ack/命令发送主链路零改动。

验证：`gui/test/_smoke_phase_d.py` 与 `gui/test/_smoke_phase_e.py` 均 EXIT=0（无功能回归）。

[2026-05-26] [路径可视化依赖已安装但 `pyqtgraph.opengl` 仍导入失败] → [缺少 OpenGL Python 绑定，`ModuleNotFoundError: OpenGL`] → [在 `gui/requirements.txt` 增加 `PyOpenGL>=3.1` 并安装，验证 `from pyqtgraph.opengl import GLViewWidget` 成功] → [教训：3D 组件依赖链要做“import 级”验收，不只看 pip 安装成功输出。]

---
[2026-05-27] [担心路径可视化需求在多轮开发中遗漏] → [需求仅分散在对话与代码中，缺少单一可勾选验收源] → [新增 `gui/requirements_lock_checklist.md`，逐条锁定 R1-R9（状态/验收标准/代码位置/每次改动必勾区），并在 `.github/copilot-instructions.md` 增加“开发前必读、完成后必勾选”约束] → [教训：阶段性大需求必须形成“单文档、可勾选、可追踪”的锁定清单，避免口头约束失真。]


## GUI 接入 0xF3 — ✅ 真链路验证通过 (2026-05-26)

[2026-05-26] GUI 端原本以 "F2 拆 3 帧串联" 实现三轴写入 → 固件已上 0xF3 原子帧 → 改用 0xF3 单帧：
- `groundTest/ano_protocol.py` 新增 `build_f3_xyz(dest,x,y,z)`，`gui/io/protocol.py` 转出。
- 新建 `gui/commands/cmd_f3.py`（CmdF3 + F3Panel），`cmd_id=0xF3` `requires_confirm=True` `ack_timeout_ms=1500`；回执正则 `^P\*=x,y,z[ CLP]
# 开发日志 — 匿名凌霄室内四旋翼无人机

> **规则（强约束）**：
> 1. **每次开发会话开始前必须读取此文件**，了解当前进度和未解决问题。
> 2. **每次解决问题后必须立即追加记录**，格式：`[日期] [问题] → [原因] → [解决方案] → [教训]`
> 3. **每次完成一个功能后必须更新"当前进度"节**，标明已完成/进行中/待做。
> 4. **思考和回答必须紧贴当前任务目标**，禁止偏离目标做无关扩展。
> 5. 若本次修改涉及飞行安全，必须在记录中注明"⚠️ 安全影响"。


。
- `gui/commands/__init__.py` 增加 `from . import cmd_f3`。
- `gui/commands/cmd_f2.py` 清掉三轴拆帧分支：删除内嵌 `_StableDoubleSpinBox`、`_PARAM_ID_TRIAXIAL=0xF0`、QStackedWidget、`_make_axis_sb` 等，仅保留单轴路径。
- 抽出 `gui/widgets/stable_spinbox.py::StableDoubleSpinBox`（之前内嵌在 cmd_f2，现 F2/F3 共用）。
- `gui/main.py` 移除残留的 `params.get("_skip_confirm")` 分支（拆帧机制下产物，已无意义）。
- `gui/io/fake_worker.py` 新增 `_echo_f3` 分支：解析 12B 三 float，独立 ±500 限幅，回执 `P*=x,y,z[ CLP]`。
- 教训：删除旧实现时要顺手清掉它在主窗口/Fake/REGISTRY 几处旁路；遗留的 `_skip_confirm` 之类 hook 不及时清会形成死代码地雷。
- 自检：`from gui import commands` 后 REGISTRY 列出 `0xE1/0xE2/0xF1/0xF2/0xF3`；`build_f3_xyz(0xFF,30,44,55)` → 18B 帧（4B 帧头 + 12B float×3 + 2B 校验）。
- **真机验证（COM11 实链路 4/4 通过）**：(20,10,0)/(30,20,0)/(30,20,20)/(30,20,40) cm，全部 INFO 级 `F3 OK：X=..,Y=..,Z=..`，无 CLP、无 TIMEOUT、无丢包。
- **算长度教训**：F3 单帧总长 = 4(AA+dest+cmd+LEN) + 12(数据) + 2(SC AC) = **18B**，不是 15B；之前 send_xyz.py 描述里"15B 总长"是错的，但代码正确。

---
## 阶段 2b：0xF3 三轴同时写入帧 — ✅ 实现 (2026-05-26)

需求：单帧原子写入 X+Y+Z，避免三条 0xF2 顺序帧的部分丢失风险。

固件改动：
- `FcSrc/Uplink_Cmd.h`：补充 0xF3 帧说明
- `FcSrc/Uplink_Cmd.c`：
  - 新增 `ECHO_KIND_PARAM3` 与 `s_last_p3_x/y/z` + `s_last_p3_clamped`
  - `Uplink_Cmd_Dispatch` 新增 `cmd==0xF3` 分支：解析 12B（3×float LE），分别复用 `param_apply(PARAM_ID_GOAL_X/Y/Z, ...)` 写入并独立返回 clamp 标志，OR 后合并
  - `Uplink_Cmd_Tick` 增加 PARAM3 回显分支："P*=30.0,44.0,55.0" 或末尾 " CLP"（绿色）
- `FcSrc/ANO_DT_LX.c`：新增 `else if (*(data+2)==0xF3) → Uplink_Cmd_Dispatch`

地面工具：
- `groundTest/send_xyz.py`（新）：参数 `--x --y --z`，`struct.pack("<fff",...)` → `build_frame(dest, 0xF3, payload)`，15B 总长

帧格式：
```
AA FF F3 0C | x(4B LE) | y(4B LE) | z(4B LE) | SC AC
```

与 0xF2 关系：并存，共用同一 RAM 槽与限幅（±500cm），生效时机一致（任务启动时拍照）。

待硬件验证。

---
## 阶段 E（GUI）：扩展槽位 + UI 美化 — ✅ 烟测全绿 (2026-05-26)

新增文件：
- `gui/commands/cmd_placeholder.py`：占位命令模块。注册 0xE1「飞行控制（占位）」+ 0xE2「模式切换（占位）」；`build_frame` 抛 NotImplementedError；面板按钮永久禁用，独立状态行显示「固件未实现」。
- `gui/services/theme_service.py`：内联 light/dark QSS 字符串 + `apply_theme(name)`，未识别名回落 dark。
- `gui/_smoke_phase_e.py`：占位命令注册 / 主题切换 / MainWindow 含视图菜单含占位类别 三项检查全过。

修改文件：
- `gui/main.py`：
  - 状态栏新增「最后接收 HH:MM:SS」label，每帧入站更新
  - `_build_menu` 新增「视图」菜单：清屏日志 (Ctrl+L) / 暂停滚动 (checkable) / 主题 (暗色/浅色 QActionGroup 互斥)
  - `main()` 启动时先用临时 ConfigService 读 `ui.theme` 并 apply，避免窗口构建一闪白底
  - 主题切换持久化到 config.json
- `gui/widgets/log_view.py`：公共 API `clear_display()` / `set_paused(bool)`，菜单可直接调
- `gui/commands/__init__.py`：导入 cmd_placeholder
- `gui/README.md`：从阶段 A 占位文档重写为完整使用手册 + "3 步加新命令"教程

新增 memory：
- `/memories/repo/gui-architecture.md`：GUI 三层分层、7 条关键设计决策、反模式 5 条

阶段 D 烟测同步重跑：8/8 仍通过，无回归。

关键决策：
- 占位命令也走 REGISTRY（UI 一致性 > 特殊路径），cmd_id 用 0xE1/0xE2 避免与已知上行帧冲突
- 主题用模块级 QSS 字符串内联，不引入资源文件或第三方主题包
- 日志区**刻意保留暗背景**，无论切哪个主题（长时间盯屏护眼）
- 视图菜单的"暂停滚动"勾选与 LogView 工具栏按钮通过 `set_paused` 双向同步


---
## 阶段 D（GUI）：F2 命令 + 二次确认 + 三态反馈 + 离线 FakeWorker — ✅ 烟测 8/8 通过 (2026-05-26)

完成文件：
- `gui/widgets/confirm_dialog.py`：强制勾选复选框才启用「发送」按钮的二次确认弹窗
- `gui/commands/cmd_f2.py`：CmdF2（requires_confirm=True, ack_timeout=1500ms）+ F2Panel（ID 下拉 + ±600 DoubleSpinBox + 三态灯）
- `gui/io/fake_worker.py`：离线仿真器，鸭子兼容 SerialWorker 接口；激活方式 `set LINGXIAO_GUI_FAKE=1 & python -m gui.main`
- `gui/_smoke_phase_d.py`：8 项烟测（F2 注册/组帧/parse_ack 三分支/交叉不误匹配/FakeWorker F1+F2 UNK+CLP/MainWindow e2e）

修改文件：
- `groundTest/ano_protocol.py`：新增 `build_f2_param(dest, id, value)` 工具函数
- `gui/io/protocol.py`：透传 build_f2_param
- `gui/services/command_registry.py`：CommandPanelBase 增加 STATE_* 常量和 `set_ack_state(state, msg)` 接口
- `gui/widgets/command_panel.py`：增加 `set_ack_state(cmd_id, state, msg)` 路由
- `gui/commands/cmd_f1.py`：F1Panel 加状态灯 + 实装 set_ack_state（idle/waiting/ok/warn/fail/timeout 六态）
- `gui/commands/__init__.py`：导入 cmd_f2
- `gui/main.py`：confirm_send 替换 QMessageBox；ack_matched/timeout 联动面板三态；环境变量切 FakeWorker

已知好串：
- F2 (id=0x01, value=50.0) 帧 = `aafff20501000048422b85`（10 字节）

关键决策：
- 三态颜色：黄=#FBC02D 等待 / 绿=#2E7D32 OK / 橙=#EF6C00 WARN(CLP) / 红=#C62828 FAIL(UNK)/TIMEOUT / 灰=#888 IDLE
- 二次确认强制勾选复选框才启用「发送」按钮，Cancel 设为默认焦点（回车默认取消）
- FakeWorker 延迟 80ms 异步回执（接近真实固件限频 ECHO_MIN_TICK_GAP）
- FakeWorker 与 MainWindow 解耦：通过 `LINGXIAO_GUI_FAKE=1` 环境变量切换，硬件场景零开销

⏳ 待硬件验证：
- F1/F2 真链路回执（用真飞控替换 FakeWorker）
- 多 token FIFO 在真链路抖动下的表现
- 二次确认弹窗在串口断开瞬间的边界

---

## 阶段1：上行指令链路打通（F1 灵活帧）— ✅ 已硬件验证通过

- [2026-05-24] 新建 `FcSrc/Uplink_Cmd.h/.c`：Init / Tick(50Hz) / Dispatch / Send_Ack 骨架
- `ANO_DT_LX.c` 解析末尾增 `else if 0xF1 → Uplink_Cmd_Dispatch`，其余分支零侵入
- `Drv_BSP.c All_Init` 末尾追加 `Uplink_Cmd_Init`
- `Ano_Scheduler.c Loop_50Hz` 追加 `Uplink_Cmd_Tick`
- 阶段1 边界：仅解析 F1 前 4 字节 (S16 X, S16 Y) → 0xA0 绿色回显 `F1: X=.. Y=..`，限频 10Hz；ACK 函数写好但未挂载
- 编译期开关：`UPLINK_CMD_EN`（默认1）

**地面测试工具（groundTest/）**：
- `ano_protocol.py`：帧构建/解析（FrameParser 状态机）
- `win_serial.py`：**Win32 CreateFile 直接打开 COM**，绕过 SetCommState
- `send_f1.py` / `monitor.py` / `list_ports.py`
- 不依赖 pyserial（已知 pyserial 3.5 在 Python 3.14 + STM32 USB-CDC 上 SetCommState 报错31）

**验证结果（2026-05-24）**：发 `AA FF F1 04 D2 04 2E EE 90 A1` (X=1234,Y=-4562) → 收到 `[RX 0xA0 GREEN] F1: X=1234 Y=-4562`。链路全通。

**稳定性测试（2026-05-24）**：
- 单帧：1/1 = 100%
- 2 Hz × 30s：53/60 = **88%**（实用工作点）


---
## 阶段4：分轴飞行验证 + X+Y 联动测试（2026-05-24）

### 4.1 遥控器手感优化（已验证）
- `ANO_LX.c`：`MAX_VELOCITY` 100→**25 cm/s**（满杆=25，半杆≈12，更适合室内）
- CH1/CH2 死区 40→**80**（消除粘杆抖动），补偿系数 0.00217→0.00238 保持线性
- 油门 CH3 **不缩放**，沿用 MAX_VER_VEL_P=300 / MAX_VER_VEL_N=200
- vx 方向最终需**取负**：`vel_x = -tmp_ch_dz[ch_1_rol] * 0.00238f * MAX_VELOCITY`（实测在定点模式下vx与摇杆反向，加负号才同向）

### 4.2 拨杆触发架构
| 通道 | 阈值 | 触发任务 | 默认目标 |
|------|------|---------|---------|
| CH5_AUX1 | 1200~1700 | 进入定点模式（PID任务前置条件） | - |
| CH6 | >1700 && <2200 | **X+Y 联动**（axis_mode=4） | x=50, y=50 |
| CH10_AUX6 | >1700 && <2200 | 仅 Y 轴（axis_mode=2） | y=50 |
| CH7 | >1700 && <2200 | 仅 Z 轴 | z=变量 |
- `pid_active_axis` 互斥状态机（0/1/2/3），多杆同时拨高会被拒绝并红字 LOG
- 触发前置：必须 mode2，且 `RC_IDENTIFY_SAFE_MODE=0`

### 4.3 `pid_3d_task` axis_mode 扩展
位于 `User_Task.c::pid_3d_task(u8 *step, u8 axis_mode)`：
```c
const float goal_x = (axis_mode==0u || axis_mode==1u || axis_mode==4u) ? Uplink_GetGoalX_Cm() : 0.0f;
const float goal_y = (axis_mode==0u || axis_mode==2u || axis_mode==4u) ? Uplink_GetGoalY_Cm() : 0.0f;
const float goal_z = (axis_mode==0u || axis_mode==3u) ? Uplink_GetGoalZ_Cm() : 0.0f;
```
- 0=三轴 / 1=仅X / 2=仅Y / 3=仅Z / **4=X+Y（Z悬停）**
- 合速度 `PID3D_VEL_TOTAL_CMPS=30` 限制：X+Y 同步满速时 vx=vy≈21cm/s（√2 缩放）

### 4.4 关键调参（验证迭代记录）
| 项目 | 初值 | 现值 | 原因 |
|------|------|------|------|
| `PID3D_SCALE_Y` | 0.90 | **1.30** | Y=50 任务实飞 75cm，超调 +25cm；scale 放大让 obs 更早达 goal、提前刹车 |
| `PID3D_VY_XCOUPLE_GAIN` | -0.10 | **-0.17** | X=50 任务 Y 残漂 +5cm（初版 +12cm 用 -0.10 减到 +5），线性外推到 0 |
| `PID3D_GOAL_Y_CM` | 0 | **50** | CH10 Y任务默认目标 |
| `RC_IDENTIFY_SAFE_MODE` | 1 | **0** | =1 时函数早 return，所有触发失效；地面通道识别完毕必须改回 0 |

### 4.5 已知物理现象（重要）
- **Y 轴超调**：纯 Y 任务存在严重惯性超调（goal 50 → 实飞 75），说明 PID 减速段太短或电机响应滞后。靠 SCALE_Y 放大 obs 缓解，但根因未除（可考虑降 `PID3D_VEL_Y_CMPS=25` 或加 D 项）
- **X→Y 串扰**：纯 X 飞行时 Y 正向漂移 ~12cm，开环补偿 `vy += vx * (-0.17)` 修正。物理来源推测为机架/电机不对称或重心偏移
- **0x08 位置帧不可用于闭环**：静止时漂移 ~5cm，已确认 `PID3D_OBS_X/Y_MODE=2`（速度积分）作为唯一可用反馈源

### 4.6 踩坑
- [2026-05-24] CH6/CH10 单独拨高都不触发任务 → `RC_IDENTIFY_SAFE_MODE=1` 导致 `UserTask_OneKeyCmd` 早 return → 改回 0 → **教训：地面识别开关用完必关，否则所有 PID 任务静默失效**
- [2026-05-24] vx 方向反复确认两次：之前因 ANO_LX.c 内部 `tmp_ch_dz` 计算用了 `ch-1500`（左推杆为负值），定点模式下 IMU 期望"右推=vx+"，需取负 → 教训：方向问题必须以实飞为准，代码注释要写明
- [2026-05-24] dev.md 追加内容后全是乱码 → 该文件是 **GBK** 编码，但 PowerShell `Add-Content -Encoding UTF8` 写入 UTF-8（带 BOM）→ 用 Python `open(...,"wb")` + `.encode("gbk")` 重写 → **教训：本仓库所有遗留中文文件（含 .c/.h/dev.md）一律 GBK，追加禁用 `-Encoding UTF8`，应使用 `Out-File -Encoding Default` 或 `[Encoding]::GetEncoding(936)`**

### 4.7 当前任务状态（2026-05-24 EOD）
- ✅ CH6 已切到 axis_mode=4（X+Y 联动，目标 (50,50)），代码已编辑就绪、未上机
- ✅ CH10 仍为 axis_mode=2（仅 Y=50）
- ⏳ 待硬件验证：X+Y 同步飞行落点、Y 超调是否随 SCALE_Y=1.30 收敛、X→Y 串扰补偿 -0.17 在双轴模式下是否过量
- 调参分支：Y 终点 ≥60 → SCALE_Y 提到 1.45；Y 终点 ~30 → VY_XCOUPLE_GAIN 退回 -0.08

---
## 阶段2：PID3D 目标坐标运行时覆盖（0xF2 帧）— ✅ 已硬件验证通过（2026-05-24）

- **范围（用户钦定 A）**：只覆盖 `PID3D_GOAL_X/Y/Z_CM`；不动 PID 参数；不动 LOG_TEST/RC_DIAG。
- **CMD 选 0xF2**：0xE2 已被凌霄 CK_Back 协议占用（ANO_DT_LX.c L334-345），私有空间 0xFx 安全。
- **帧格式**：`AA FF F2 05 | id(1B) | float_LE(4B) | SC AC`，DATA=5B
- **白名单 ID**：0x01=GOAL_X, 0x02=GOAL_Y, 0x03=GOAL_Z；其他红字 "P?? UNK"
- **安全限幅**：±500 cm（飞控端 + Python 端双检），越界 clamp 并回 "CLP"
- **生效时机**：任务启动时（PID3D step=1）通过 `Uplink_GetGoalX/Y/Z_Cm()` 拍照锁定为 const，飞行中不变。修改流程：落地 → 写参 → CH6 重启任务。
- **回显**：成功绿 "P01=30.0"，限幅绿 "P01=500.0 CLP"，未知红 "P05 UNK"

**修改清单**：
- `Uplink_Cmd.h`：声明 3 个 Getter + 白名单 ID 宏 + `PARAM_GOAL_LIMIT_CM=500.0f` + `PARAM_WRITE_EN` 子开关
- `Uplink_Cmd.c`：加 RAM 副本 `s_goal_x/y/z_cm`（Init 从宏取值）、`param_apply()`、`float_to_dec1()`、echo 队列扩展为 KIND_F1/KIND_PARAM 两种内容
- `User_Task.c` L930-932：`PID3D_GOAL_X_CM` → `Uplink_GetGoalX_Cm()`（保持 `const float goal_x = ...`）；新加 `#include "Uplink_Cmd.h"`
- `ANO_DT_LX.c`：F1 分支后追加 0xF2 同样分发到 `Uplink_Cmd_Dispatch`
- `groundTest/send_param.py`：`--port --id --value --listen`，复用 Win32Serial / build_frame / FrameParser

**Keil 工程**：未加新文件（继续用 Uplink_Cmd.c），无需改 .uvprojx。

**硬件验证结果（2026-05-24）— 第1层 RAM 写入路径 5/5 通过**：
| Case | 输入 | 实际回显 | 结论 |
|---|---|---|---|
| 1 | id=1 val=30 | `P01=30.0` 绿 ×4/5 | ✅ X 轴写入 |
| 2 | id=2 val=-50 | `P02=-50.0` 绿 ×2/3 | ✅ Y 轴写入（含负值） |
| 3 | id=3 val=80 | `P03=80.0` 绿 ×3/3 | ✅ Z 轴写入 |
| 4 | id=1 val=800 | `P01=500.0 CLP` 绿 ×4/4 | ✅ 限幅生效 |
| 5 | id=9 val=0 | `P09 UNK` 红 ×4/4 | ✅ 白名单拒绝 |

最终写入 `GOAL_X=33, GOAL_Y=44, GOAL_Z=55`（双发确认，6/6 全部回显）。
**第2层（Getter 拍照锁定到任务 step=1 INIT 日志）暂未现场触发** —— 当前没起飞条件；
代码层面 `const float goal_x = Uplink_GetGoalX_Cm();` 是 1 行确定性 inline，无绕过路径。

**实用工作点**：单帧偶发丢，重发 1-2 次必能命中（与阶段1 88% 通过率一致）。
- 10 Hz × 30s：57/300 = **19%**（带宽饱和，被 IMU 持续上报帧挤压）
- 结论：无线数传上行带宽是瓶颈，0xA0 echo 不要超 2Hz。阶段2/3 实际指令都 ≤2Hz，不受影响。

### 关键踩坑记录

- [2026-05-24] **pyserial 打不开匿名数传 COM11** → SetCommState 报 Win32 错误31 (ERROR_GEN_FAILURE) → 数传驱动固化波特率不接受标准 SetCommState → 用 ctypes CreateFile 直接打开（不调 SetCommState），驱动用内置波特率正常工作 → 教训：遇到驱动报错31先想"驱动是否拒绝改配置"，用 .NET SerialPort 也会复现同样问题，确认非 pyserial bug
- [2026-05-24] groundTest 脚本输出帧太多终端吞掉输出 → 监听时 IMU 持续上报几百帧 → 重定向到文件再 grep；后续可加 `--filter 0xA0` 选项


---
## 阶段5：上行命令链路项目文档归档（2026-05-25）

> 代码层面无新增，仅整理阶段1/2 的对外文档体系，方便交接和后续扩展。

### 5.1 新建/更新文档

| 文件 | 内容 |
|------|------|
| `数据帧.md`（新建） | 顶层数据帧规格汇总：通信链路图 + 0xF1/0xF2/0xA0 帧结构表 + 地址速记 + CMD 私有空间约定（0xFx 全留本项目，禁用 0xE2） |
| `groundTest/README.md` | 加入「阶段2」章节：send_param.py 参数表、回显含义表、完整使用流程（CH6 回中 → 写参 → 触发任务 → 看 INIT 日志）、断电丢值⚠️、阶段2 专用故障排查 |
| `dev.md`（项目根） | 末尾追加「阶段5：上行命令链路」章节：总体架构 ASCII 图、阶段1/2 规格表、地面工具列表、踩坑记录、后续扩展点（Layer2 启动回显 / PID 参数 id / Flash 持久化 / 参数读回） |

### 5.2 私有 CMD 空间约定（落地到所有文档）

| CMD | 用途 | 方向 |
|-----|------|------|
| `0xF1` | 链路验证灵活帧 | PC → 飞控 |
| `0xF2` | 参数写入（白名单 0x01/0x02/0x03） | PC → 飞控 |
| `0xF3` | 三轴目标同帧写入 | PC → 飞控 |
| `0xF4` | 预留候选，分配前必须查最新冲突 | — |
| `0xF5` | 树莓派位置帧规划（cur/tar/flags） | 树莓派 → 飞控 |
| `0xF6`~`0xFF` | 预留候选，分配前必须查最新冲突 | — |

**禁用 `0xE2`**：被凌霄 CK_Back 协议占用（`ANO_DT_LX.c L334-345`），会触发 ACK 冲突。CMD 选取前必须先在 `ANO_DT_LX.c` 全文搜对应 `0xXX` 字面量确认无冲突。

### 5.3 后续扩展候选（未实施）

- **Layer2 启动回显**：CH6 触发任务时发 `3D INIT gx:.. gy:.. gz:..`，让地面能在起飞前确认参数已生效（目前需间接通过 monitor 看任务自身的 INIT log）
- **PID 参数 id**：扩 `0x04~0x08` 给 `KP/KI/KD/SCALE_*/VEL_LIMIT`，飞行中调参；需加 mode2/未起飞 守门避免飞行中突变
- **Flash 持久化**：后续需重新分配未占用私有帧ID，不能复用已占用 `0xF1`/`0xF2`/`0xF3`，并需核对 `0xF5` 树莓派位置帧规划
- **下行参数读回**：后续可另分配未占用读回帧ID → 飞控回 `P01=30.0`，让 PC 主动查询当前 RAM 值


---
## 项目基本信息

- **硬件**：STM32F407 + 凌霄IMU（闭源）+ 凌霄光流 + 凌霄数传
- **开发环境**：Ubuntu 22.04 + VS Code + GCC/CMake/Ninja + OpenOCD + ANO CMSIS-DAP
  - 编译：`./scripts/build.sh`（arm-none-eabi-gcc 9.3.1，输出 `build-gcc/ANO_LX.elf/.hex/.bin`）
  - 烧录：`./scripts/flash-dap.sh`（命令行 OpenOCD，低速无SRST方案已验证，看到 `Verified OK` 即成功）
  - Keil5 工程（`ProjectSTM32F407/ANO_LX_STM32F407.uvprojx`）是原始 Windows 遗留，**当前 Ubuntu 环境不使用**
  - Linux 大小写问题已用 `compat/include/` 目录桥接，不改原始源码
- **语言**：纯C（不是C++）
- **用户入口**：`FcSrc/User_Task.c` → `UserTask_OneKeyCmd()`，50Hz调用

---

## 开发阶段记录

### 阶段0：项目初始化与配置（2026-05-10）

**完成的工作**：
- 阅读了项目完整源码结构（main.c、ANO_DT_LX.c/h、ANO_LX.c/h、LX_FC_Fun.c/h、LX_FC_State.c/h、Ano_Scheduler.c、User_Task.c）
- 建立了完整的 agent 配置系统：
  - `.github/copilot-instructions.md`：全局开发指令
  - `.github/instructions/lingxiao-protocol.instructions.md`：凌霄协议规则库
  - `.github/instructions/keil5-stm32f407.instructions.md`：MCU开发规则
  - `.github/instructions/drone-c-conventions.instructions.md`：C代码规范
  - `/memories/repo/dev-log.md`：本开发日志
  - `/memories/repo/project-structure.md`：项目模块结构
  - `/memories/repo/architecture.md`：架构决策记录

### 阶段0.5：手册审查与配置纠错（2026-05-10）

**手册来源**：`数据手册/匿名通信协议V7.pdf` + `数据手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`

**发现的初始配置错误/遗漏**：
- 协议文件缺少大量数据帧ID：`0x02`/`0x05`/`0x08`/`0x09`/`0x0A`/`0x0B`/`0x0C`/`0x0E`/`0x21`/`0x32`/`0x51`/`0xA0`/`0xA1`
- 缺少硬件地址完整定义（0x22光流/0x30 UWB/0x10数传）
- 0x34测距帧距离字段类型错误（协议规定U32，代码写了s32）
- 缺少CMD类别A/B/C限制系统（B类不能在姿态模式用，C类只能程控模式）
- 0x41有效性表完全缺失（各字段按飞行模式的响应规则）
- 校验公式参考错误（应为 `len+4` 循环，不是 `len-2`）
- AUX1模式映射遗漏（1200-1400和1600-1800是失控保护区间）
- E0帧LEN=11未说明

**已修复**：所有上述问题已在阶段0.5更新到配置文件中

**待验证（须硬件测试确认）**：
- `LX_FC_Fun.c` 中一键起飞使用 CID=0x01/CMD0=0x01/CMD1=0x02，但协议V7.15描述为 CID=0x10/CMD0=0x00/CMD1=0x05。代码可能基于早期协议版本，以源码为准，实际串口抓包验证

**下一步计划**：
- [ ] 深入阅读 `ANO_DT_LX.c` 发送部分完整实现
- [ ] 深入阅读 `LX_FC_Fun.c` 所有功能函数实现
- [ ] 制定阶段1开发计划（基础飞行控制验证）


### 阶段0.6：0xA0字符串日志发送能力补齐（2026-05-15）

**完成的工作**：
- 在 `FcSrc/ANO_DT_LX.c/h` 增加 `String_Info_Send(u8 dest_addr, const char *str)`
- 按匿名协议直接组 `0xA0` 字符串帧，通过现有 `UartSendLXIMU` 链路发送
- 采用固定上限 `STRING_INFO_MAX_LEN=48`，超长字符串自动截断，避免动态内存
- [2026-05-15] [需要验证匿名上位机0xA0字符串日志链路] → [原工程无User_Task侧独立A0测试任务，无法区分函数/协议/链路问题] → [在FcSrc/User_Task.c新增低频静态任务user_a0_log_test_task，每500ms通过String_Info_Send(SWJ_ADDR, "A0_LOG_TEST_n")发送ASCII日志；开关与周期宏放在User_Task.h，默认可直接上板验证]
- [2026-05-15] [匿名上位机抓包里始终看不到0xA0文本帧] → [抓包中反复出现的“A0 8C”只是`AA AF 30 17 ...`这类帧的SC/AC校验尾字节，不是真正的`ID=0xA0`；同时0xA0日志作为“下位机发给上位机”的帧，目标地址应优先使用`0xAF`] → [将User_Task.h中的`USER_A0_LOG_TEST_DEST`从`HW_ALL`改为`SWJ_ADDR`，后续实机重新验证IMU桥接是否会放行0xA0]


### 阶段0.8：0xA0 LOG 双路径验证成功（2026-05-15）

**背景**：之前多轮调试始终在匿名上位机看不到 0xA0 日志，最终确认根因是**飞控断电重启问题**（见下方教训），与代码无关。

**已验证可用的两种 LOG 发送方案**：

#### 方案A：UART2 直连数传（推荐，最简单可靠）
- **路径**：STM32 UART2 (PD5 TX) → UTI数传（空中端）→ 数传（地面端）→ USB → 匿名上位机
- **波特率**：500000（`DrvUart2Init(500000)` 已在 `All_Init()` 中初始化，无需额外配置）
- **关键函数**（位于 `FcSrc/User_Task.c`）：
  ```c
  static void Log_Send_Uart2(u8 color, const char *str)
  // 直接构造 0xA0 帧调用 DrvUart2SendBuf()，绕过 IMU
  ```
- **优点**：不经过凌霄 IMU，不受 IMU 固件转发白名单限制，颜色显示正常（验证：绿色 `STRING_INFO_COLOR_GREEN=2`）
- **缺点**：占用 UART2，需额外一组数传硬件连接

#### 方案B：UART5 → 凌霄IMU → 数传（IMU自带链路）
- **路径**：STM32 UART5 → 凌霄IMU → IMU内置数传 → 匿名上位机
- **关键函数**（位于 `FcSrc/ANO_DT_LX.c`）：
  ```c
  void String_Info_Send(u8 dest_addr, u8 color, const char *str)
  // 写入 s_log_color/s_log_str，设置 dt.fun[0xa0].WTS=1，由 Check_To_Send 调度发出
  ```
- **注意**：凌霄 IMU 固件**会转发** 0xA0 帧（已实机验证），颜色显示正常（验证：红色 `STRING_INFO_COLOR_RED=1`）
- **目标地址**：使用 `0xFF`（广播），IMU 正常转发

**协议格式**（两种方案均需遵守）：
```
0xAA | 0xFF | 0xA0 | LEN | COLOR(u8) | 字符串... | SC | AC
```
其中 `LEN = 1 + 字符串长度`（包含 COLOR 字节），`STRING_INFO_MAX_LEN` 设为 **43**（避免超出 `send_buffer[50]`）。

---

### 阶段0.7：agent 配置可靠性加固（2026-05-15）

**完成的工作**：
- 在 `.github/copilot-instructions.md` 新增“官方手册优先原则”，明确遇到不确定项必须先查工作区 `用户手册/` 下官方 PDF
- 在 `.github/instructions/lingxiao-protocol.instructions.md` 新增同样的“官方手册优先原则”，并补入 `0xA0` 条目
- [2026-05-15] [抓包持续看不到任何真实`ID=0xA0`帧] → [回查`用户手册/匿名通信协议V7.pdf`第10页后确认：0xA0 的 DATA 不是“纯字符串”，而是 `COLOR(u8)+STR`，且协议示例目标地址为 `0xFF`；此前测试代码少发了COLOR字节，并把目标地址改成了`0xAF`] → [已将 `String_Info_Send` 修正为 `dest_addr + color + str` 组帧，测试任务默认改回 `HW_ALL` + 黑色文本，等待重新烧录验证]

- 通过读取 `用户手册/匿名通信协议V7.pdf` 确认：`0xA0` 官方定义为“LOG打印功能--字符串”，不是仅靠历史记忆补写
- 在 `/memories/drone-lingxiao-rules.md` 固化“手册优先、memory/规则冲突时以官方手册为准”的行为规则

**额外修正**：
- 本工作区实际手册目录名为 `用户手册/`，后续记录统一使用该路径，不再写成 `数据手册/`


**使用建议**：
- 若希望经 `UTI -> 凌霄IMU -> 匿名上位机` 观察日志，优先使用上位机地址 `0xAF`
- 建议从 `User_Task.c` 或用户状态机中按事件触发发送，避免在1ms任务里高频刷屏

---

## 问题与解决方案记录

> 格式：[日期] [问题描述] → [原因] → [解决方案]

- [2026-05-15] [烧录新代码后上位机始终看不到 0xA0 LOG，反复修改代码均无效] → [**飞控烧录后未断电重启**，STM32 没有复位，代码没有真正运行新版本，旧代码一直在跑] → [**烧录完成后必须手动断电重启飞控**，不能只靠调试器复位或软件复位；下次遇到"代码没问题但功能不生效"优先怀疑这个原因]

---

### 阶段1（代码架构）：三轴联合PID任务 pid_3d_task（2026-05-21）

**完成的工作**：
- `FcSrc/User_Task.h`：新增 PID3D_* 宏配置块（含目标坐标、各轴速度限制、合速度限制、各轴独立PID参数、观测比例、前置定高参数），默认 `PID3D_EN=0`（不编译）
- `FcSrc/User_Task.c`：
  - 添加 `#include "Ano_Math.h"`（合速度限幅用 `my_sqrt`）
  - 新增 `s_3d_pid_x/y/z`、`s_3d_obs_x/y/z` 等 14 个文件作用域静态变量（`#if PID3D_EN` 包围）
  - `pid_stop_output_now()` 扩展：增加三轴PID复位（`#if PID3D_EN` 包围）
  - 新增 `pid_3d_task(u8 *step)` 函数（`#if PID3D_EN && #if PID_TEST_EN` 双层包围）
  - `UserTask_OneKeyCmd()` CH6 触发段改为 `#if PID3D_EN` 条件切换：PID3D_EN=1 调用 `pid_3d_task`，PID3D_EN=0 继续调用原 `pid_ground_test_task`
- **编译验证**：`PID3D_EN=0` 时 zero errors（Intellisense验证）

**验收标准已达到**：
- `PID3D_EN=0`：行为与修改前完全一致，不引入任何新代码
- `PID3D_EN=1`：CH6>1700 触发三轴联合PID，含前置定高等待、合速度限制、到位确认

---

## 桌面 GUI 上位机项目（2026-05-25 启动）

> 长期项目计划见 `/memories/session/plan.md`，跨天会话先读它。
> 推进规则：**前一阶段未验收，不进入下一阶段**；用户未明说进入下一阶段时 AI 不擅自推进。

### 阶段 A：项目骨架 — ✅ 已验收（2026-05-25）

**已创建**：
- `gui/__init__.py`、`gui/{io,services,widgets,commands}/__init__.py`（占位包）
- `gui/requirements.txt`：PySide6
- `gui/io/protocol.py`：薄壳 import `groundTest/ano_protocol.py`（sys.path 注入）
- `gui/io/serial_worker.py`：QThread 包 `Win32Serial`，TX 队列槽 + RX 解析循环 + 信号上抛（connected/disconnected/error/frame_received/bytes_in/bytes_out）
- `gui/main.py`：占位主窗口 1200x800，菜单"文件→退出"，状态栏；启动 SerialWorker 线程；closeEvent 干净退出
- `gui/README.md`、`gui/_smoke_phase_a.py`（自测）

**关键决策/踩坑**：
- [2026-05-25] `create_file` 在 Windows 中文系统会以 **GBK** 编码写文件，最初统一加 `# -*- coding: utf-8 -*-` 导致 `SyntaxError: 'utf-8' codec can't decode byte 0xb0` → 改为 `# -*- coding: gbk -*-` 与 `groundTest/ano_protocol.py` 对齐 → 教训：本仓库所有新建含中文的 .py 一律用 `coding: gbk` 头
- [2026-05-25] `pip install PySide6`（无前缀）装到了非工作环境的 Python，导致 `ModuleNotFoundError` → 用 `C:/Users/20399/.../Python313/python.exe -m pip install PySide6` 显式指定解释器 → 教训：本机 Python 多版本，安装命令必须用绝对路径解释器
- 串口 IO 严格隔离设计：UI 线程 → `QMetaObject.invokeMethod(worker, "send_bytes", QueuedConnection)` → worker 线程串行执行，天然防 TX 冲突

**验收**：
- import 链 OK；`build_f1_xy(0xFF,1234,-4562)` 输出 `aafff104d2042eee90a1`，与 dev-log 阶段1 固化字节序完全一致
- 自测脚本 `python -m gui._smoke_phase_a`：窗口弹出 → 2s 后自动关闭 → 进程返回 0、stderr 无 Traceback

**待做（阶段 B 启动前由用户明确指令）**：
- 串口连接栏 + 日志/报警基础设施 + 全局 excepthook + config.json 持久化

---

## GUI 桌面上位机 — 阶段 B：串口连接 + 日志/报警基础设施 — ✅ 已验收（2026-05-25）

**新增文件**：
- `gui/services/config_service.py`：JSON 持久化（last_port/window_size/window_pos/log_dir/log_filter_level）
- `gui/services/log_service.py`：`LogLevel` 四级（DEBUG/INFO/WARN/ERROR）+ `LogEntry` + Qt 信号 `entry_added` + 文件写入（utf-8-sig，QMutex 保护）
- `gui/services/alarm_service.py`：三级报警，ERROR 通过 `_request_error_dialog` 私有信号 + QueuedConnection 跨线程到主线程弹模态窗
- `gui/io/serial_ports.py`：winreg 枚举 `SERIALCOMM`，**只读注册表不触碰驱动**，避免数传 SetCommState 误触发
- `gui/widgets/connection_bar.py`：可编辑 QComboBox + 刷新 + 只读"波特率 500000" + 连接/断开二态按钮 + LED + 提示；记忆 last_port 写回 ConfigService
- `gui/widgets/log_view.py`：QTextEdit + HTML 着色（按 LogLevel.color_hex）+ 工具栏（等级过滤/暂停滚动/清屏/导出）+ `_MAX_BLOCKS=5000` 行数裁剪
- `gui/main.py`：**完整重写**，装配服务层 + 状态栏(RX/TX 计数 + 连接指示) + 菜单(导出日志/打开日志夹/关于) + 全局 `sys.excepthook` → AlarmService.error + closeEvent 持久化窗口几何
- `gui/_smoke_phase_b.py`：自动化烟测脚本

**关键设计决策**：
- 选 **QTextEdit** 而非 QPlainTextEdit：要 HTML 着色；上位机日志 <10Hz 不需要极限性能；行数超 5000 自动裁剪头部
- **红色 0xA0 (color=1) 默认归 WARN** 而非 ERROR：避免飞控 OF 提示等良性红字反复弹窗；命令层（如阶段 D 的 `UNK` 拒绝）可显式升级到 ERROR
- ConnectionBar **不持有串口对象**，纯发 `connect_requested`/`disconnect_requested` 信号，由 MainWindow 用 `QMetaObject.invokeMethod(worker, "...", Qt.QueuedConnection, Q_ARG(str, port))` 跨线程派发
- 弹窗必须跨线程：AlarmService 通过私有 Signal + QueuedConnection 把 `_show_error_dialog` 调用排到主线程，**杜绝在 SerialWorker 线程构造 QMessageBox 导致崩溃**
- 全局异常钩子 `sys.excepthook`：未捕获异常 → stderr + AlarmService.error，**绝不静默崩溃**

**验收（烟测自动化）**：
1. 主窗口 1200×800 显示，三区布局（连接栏/命令面板占位/日志区）+ 状态栏
2. 三级日志（DEBUG 被过滤 / INFO / WARN）按 HTML 着色显示
3. 日志文件 `gui/logs/gui_20260525_234324.txt` 写入 781B（含 BOM 头），记事本可直接打开看中文
4. ConfigService 持久化到 `gui/config.json`：last_port=COM_TEST、window_size=[1200,800]、window_pos=[254,80]
5. 模拟 `_on_serial_connected("COM_TEST")` / `_on_serial_disconnected` 路径无异常，连接栏 LED 和状态栏同步更新
6. ConnectionBar 端口枚举返回 0（虚拟机无 COM 口），不抛异常
7. `python -m gui._smoke_phase_b` 返回 0、stderr 无 Traceback

**问题与解决**：
- [2026-05-25] [`create_file` 报"File already exists"on `gui/main.py`] → [阶段 A 已经创建过 main.py，需要覆盖式重写] → [先 `Remove-Item` 删旧文件再 `create_file`，不要试图用 replace_string_in_file 替换整个文件内容] → **教训：替换整文件直接 rm 再 create，比拼接 oldString 整段文本更可靠**
- [2026-05-25] [初版烟测脚本用 `win._alarm._popup_on_error = False` 试图关闭弹窗] → [AlarmService 根本没有这个字段，弹窗禁用应用 `error(..., popup=False)` 关键字参数] → [改为不主动调用 `alarm.error`，避免触发弹窗] → **教训：写 stub 字段前先 grep 确认存在**

---

## GUI 桌面上位机 — 阶段 C：CommandRegistry + 0xF1 命令面板 — ✅ 已验收（2026-05-25）

**新增文件**：
- `gui/services/command_registry.py`：`Command` ABC（cmd_id/name/category/requires_confirm/ack_timeout_ms + build_frame/parse_ack/create_panel/describe_params）+ `AckResult` 冻结数据类 + `CommandPanelBase` Widget 基类 + 全局 `REGISTRY` 单例（register/get/all/categories/in_category）
- `gui/services/ack_matcher.py`：`AckMatcher(QObject)`，`track(cmd, desc) → token` 用 QTimer 单次超时（`ack_timeout_ms` 决定，≤0 不计时），`handle_text(text)` 按 token 升序 FIFO 遍历挂起，首次 `parse_ack` 非 None 即 `ack_matched` 信号发出并结清；信号 `request_tracked/ack_matched/request_timeout`；`cancel/cancel_all/pending_count`
- `gui/commands/cmd_f1.py`：`CmdF1`（cmd_id=0xF1, name="链路验证 F1"，requires_confirm=False, ack_timeout_ms=1500），build_frame 复用 `ano_protocol.build_f1_xy`，parse_ack 用 `^F1\s*:\s*X\s*=\s*(-?\d+)\s+Y\s*=\s*(-?\d+)` 正则，命中返回 `AckResult(ok=True, level=INFO, message=...)`；`F1Panel` 两 QSpinBox（-32768..32767，默认 1234/-4562）+ 发送 + 重发上次按钮 + 状态标签；`set_enabled_for_link(linked)` 控制按钮使能与状态色
- `gui/commands/__init__.py`：仅 `from . import cmd_f1` 一行触发自注册；**新增命令只需在此 import 一行**
- `gui/widgets/command_panel.py`：`CommandPanel` 两级 ComboBox（分类→命令）+ `QStackedWidget` 懒构造面板；面板 `send_requested` 转发为本控件的 `command_send_requested(int cmd_id, dict params)`；`set_enabled_for_link` 广播到所有已构造的子面板
- `gui/main.py`：导入 `AckMatcher/REGISTRY/CommandPanel/gui.commands`；中央占位 QFrame 换成 `CommandPanel`，并创建 `self._ack = AckMatcher(self)`；`_on_serial_connected/disconnected/error` 联动 `set_enabled_for_link` 与 `_ack.cancel_all`；0xA0 入站路径调用 `self._ack.handle_text(text)`；新增三槽 `_on_command_send_requested/_on_ack_matched/_on_ack_timeout`，封装"敏感命令确认 → build_frame → AckMatcher 先登记后入队 send_bytes"流程
- `gui/_smoke_phase_c.py`：自动化烟测 6 项

**关键设计决策**：
- **AckMatcher.track 先登记再发送**：避免极快回执先到导致漏匹配（即使是 USB-CDC 也可能在 1ms 内回 0xA0）
- **每条 0xA0 文本只匹配一个挂起**：按 token 升序 FIFO，首中即结清，绝不跨命令乱抢
- **不自动重发**（用户钦定规则）：超时只发 `request_timeout` 信号→ AlarmService.warn + 用户手动点"重发上次"
- **扩展接入点收敛到 1 行**：新增命令 → 写 `gui/commands/cmd_xxx.py`（含 `REGISTRY.register(CmdXxx())`）+ 在 `gui/commands/__init__.py` 加 `from . import cmd_xxx`，UI 框架代码零修改
- **CommandPanel 懒构造**：切到某命令首次才 `cmd.create_panel()`，避免启动时全量加载所有面板

**烟测验证（python -m gui._smoke_phase_c, exit=0）**：
1. REGISTRY 自注册 0xF1 成功
2. `CmdF1.build_frame({"x":1234,"y":-4562}).hex() == "aafff104d2042eee90a1"`（与阶段1 固化字节序完全一致）
3. parse_ack 正确识别 "F1: X=1234 Y=-4562"，正确拒绝 "P01=30.0"
4. AckMatcher track + handle_text → ack_matched 触发，pending_count 归零
5. F1Panel 在 link=False 时发送按钮禁用，link=True 时使能
6. AckMatcher 短超时（200ms）+ QEventLoop 等待 400ms → request_timeout 触发

**问题与解决**：
- [2026-05-25] [烟测中创建独立 AckMatcher 实例 + QTimer 超时路径 → `STATUS_STACK_BUFFER_OVERRUN (0xC0000409)`] → [PySide6 中临时 AckMatcher 与 lambda slot 在事件循环中的生命周期问题；非产品 bug，但测试代码不稳] → [测试中复用 `win._ack`，不再创建新 AckMatcher 实例] → **教训：QObject 子类含 QTimer 的实例不要在临时函数局部短期持有；测试中复用主窗口的实例即可**
- [2026-05-25] [`replace_string_in_file` 误把 `_on_menu_export` 方法体清空导致 SyntaxError] → [想分两步重构，第一步删除旧体，第二步插入新体，但被 token 限制中断] → [一次性 replace 同时包含旧 + 新内容，不要拆步] → **教训：方法重构必须单次 atomic replace，不留空函数体中间态**

**待做（阶段 D 启动前由用户明确指令）**：
- `gui/commands/cmd_f2.py`：参数写入命令（敏感，requires_confirm=True），三态回执（OK/CLP/UNK）颜色映射到日志

---

## 当前总进度（2026-05-25）

| 功能 | 状态 | 备注 |
|------|------|------|
| 0xA0 LOG 发送能力 | ✅ 完成 | UART2直连和UART5→IMU两路均验证 |
| X轴PID任务（CH6触发） | ✅ 完成 | 含前置定高阶段，已实飞验证 |
| Y轴PID任务（CH10触发） | ✅ 完成 | 已实飞，收敛 |
| Z轴PID任务（CH7触发） | ✅ 完成 | 代码实现，待充分实飞验证 |
| 遥控全通道识别（RC诊断） | ✅ 完成 | RC_DIAG_ALL_CHANNELS，10通道 |
| RC override 防干扰 | ✅ 完成 | PID任务激活期间屏蔽RC速度覆写 |
| 油门冲突修复（X/Y vs Z） | ✅ 完成 | xy_active固定thr=500，z_active不固定 |
| 多轴防同时触发告警 | ✅ 完成 | pid_multi_axis_warned单次告警 |
| 观测比例分轴标定 | ✅ 完成 | PID_OBS_VX_SCALE_X/Y/Z独立 |
| 波形分析Python脚本 | ✅ 完成 | wave/analyze_wave.py，8个分析模块 |
| notch滤波配置 | ❌ 未做 | 频谱检测到19.3Hz主峰，需飞控参数配置 |
| Y轴KD调参（超调59%） | ⏳ 待飞 | 待下次实飞验证减KP/增KD效果 |

---

### 阶段1：X/Y/Z 轴解耦 PID 位移任务（2026-05-18 ~ 05-20）

**功能说明**：
- X轴任务：CH6>1700 触发，Pitch 方向推进，目标 50cm
- Y轴任务：CH10>1700 触发，Roll 方向推进，目标 50cm
- Z轴任务：CH7>1700 触发，垂直速度控制，目标 50cm
- 三轴完全解耦，不可同时触发（告警）

**参数（User_Task.h）**：
- `PID_TARGET_X/Y/Z_CM = 50.0f`
- `PID_OBS_VX_SCALE_X/Y = 0.90f`，`Z = 1.00f`
- `kp=1.10, ki=0.0043, kd=0.03, vel_limit=25cm/s`

**问题与解决**：
- [2026-05-18] [Y轴响应极慢，log无vel_y输出] → [ANO_LX.c的RC_Data_Task()在100Hz循环中每帧覆写vel_y=0（非程控模式下的清零逻辑）] → [在RC_Data_Task()中扩展pid_task_xy_active判断至三个触发通道，PID激活期间跳过RC速度覆写] → **教训：RC 100Hz覆写优先级高于User 50Hz写入，任何速度指令冲突必须先检查ANO_LX.c的RC任务**
- [2026-05-18] [Z轴任务与X/Y任务共用xy_active，起飞时油门错误固定] → [Z轴PID只需屏蔽RC vel覆写，不需要固定thr=500（Z轴自己控制throttle）] → [拆分为pid_task_xy_active和pid_task_z_active，各自处理逻辑分离] → **教训：XY保高和Z控高机制完全不同，必须拆开**
- [2026-05-18] [日志频繁出现"PID seq: release all switches"误告警] → [该保护逻辑原意是检查多轴同时触发，但逻辑写错导致每次都触发] → [移除序列保护逻辑，仅保留多轴同时检测（pid_multi_axis_warned单次告警）] → **教训：安全逻辑必须在地面充分仿真，不能只靠逻辑推理**
- [2026-05-19] [实飞X轴仅移动约30cm，日志显示50cm，误差极大] → [速度积分观测比例scale=1.55偏高，真实积分距离比飞控估算小] → [公式：scale_new=scale_old×(D_real/m_done)，实测30cm/51cm≈0.59，scale_new≈1.55×0.59≈0.91，设为0.90] → **教训：上线前必须用卷尺标定观测比例，不能直接信任飞控积分**

---

### 阶段2：全通道遥控诊断（RC Diagnostic）（2026-05-19）

**功能**：`rc_diag_task()` 检测 CH1~CH10 变化，超阈值打印日志
**开关**：`RC_IDENTIFY_SAFE_MODE=1` 时禁止一切任务动作，仅输出诊断
**日志格式**：`CH7_AUX3:1988 -> aux3`

---

### 阶段3：波形自动分析工具（2026-05-20）

**文件**：`wave/analyze_wave.py`
**功能模块**（8个）：
1. basic：总览/姿态/IMU/高度图
2. vibration：ACC RMS振动评分
3. fft：Welch PSD频谱 + notch建议
4. spectrogram：STFT时频图
5. distribution：直方图 + 3σ
6. pid_response：阶跃响应自动检测（rise/OS/settle）
7. coupling：Pearson 轴间耦合
8. anomaly：突变/卡死/离群事件

**实飞波形分析结论（2026-05-20）**：
- X任务：19.3Hz 电机振动极强（ACC_Y PSD能量比中位高206×）→ 需加notch@19Hz
- Y任务：振动RMS=126（X任务52），主频6.7Hz，说明两次飞行油门/转速差异大
- Y任务ROL超调59.2% → 减KP或增KD
- X/Y轴ROL~PIT耦合0.488（Y任务） → 检查重心对称性
- 脚本已知问题：小幅值阶跃（<1°）被误判为超调，需加`abs(amp)<1.0`过滤

---

## 已验证的关键知识点

### 协议相关
- 帧头固定`0xAA`，目标地址`0xFF`（广播），本机地址`HW_TYPE=0x61`
- SC/AC校验范围：从`0xAA`帧头到DATA区结束（不含校验字节本身）
- CMD发送前必须检查`dt.wait_ck == 0`，否则会丢失前一个CMD的确认
- 程控模式`fc_sta.fc_mode_sta == 3`才能响应`0x41`实时控制帧

### 调度器相关
- 裸机时分调度，无RTOS
- UserTask在50Hz（Loop_50Hz），周期20ms
- 状态变量用`static`修饰，保持跨调用状态

### 已知的坑
- `ANO_DT_LX.c`中`0x03`（欧拉角）和`0x04`（四元数）的`else if`条件原本**写错了**（两个都是`0x03`），导致四元数数据永远不会被解析——**已于2026-05-15修复**，四元数分支已改为 `0x04`

---

## 2026-07-19：基础工作原理记忆升级

[2026-07-19] [用户补充凌霄飞控最基础系统边界，要求作为最高优先级知识库继承] → [此前记忆中已有“STM32F407 + 凌霄 IMU 闭源核心”的方向，但缺少独立最高优先级文件、会话启动强制读取入口、匿名系列传感器资料归档规则和数传数据所有权提醒] → [新增 `CODEX_FOUNDATION.md`，并同步更新 `AGENTS.md`、`CODEX_MEMORY_INDEX.md`、`CODEX_SESSION_START.md`、`CODEX_UPDATE_RULES.md`、`CODEX_INHERITANCE_AUDIT.md`、`memories/user/drone-lingxiao-rules.md`、`memories/repo/architecture.md`、`memories/repo/project-structure.md`、`project_docs/sensors/README.md`] → [后续开发必须先按 STM32F407 可编程中央总控、凌霄 IMU 闭源传感/融合/控制核心、STM32 只通过协议帧影响 IMU 输入、数传接凌霄 IMU 链路这四个事实分析数据所有权；涉及外部匿名系列传感器时先查官方/权威资料并落本地知识库，不能凭经验猜字段]
[2026-07-19] [用户要求配置 Git/项目历史回滚、进度记忆与备份硬规则] → [用户明确要求：回滚必须始终由用户亲手做；Codex 做的东西要实时更新项目进度和记忆；必要时常备份开发代码，防止误回滚导致代码消失] → [新增 `CODEX_GIT_BACKUP_RULES.md`；同步更新 `AGENTS.md`、`CODEX_SESSION_START.md`、`CODEX_MEMORY_INDEX.md`、`CODEX_UPDATE_RULES.md`、`CODEX_INHERITANCE_AUDIT.md`、`memories/user/drone-lingxiao-rules.md`] → [后续 Codex 不得执行 `git reset/restore/checkout --/revert/clean` 等回滚或清理历史命令；完成可验证成果或纠错必须更新 `dev-log.md`；高风险/多文件/飞控安全/协议/GUI大阶段修改前必要时备份源码补丁和关键文件到 `记忆迁移/codex记忆迁移/backups/`]
[2026-07-19] [树莓派 ↔ STM32 正式对接第一阶段落地，要求先修正文档、明确 USB-TTL 接线、实现 0xF5 只解析/日志、不控飞] → [原 `树莓派飞控对接文档.md` 未覆盖 USB-TTL 优先接线，Python 示例把 `0x80000000` 当 signed `<i` 打包会越界，且源码只分发 `0xF1/0xF2/0xF3`，`0xF5` 尚未进入解析] → [修改前备份到 `记忆迁移/codex记忆迁移/backups/20260719-155019-rpi-f5-stage1/`；新增 `Uplink_Cmd` 的 `0xF5` 快照解析、长度/校验错误计数、`0xA0` 限频 ACK 日志、`Uplink_Log()` 全局异步日志接口；`ANO_DT_LX.c` 分发 `0xF5` 并记录校验失败；`groundTest/ano_protocol.py` 新增 `build_f5_position()`；新增 `groundTest/send_f5.py` 与 `groundTest/test_f5_frame.py`；升级根目录和迁移包 `树莓派飞控对接文档.md`、`数据帧.md`、`groundTest/README.md`] → [已离线验证：`python3 ANO_LX_FC/groundTest/test_f5_frame.py` 通过，`python3 -m py_compile ...` 通过，`bash scripts/build.sh` 通过；构建仅保留历史已有 CMSIS/旧静态声明/未用函数等告警；待用户用 USB-TTL 实机验证 `F5 #... c=/t=` 日志]
[2026-07-19] [用户明确树莓派 ↔ 飞控正式对接不再是单线开发，而是双端同步沟通、阶段闸门推进] → [若只按普通单线开发记忆，后续 Codex 可能一次性继续写超时/PID/0x41/实机控制，忽略树莓派侧每阶段验证结果] → [备份到 `记忆迁移/codex记忆迁移/backups/20260719-162748-sync-gated-workflow/`；更新 `AGENTS.md`、`CODEX_SESSION_START.md`、`CODEX_MEMORY_INDEX.md`、根目录和迁移包 `树莓派飞控对接文档.md`，新增“双端同步阶段闸门”硬规则：Codex 每次只完成一个飞控侧小阶段并汇报，再明确树莓派侧要跑的命令、期望日志和失败材料；用户回传树莓派侧通过结果后，才能推进下一阶段] → [后续树莓派/0xF5/SLAM/视觉目标联调必须先确认当前阶段和双方状态；未收到树莓派侧固定帧、方向、flags、SLAM 当前坐标等对应验收结果前，不得跳级接 PID、0x41 或实际飞行输出]
[2026-07-19] [树莓派侧回报步骤1-3完成，黄金0xF5帧已正确发送，要求飞控侧完成UART2 RX、0xF5解析、0xA0 ACK] → [发现STM32F407 `Drv_Uart.c` 中UART2 RX原先挂 `NoUse`，即使PD6收到USB-TTL字节也不会进入上行解析；原有 `ANO_DT_LX_Data_Receive_Prepare()` 是UART5/IMU链路解析器，不能和UART2共享静态状态] → [修改前备份到 `记忆迁移/codex记忆迁移/backups/20260719-163959-uart2-f5-ack/`；将 `U2GetOneByte` 改为 `Uplink_Cmd_Uart2RxByte`；新增UART2专用 `0xF5` 状态机，校验 `AA 61/FF F5 19`、31B总长和SC/AC；合法帧解析6个s32小端cm和flags，立即经UART2/PD5回 `0xA0` 绿色ACK `F5 #... f=03 c=... t=...`；修复UART2发送完成后 `TxCounter/count` 归零，避免连续ACK缓冲累计] → [已验证：`git diff --check` 通过，`bash scripts/build.sh` 通过并生成 `build-gcc/ANO_LX.hex/.bin/.elf`；本阶段仍不接PID、不写`rt_tar`、不发`0x41`、不改变飞行输出；下一步等待树莓派运行 `send_f5.py` 验证是否收到ACK]
[2026-07-19] [树莓派侧完成固定帧ACK、X/Y/Z方向帧ACK、flags失效帧ACK验收，准备进入真实SLAM当前坐标接入] → [实测ACK：固定帧 `F5 #1 f=03 c=0,0,80 t=100,0,80`；X方向 `t=100,0,0`、Y方向 `t=0,100,0`、Z方向 `t=0,0,100` 共约90帧连续ACK；`--slam-invalid` 得到 `f=02`，`--target-invalid` 得到 `f=01`] → [结论：STM32串口链路、0xF5字段顺序、s32小端cm解析、flags字节解析均与树莓派发送一致；这只证明协议字段未被交换/取反，实际世界坐标到飞控坐标系的“X前/Y左/Z上”转换仍由树莓派SLAM接入阶段用真实运动验证] → [下一阶段只允许接入真实SLAM当前位置：建议树莓派发送 `cur=SLAM厘米坐标`、`tar=cur` 且 `TARGET_VALID=0`，SLAM未收敛/丢失时清 `SLAM_VALID=0`；STM32继续只ACK日志，不接PID、不控飞]
[2026-07-19] [用户说明树莓派真实SLAM当前坐标测试正在进行，要求先不要继续开发，先讲清ROS导航/激光雷达坐标与飞控位置PID对齐方法] → [当前阶段状态需保持：等待树莓派回传真实SLAM `cur` 静态/手动移动日志，不得跳级写PID、误差干运行或实际控制输出] → [讲解边界：树莓派/ROS负责SLAM定位、路径规划和坐标转换，飞控STM32负责读取0xF5快照作为位置观测、做位置PID、输出`rt_tar.vel_x/y/z`并通过0x41交给凌霄IMU；坐标对齐建议先锁yaw，用起点为原点，基于ROS `map->base_link`初始yaw或手动前/左移动标定2x2变换，把ROS map坐标转为飞控X前/Y左/Z上cm坐标后再进入PID]
[2026-07-20] [J-Link/OpenOCD烧录排查：CMSIS-DAP脚本找不到设备，J-Link低速脚本初期写flash时报algorithm/CRC timeout] → [确认当前USB设备为SEGGER J-Link `1366:0105`；新增/使用J-Link低速no-SRST配置，SWD固定100kHz；用户断电、拔J-Link、重新上电并重插后，`probe-jlink.sh`可稳定识别STM32、VTarget=3.3V、SWD DPIDR正常；`flash-jlink.sh`不再报Programming Failed，但OpenOCD `verify_image`/CRC类算法在该环境可能因目标RAM算法执行超时而不可靠] → [通过重新只读dump出的`artifacts/jlink/flash_head_now.bin`与本地`build-gcc/ANO_LX.bin`头256字节逐字节比较无差异，且本地Reset_Handler=`0x08008364`与OpenOCD halt时PC一致，结论：当前flash至少头部向量表已是新固件，下一步应以GUI/0xF6实测作为功能验收，不要反复盲目烧录；若后续仍需强校验，优先用dump小段/关键符号比对或接NRST后connect-under-reset]
[2026-07-20] [0xF6运行时抓包验收：用户说明树莓派已运行导航和通信，要求抓数据判断烧录是否成功] → [通过匿名数传`/dev/ttyACM0 @ 500000`按项目`FrameParser`抓包20秒，保存到`artifacts/capture/telemetry_20260720-105035.jsonl`和summary；共收到`raw_bytes=152230`、有效帧`13487`，包含0x01/0x02/0x03/0x04/0x05/0x06/0x07/0x08/0x09/0x0D/0x0E/0x20/0x30/0x40/0x41/0xFA等正常数传帧，但`F6_COUNT=0`、`A0_COUNT=0`] → [结论：GUI/数传侧不能确认0xF6新功能已生效；如果树莓派侧此时仍能收到UART2 ACK `F5 #...`，说明STM32正在接收0xF5但0xF6经IMU转发链路未打通；如果树莓派侧也无ACK，优先查0xF5未到STM32或当前运行固件不是新版本。当前J-Link设备未出现在`lsusb`，无法继续做只读flash代码段比对] → [教训：验证烧录成功必须用“代码内容读回 + 运行时新行为”双证据；只看到普通数传帧不等于新固件生效，0xF6阶段的闸门标准是`0xF5输入存在`且GUI抓到约10Hz `0xF6`镜像；⚠️ 安全影响：本轮只抓数传数据和记录结论，未修改飞控控制逻辑]
[2026-07-20] [更换Horco CMSIS-DAP后仍无法DAP烧录] → [新设备`faed:4873 Horco CMSIS-DAP`已被Linux识别为CMSIS-DAPv2复合设备：if0/if1为CDC ACM串口，if2为`Horco CMSIS-DAP v2` bulk接口；初始`unable to find matching CMSIS-DAP`根因是raw USB权限不足，OpenOCD debug显示`0xfaed:0x4873 Access denied`；临时`chmod 666 /dev/bus/usb/003/084`后权限通过，但OpenOCD只能在`usb_bulk + interface 2`打开设备，随后第一条`CMSIS-DAP command CMD_INFO failed`；接口矩阵验证：if0/if1找不到设备、hid找不到设备、auto/if2均CMD_INFO失败；ModemManager/brltty/ttyACM1占用均排除] → [新增`openocd/stm32f407-horco-cmsis-dap-v2-no-srst.cfg`，锁定`cmsis-dap backend usb_bulk`、`vid_pid 0xfaed 0x4873`、`usb interface 2`、低速1000kHz；新增`scripts/probe-horco-dap.sh`、`scripts/flash-horco-dap.sh`、`scripts/show-horco-dap-permission.sh`用于后续复测；当前结论：Horco探针自身DAP协议响应异常/与当前xPack OpenOCD不兼容，尚未进入STM32 SWD连接阶段，不能据此判断飞控板接线或芯片状态] → [教训：DAP排障要分层：USB枚举→raw USB权限→CMSIS-DAP协议CMD_INFO→SWD DPIDR→flash写入；`unable to find matching`可能是权限，`CMD_INFO failed`是探针协议层，二者不能混为STM32烧录失败；⚠️ 安全影响：本轮只新增调试器脚本和记录，未改飞控运行逻辑]
[2026-07-20] [0xF6位置镜像调试帧现场抓包仍为0，用户提醒此前F1/F2/F3自定义控制帧经数传/IMU上行已验证成功] → [复核代码链路后确认二者不是同一方向：F1/F2/F3是PC/GUI→数传→IMU→STM32 UART5 RX，由`ANO_DT_LX_Data_Receive_Prepare()`校验后分发到`Uplink_Cmd_Dispatch()`；F6是STM32解析UART2收到的F5后，经`Uplink_Cmd_Tick()`检测`rx_cnt`变化，调用`Rpi_Position_Mirror_Send()`，再由`ANO_LX_Data_Exchange_Task()`通过UART5 TX发给IMU/数传/GUI。现场8秒抓`/dev/ttyACM0`得到`raw_bytes=61022`、有效帧`5401`，常规0x01/0x03/0x20/0x41等均存在但`F6_COUNT=0 A0_COUNT=0`；随后DAP读RAM显示`s_f5_snapshot.rx_cnt=140`且`f6_last_rx_cnt=140`，`dt.fun[0xF6].WTS=0`] → [结论：本次抓包窗口内STM32没有收到新的F5，因此F6不会重复发送；不能据此证明IMU不转发自定义下行帧，也不能否定用户已验证过的上行自定义帧。下一步必须让树莓派持续发送F5的同时抓数传并同步读RAM：若`rx_cnt`增长但`F6_COUNT=0`，再转为检查UART5 TX是否实际发出F6和IMU/数传是否过滤；若`rx_cnt`不增长，则先查树莓派串口/接线/运行脚本] → [教训：0xF6当前设计是“每收到新F5才镜像一次”，不是周期保活帧；排查必须同时记录触发源F5计数、F6发送队列状态和数传抓包，不能只看GUI等待状态]
[2026-07-20] [树莓派持续发送F5时重新抓数传，0xF6镜像帧验证通过] → [用户回传树莓派日志显示UART2 ACK编号从`F5 #142`持续增长到`F5 #247`，说明STM32正实时接收F5；随后在同一阶段抓`/dev/ttyACM0 @500000` 12秒，得到`raw_bytes=96409`、有效帧`8205`，其中`0xF6:120`，镜像频率约`9.94Hz`，符合`UPLINK_F6_MIRROR_TICK_GAP=5`的约10Hz设计；首帧解析为`cur=(84,79,0) tar=(84,79,0) flags=0x01 rx_cnt=411 len_err=0 ck_err=0`，末帧为`cur=(60,80,0) tar=(60,80,0) flags=0x01 rx_cnt=530 len_err=0 ck_err=0`] → [结论：STM32解析F5、F6打包、UART5 TX到凌霄IMU、IMU/数传下行转发、PC侧FrameParser解析均已打通；此前`F6_COUNT=0`的根因是抓包窗口没有新的F5触发源，不是自定义下行帧不能转发。如果GUI位置测试页仍显示等待0xF6，下一步应排查GUI是否连接`/dev/ttyACM0`、位置测试页是否激活、`PositionTestWindow.on_frame()`是否收到cmd=0xF6，而不是继续改飞控协议] → [教训：0xF6阶段验收标准应改为“树莓派ACK编号增长 + 数传抓包F6_COUNT约等于发送秒数*10 + 字段解析一致”；只有三者同时满足才算链路通过]
[2026-07-20] [用户最终确认GUI位置测试“等待0xF6”的真实原因：树莓派只运行ROS导航不会自动发送0xF5，必须额外运行测试发送程序] → [此前排查中曾把“数传抓不到0xF6 / GUI等待0xF6”误导到烧录、DAP/J-Link、IMU下行转发、GUI解析等方向；根因其实是当前阶段的树莓派设计为了安全解耦：导航/SLAM节点只负责建图定位和导航能力，不默认向飞控持续发布位置控制帧；只有运行`send_slam_cur_f5.py`等测试程序时，才会把SLAM当前位置打包成0xF5发给STM32，随后STM32才会镜像0xF6给GUI] → [用户运行测试程序后，GUI“位置测试”已能看到原始解析数据，证明0xF5输入源、STM32解析、0xF6镜像、数传下行、GUI显示链路整体成立；当前主线应从烧录/链路误判切回GUI位置测试功能开发阶段，不得继续围绕烧录和下行转发反复打补丁] → [教训：后续树莓派↔飞控联调必须明确“ROS导航运行状态”和“0xF5测试发送程序运行状态”是两个独立闸门；为了安全，默认不能假设导航节点会自动给飞控发位置或目标，必须通过测试程序显式发送、看ACK和GUI原始数据后，才推进下一步GUI/坐标标定/稳定性测试；排查流程先看树莓派TX日志，再看STM32 ACK，再看数传F6，再看GUI页面]
[2026-07-20] [GUI位置测试主线恢复并完成第一版诊断页：用户确认等待0xF6根因是未运行树莓派测试发送程序后，要求从烧录/链路排障切回GUI功能开发] → [根因纠偏：ROS导航/SLAM运行状态与0xF5测试发送程序运行状态必须分开；GUI需要把“等待0xF6”直接提示成“需运行树莓派发送程序”，并提供后续黑线地面测试所需的稳定性、坐标标定和轨迹记录工具] → [修改 `gui/position_test/position_test_window.py`：实时页补链路状态提示和GUI帧计数；新增稳定性页，统计SLAM有效样本的均值/标准差/峰峰值/跳变/rx_cnt跳号；新增坐标标定页，支持O/+X/+Y三点采样，计算夹角、方向性和原始坐标到飞控X前/Y左的2D变换；新增轨迹页，支持开始/停止/清空、XY曲线、目标点显示和CSV导出；更新 `gui/position_test_master_plan.md`] → [验证：`.venv-linux` 下 `py_compile gui/main.py gui/position_test/position_test_window.py` 通过，`git diff --check` 通过；Qt offscreen注入0xF6截图验证 `artifacts/gui/position_test_waiting_hint.png`、`position_test_stability.png`、`position_test_calibration.png`、`position_test_trajectory.png`，CSV导出首行t_rel_s=0.000、40行样本正常；安全影响：仅GUI诊断，不接PID、不发0x41、不改变飞控输出；下一步现场验收必须运行树莓派测试发送程序后再看GUI四页数据]
[2026-07-20] [GUI位置测试可用性完善：用户指出坐标标定当前cur太暗太小、稳定性页语义不清且没有开始按钮、说明文字不可读] → [根因：第一版偏工程调试面板，稳定性页默认被动统计窗口样本，未明确“静止定位稳定性”用途，也没有用户级流程；QGroupBox在当前主题下说明文字对比度不足] → [修改 `gui/position_test/position_test_window.py`：坐标标定页新增产品级操作引导，按钮改为1/2/3步骤，当前cur改为亮绿色22px粗体；稳定性页改为测试流程模式，支持测试类型选择、开始测试、停止并结算、重置结果、测试时长、跳变阈值，默认语义明确为“静止定位稳定性（起飞前观测质量检查，不是飞行控制稳定性）”；表格新增抖动σ、最大摆动、漂移、判读列；说明/引导区域改为深底亮字] → [验证：`.venv-linux` 下 `py_compile gui/main.py gui/position_test/position_test_window.py` 通过，`git diff --check` 通过；Qt offscreen注入0xF6后截图验证 `artifacts/gui/position_test_calibration_polished.png` 和 `artifacts/gui/position_test_stability_polished.png`，当前cur和稳定性摘要均为明亮绿色大字，稳定性测试只在点击开始后采样；安全影响：仅GUI显示/诊断，不接PID、不发0x41、不改变飞控输出]
[2026-07-20] [GUI位置测试两个现场bug修复：页面被撑到超屏，频率始终约10Hz] → [根因1：坐标标定/稳定性页为了强调说明和状态，给长文本、大字号、`minimumWidth` 和横向扩展策略过多，叠加 `gui/config.json` 保存的异常窗口几何/旧Dock状态，导致主窗口超出屏幕；根因2：GUI原先显示的是STM32→IMU→数传→GUI的`0xF6`镜像到达频率，而不是树莓派→STM32的`0xF5`输入频率；固件中`UPLINK_F6_MIRROR_TICK_GAP=5`本来就把调试镜像限到约10Hz] → [解决：压缩位置测试页说明文字、表格列宽和长状态文本，移除`当前cur`的强制420px最小宽度，保留亮绿色大字但不再撑宽窗口；`gui/main.py`启动时把保存窗口尺寸/位置钳制到当前屏幕可见范围；`gui/config.json`恢复默认1200×800、居中并清空旧Dock状态；实时页频率改成`F5输入 / F6镜像`，用`rx_cnt`差值估算真实F5输入频率；`UPLINK_F6_MIRROR_TICK_GAP`改为2，F6调试镜像约25Hz] → [验证：`.venv-linux`下`py_compile gui/main.py gui/position_test/position_test_window.py`通过，`python3 -m json.tool gui/config.json`通过，`git diff --check`通过，`bash scripts/build.sh`通过；Qt offscreen注入60帧F6且rx_cnt每帧+2时实时页显示`50.0 / 25.0 Hz`，位置测试窗口在1100×720截图下可见，主窗口在800×800虚拟屏被钳到760×740；安全影响：F6频率仅影响GUI调试镜像，不接PID、不写`rt_tar`、不发`0x41`、不改变飞行输出；建议控制观测后续从STM32内部F5快照按20~30Hz起步，50Hz作为带宽稳定后再测]
[2026-07-20] [GUI位置测试坐标标定/稳定性排版二次修正：结果表只剩一行、点位表下方空白大、稳定性绿色摘要换成多行] → [根因：坐标标定页点位表未固定高度，结果表作为唯一stretch区域被剩余高度反向压缩；页面没有滚动容器导致小屏无法滚动查看；稳定性摘要设置了最大宽度和自动换行，左侧仍有空间时也被挤成多行，并且未开始状态写了提示句而不是纯数据] → [解决：坐标标定页加入QScrollArea，点位表固定为3行高度，结果表固定为6行高度并关闭表内纵向滚动，页面整体可鼠标滚轮查看；去掉点位表到结果表之间的无意义扩张空白；稳定性摘要取消最大宽度和wordWrap，改为横向Expanding显示纯数据，未开始时仅显示样本/有效/无效/F5/F6/节流，不再显示“点击开始测试后才采样”] → [验证：`.venv-linux`下`py_compile gui/main.py gui/position_test/position_test_window.py`通过，`git diff --check`通过；Qt offscreen截图`artifacts/gui/position_test_calibration_layout_fixed.png`显示点位3行和结果6行完整可见，`position_test_stability_layout_fixed_idle.png`/`running.png`显示绿色摘要一行横向排布；安全影响：仅GUI布局，不改协议、不改固件、不接PID、不发0x41、不改变飞控输出]
[2026-07-21] [匿名光流绿灯呼吸但GUI显示G_VEL/ALT无数据，用户要求抓包判断是真无数据还是GUI解析问题] → [关闭GUI后直连抓`/dev/ttyACM0 @500000` 15秒，收到`raw_bytes=114170`、合法帧`10115`，常规0x01/0x02/0x03/0x04/0x05/0x06/0x07/0x08/0x09/0x0D/0x0E/0x20/0x30/0x40/0x41/0xFA均存在，但`0x33=0`、`0x34=0`、`0x51=0`；0x0E共51帧且原始字节恒为`AA AF 0E 04 00 00 00 00 6B 81`，即`STA_G_VEL=0`、`STA_G_POS=0`、`GPS=0`、`STA_ALT_ADD=0`] → [结论：GUI显示“无数据”不是解析错误，线上确实没有通用速度0x33和通用测距0x34下行帧，IMU状态帧也明确报告G_VEL和ALT_ADD无数据；同时0x05高度帧存在且`ALT_ADD≈2cm`、`ALT_STA=0`，这是IMU高度遥测字段，不等于0x34通用测距模块已接入有效] → [下一步排查应沿上游走：确认匿名光流TX/RX/GND是否接到STM32 UART4 PA1/PA0/GND、波特率是否500000、光流输出帧目标地址是否为`HW_TYPE=0x61`或广播、是否持续输出0x51 MODE1和0x34高度；必要时新增限频调试日志或RAM计数读取`ano_of.of_update_cnt/alt_update_cnt/link_sta/work_sta`，不要先改GUI]
[2026-07-23] [位置测试GUI仍无显示，但树莓派日志显示UART2 ACK `F5 #20790...`持续增长] → [本机关闭GUI/确认`/dev/ttyACM0`未被占用后，用GUI同源`FrameParser`直抓匿名数传10.0秒，得到`raw_bytes=39607`、有效帧`3378`，常规0x01/0x02/0x03/0x04/0x05/0x06/0x07/0x08/0x09/0x0D/0x0E/0x20/0x30/0x40/0x41/0xFA均存在，但`0xF6=0`] → [结论：GUI页面不显示的直接原因是当前数传下行没有收到0xF6镜像帧；树莓派端`0xA0 GREEN F5 #...`只证明USB-TTL/UART2 ACK链路正常，不等价于STM32已把F5快照经UART5→IMU→数传镜像到GUI。由于本次抓包时间约21:59，而用户提供的树莓派日志时间约21:48，尚缺“同一时间ACK增长+同一时间F6抓包”的同步证据，不能把根因直接写死为固件或GUI] → [下一步闸门：保持树莓派`send_slam_cur_f5.py`持续运行并确认ACK编号增长，同时关闭GUI后抓`/dev/ttyACM0`；若同步抓包仍`F6=0`，优先查`Uplink_Cmd_Tick()`是否触发`Rpi_Position_Mirror_Send()`、当前运行固件是否包含0xF6、以及UART5下行排队/IMU转发；若同步抓包有F6而GUI无显示，再查GUI页面激活和`PositionTestWindow.on_frame()`订阅]
[2026-07-24] [GUI飞行数据面板电量长期显示16.30V、外部传感器后续显示无效，用户对比官方匿名上位机认为GUI误判] → [排查GUI链路：主窗口`_on_frame()`确实把所有入站帧喂给`TelemetryBus`，`0x0D`电池解码为`<HH>/100`且与官方协议、数据帧监视、树莓派解析器一致；飞行数据Dock旧逻辑只显示最后值，没有显示0x0D帧计数/帧龄/原始raw，导致无法区分“GUI没更新”和“收到的0x0D原始值本来仍是1630”；外部传感器状态旧逻辑把0x0E状态标签和通用数据标签统一放进2.5s超时清空，会把短时未刷新的状态显示成NO/无效，语义不同于官方上位机的最后状态保持] → [解决：修改`gui/widgets/flight_data_dock.py`，新增0x0D诊断行显示`raw=电压raw,电流raw | #帧计数 | 帧龄`，电池超时后保留最后值并标“旧”而不是静默卡住；新增0x0E诊断行显示四个状态raw、计数和帧龄，状态标签超时后显示“正常 旧/良好 旧”而非直接变NO；通用位置/速度/测距数值行新增传感器状态感知，官方状态正常时短时无数据只显示等待/旧值，不再误判成传感器无效；同时扩展`gui/services/frame_recorder.py`记录白名单和字段解码，补上0x0D电池、0x32通用位置、0x33通用速度、0x34测距，方便后续导出日志与官方上位机逐帧对比] → [验证：`.venv-linux/bin/python -m py_compile gui/widgets/flight_data_dock.py gui/services/frame_recorder.py gui/services/telemetry_bus.py gui/services/telemetry_decoder.py`通过；Qt offscreen注入0x0D/0x0E/0x33后截图`artifacts/gui/flight_data_debug_fix.png`生成，显示`raw=1630,0 | #1 | 0.0s前`和`raw=2,0,0,2 | #1 | 0.0s前`；强制20s超时验证电压显示`16.30 V 旧`、状态显示`正常 旧`；`git diff --check`通过。安全影响：仅GUI显示/记录增强，不改飞控固件、不改协议、不影响飞行输出；下一步若仍显示16.30V但raw计数持续增长，应转查STM32/IMU实际下发的0x0D来源而不是GUI刷新]
[2026-07-24] [定点模式下遥控器CH2前推方向与现实世界相反，实机表现为前推反而后退] → [初次处理时误把“CH2反向”理解为姿态俯仰`pit`方向，用户立即纠正：问题限定在模式2定点下的CH2水平速度控制；根因位于`FcSrc/ANO_LX.c::RC_Data_Task()`的`mod_f[0] == 2`分支，CH2写入`rt_tar.st_data.vel_y`时符号与实测方向相反] → [解决：前进式修正，恢复姿态`pit`原符号不变，只将定点模式`rt_tar.st_data.vel_y = tmp_ch_dz[ch_2_pit] * ...`改为取负；不改CH1、不改CH3/CH4、不改PID、不改0x41结构] → [验证：`git diff --check -- FcSrc/ANO_LX.c`通过，`./scripts/build.sh`通过，仅保留项目已有CMSIS pragma和旧static声明告警；待用户重新烧录后只在定点模式下小幅测试CH2方向]
[2026-07-24] [匿名光流/激光高度直连匿名数传时高度和速度正常，但接入STM32飞控后经凌霄IMU/数传显示无外部传感数据，怀疑此前光流转发处理被改坏] → [按链路拆分排查：光流模块可能只向上位机地址`0xAF`输出，旧`AnoOF_GetOneByte()`只接收`HW_TYPE=0x61`或广播`0xFF`会把这类帧丢掉；原工程只把0x51 MODE1转成通用速度0x33、把0x34转成通用测距0x34，没有把光流原始0x51 MODE0/1/2原样转发给IMU/数传，导致现场无法判断是UART4没收帧、地址过滤、校验错误、模式不对、高度无效还是IMU未采纳外部传感] → [修改前备份到`记忆迁移/codex记忆迁移/backups/20260724-165031-of-debug-mirror/`；扩展`DriversBsp/Drv_AnoOf.c/h`的UART4解析诊断计数，记录合法帧、地址错误、长度错误、校验错误、0x51/0x34数量、MODE0/1/2数量、最近目标地址、最近0x34方向/角度/高度；光流解析入口临时接受`0x61/0xFF/0xAF`，避免直连PC正常但STM32因地址过滤收不到；新增0x51原始DATA缓存并在`ANO_DT_LX.c`注册/发送标准匿名`AA FF 51 LEN DATA SC AC`镜像帧；`LX_FC_EXT_Sensor.c`新增限频0xA0日志`OF ok/51/34/l/w`、`OF m0/1/2/q`、`OF a/d/g/e/la`；通用测距0x34按凌霄通用测距协议改为`DIRECTION=1、ANGLE=270、DIST=u32 cm`] → [验证：`git diff --check -- DriversBsp/Drv_AnoOf.c DriversBsp/Drv_AnoOf.h FcSrc/ANO_DT_LX.c FcSrc/LX_FC_EXT_Sensor.c FcSrc/LX_FC_EXT_Sensor.h`通过，`./scripts/build.sh`通过并生成`build-gcc/ANO_LX.hex/.bin/.elf`；安全影响：本阶段只增加诊断日志、0x51原始镜像、0x33/0x34外部传感打包修正，不接PID、不发0x41、不改变飞行输出；烧录后现场判断规则：`OF ok=0`优先查UART4接线/波特率/供电，`ok增长但51/34为0`查光流输出配置，`e=len/ck/addr`非零查帧格式/波特率/目标地址，`m0/1/2`判断实际输出模式，`la=175`表示最近目标地址为0xAF]
[2026-07-24] [烧录光流调试固件后，用户要求Codex直接用DAP读取飞控内部状态定位问题] → [同步抓匿名数传12秒：`0x0E=40`且`STA_G_VEL=0, STA_ALT_ADD=0`，`0x33/0x34/0x51/0xA0`下行计数均为0；但DAP只读RAM显示`ano_of.link_sta=1, work_sta=1`，3秒内`rx_ok +3102`、`id51 +1073`、`id34 +188`、`mode0 +153`、`mode1 +153`、`mode2 +767`、地址错误0、长度错误0、校验错误0，最近`raw_mode=2, raw_len=15, last_addr=255, quality≈250, alt_cm=3`；`ext_sens.gen_dis`已打包为`direction=1, angle=270, dist=4cm`，UART5发送缓冲可见`AA FF 51 0F ...`标准光流帧] → [结论：光流模块→STM32 UART4→`AnoOF_GetOneByte()`解析链路是通的，新固件也在运行；问题不在“光流没有进STM32”。当前卡点转移到STM32经UART5发给凌霄IMU后的采纳/转发层：这些标准外部传感输入帧已被STM32送出，但数传下行没有镜像显示，且IMU的`0x0E`仍报告外部速度/外部高度无数据] → [教训：后续不要再优先怀疑光流绿灯、UART4接收或解析器；下一步应围绕凌霄IMU对0x33/0x34/0x51输入帧的期望字段、地址、配置开关和是否转发已知传感输入帧排查。若需要GUI可视化STM32内部光流原始数据，优先新增类似0xF6的自定义调试镜像帧，而不是依赖IMU转发标准0x51/0x33/0x34]
[2026-07-24] [用户把光流/激光高度抬高后要求复测，验证“高度太低导致IMU不采纳”的假设] → [DAP复测显示`ano_of.alt_cm=75cm`、`link_sta=1`、`work_sta=1`、`quality=255`，3秒内`rx_ok +3095`、`id51 +1075`、`id34 +180`、`mode0 +154`、`mode1 +154`、`mode2 +767`，地址/长度/校验错误均无新增；`ext_sens.gen_vel=(0,-2,0x8000)`、`ext_sens.gen_dis={direction=1, angle=270, dist=75cm}`，UART5发送缓冲继续可见`AA FF 51 0F ...`和`AA FF 51 07 ...`标准光流镜像帧；但同步匿名数传12秒仍为`0x33=0, 0x34=0, 0x51=0, 0xA0=0`，`0x0E`仍是`STA_G_VEL=0, STA_ALT_ADD=0`] → [结论：高度已经进入合理工作范围，仍未被凌霄IMU标记为外部速度/外部高度有效；因此“3cm太低”不是唯一根因。当前更像是STM32→凌霄IMU的外部传感输入格式/字段/配置不符合IMU采纳条件，或IMU不会把这些输入帧原样转发到数传] → [下一步应优先对照凌霄手册和旧源码验证0x34字段到底应采用光流原始`direction=0, angle=0`还是通用测距`direction=1, angle=270`；必要时保留树莓派0xF6思路，新增STM32内部光流诊断自定义下行帧供GUI直接显示，避免继续依赖IMU是否转发标准0x51/0x33/0x34]
[2026-07-24] [用户提醒此前曾修改“光流转发给IMU”的逻辑，要求重新对照匿名/光流手册和官方例程分析差异] → [对照`原例程代码/FcSrc/LX_FC_EXT_Sensor.c`、匿名通信协议V7、匿名光流V4官方Wiki后发现三处高风险差异：1）官方例程只把光流解析后作为`0x33`通用速度和`0x34`通用测距输入IMU，不原样镜像`0x51`；当前调试版新增`0x51`原样镜像，现场估算STM32→IMU流量从官方约5.8%提高到约20.6%，可能干扰闭源IMU接收/采纳；2）官方例程`0x34`发`direction=0, angle=270`，当前按协议V7理解改为`direction=1, angle=270`，但实测IMU仍不采纳，说明应优先尊重“已验证官方例程”；3）官方例程`0x33`在高度帧更新时触发发送，当前改为MODE1速度帧更新时触发发送，可能破坏IMU预期的速度/高度同步节奏] → [当前分析结论：光流解析层无问题，最可疑的是外置传感器转发层偏离官方例程；建议下一步做最小A/B固件：禁用`0x51`原样镜像和0xA0高频日志，恢复官方`0x33`随高度更新触发、恢复`0x34 direction=0 angle=270`，保留DAP计数用于内部验证，烧录后只看`0x0E STA_G_VEL/STA_ALT_ADD`是否从0变为2/3] → [教训：闭源凌霄IMU输入应优先按官方例程和实机结果，而不是只按协议表重新解释字段；任何“看起来更符合协议”的改动都必须A/B验证后再保留。此条为分析结论，待下一版固件实机验证]
[2026-07-24] [光流外置传感器转发最小A/B固件已落地，用户询问是否可以烧录] → [根据上一条对照结论，当前应先排除“0x51原样镜像/高频日志/0x33触发节奏/0x34方向字段”偏离官方例程导致凌霄IMU不采纳的问题，而不是继续扩大补丁] → [仅修改`FcSrc/LX_FC_EXT_Sensor.c`：`OF_DEBUG_MIRROR_51_EN=0`禁用原始0x51镜像，`OF_DEBUG_LOG_EN=0`禁用0xA0光流日志；`General_Velocity_Data_Handle()`恢复官方节奏，XY随`of_update_cnt`更新，但`0x33`发送只随`alt_update_cnt`触发并置Z无效；`General_Distance_Data_Handle()`恢复`direction=0, angle=270, distance=ano_of.of_alt_cm`；保留`DriversBsp/Drv_AnoOf.c/h`内部DAP诊断计数，便于烧录后继续读RAM判断UART4光流输入] → [验证：`git diff --check -- FcSrc/LX_FC_EXT_Sensor.c FcSrc/ANO_DT_LX.c DriversBsp/Drv_AnoOf.c DriversBsp/Drv_AnoOf.h FcSrc/LX_FC_EXT_Sensor.h`通过；`./scripts/build.sh`通过，生成`build-gcc/ANO_LX.hex/.bin/.elf`，仅剩项目已有CMSIS pragma和旧头文件static声明告警；安全影响：本版不接PID、不发0x41、不改变飞行控制输出，只改变光流/测距输入IMU的转发方式。烧录后验收目标：抬高光流/激光高度，观察0x0E的`STA_G_VEL`和`STA_ALT_ADD`是否从0变为2/3]
[2026-07-24] [烧录最小A/B光流固件后现场复测，用户要求查看情况] → [数传抓`/dev/ttyACM0 @500000` 12秒：合法帧8100、校验错误0，`0x0E`仍显示`STA_G_VEL=0, STA_ALT_ADD=0`，未见下行`0x33/0x34/0x51/0xA0`；DAP读RAM确认新固件生效：`0x51`原始镜像已关闭，UART5 TX缓存存在`AA FF 33`和`AA FF 34`，不存在`AA FF 51`] → [内部状态：光流到STM32仍正常，3秒内`rx_ok +3050`、`id51 +1051`、`id34 +200`、`mode0 +150`、`mode1 +150`、`mode2 +751`，地址错误0；抬高时读到`ext_sens.gen_vel=(1~0,3~2,0x8000)`、`ext_sens.gen_dis={direction=0, angle=270, distance=75~76cm}`；当前再次读取时高度为3cm但仍能看到`0x33/0x34`发送缓存] → [结论：最小A/B固件证明“没烧进去/光流没进STM32/STM32完全没发0x33/0x34”都不是根因；凌霄IMU仍不把STM32送入的通用速度/测距判为有效，问题继续集中在IMU采纳条件、外部传感器配置开关、输入方向/字段语义或链路接法，而不是GUI和UART4解析。下一步若继续排查，不要再扩大镜像0x51，应优先查凌霄手册/参数中是否需要开启外部通用速度/附加高度输入，或做“直接把光流模块接IMU同一输入口 vs STM32转发”的A/B]

[2026-07-24] [最终纠错：光流/激光/外部传感无数据的根因不是光流模块、STM32转发代码或凌霄IMU协议采纳，而是UART2树莓派串口桥硬件导致电压数据消失] → [用户最终现场确认：只要没有`0x0D`电池电压数据，就不会有光流和激光数据；便宜的简单USB-TTL接树莓派和飞控UART2时飞控一切正常；换成某款ANO `SWD&UART V2.0` 类DAP/UART复合模块后，只要该模块的USB插到树莓派，即使树莓派关机，飞控电压立刻变为0/消失，通用速度和测距也立刻没有；拔掉模块马上恢复。插上故障模块时终端打印`[19:57:06.529] [警告] [回执] [A0 红] 运动解算失效复位`，拔掉后打印`[19:57:10.223] [信息] [回执] [A0 绿] 运动解算启动`] → [深层工程推断：该DAP/UART复合模块不是透明USB-TTL，板上同时有SWD口`VCC/CLK/GND/DIO`和UART口`TX/RX/GND/5V`、USB供电路径、DAP MCU和电平/电源域；故障在树莓派关机时仍可触发，说明不是树莓派软件发串口字节，而更像被动硬件电气问题：1）USB 5V/模块内部稳压或IO保护经UART TX/RX/GND/VCC/5V路径反灌飞控或树莓派USB地；2）模块UART侧可能是5V TTL、强上拉或异常空闲电平，经STM32 UART2引脚ESD二极管形成寄生供电/钳位电流；3）插入树莓派USB建立额外地线/屏蔽地路径，即使Pi关机也可能通过USB口泄漏或拉偏飞控ADC参考地，导致PC5/ADC1_CH15电池分压读数异常；4）DAP/UART复合板的MCU固件/电源域可能会驱动串口线或SWD相关线，不像廉价USB-TTL那样高阻透明；5）凌霄IMU的运动解算对有效电压/供电遥测存在安全依赖，当`0x0D`失效时触发运动解算复位，进而外部速度/高度状态一起失效] → [解决和新规则：树莓派UART2链路只使用已验证的简单3.3V USB-TTL或经验证隔离串口桥，只接`TX/RX/GND`，`VCC/5V`不接；任何新串口模块上线前必须先插入并验证`0x0D`电压持续合理、`0x0E`外接状态不掉、无`A0红 运动解算失效复位`，然后才运行`0xF5`发送程序；以后遇到G_VEL/ALT/0x33/0x34无数据，排查顺序固定为`0x0D电压 → UART2串口桥/反灌电/地线/电平/供电线 → 0x0E状态 → 光流0x51/0x33/0x34协议和转发代码`] → [教训：此前2026-07-21到2026-07-24关于“光流绿灯但GUI无G_VEL/ALT”“IMU不转发0x33/0x34/0x51”“0x34方向字段/0x33触发节奏可能不被采纳”等记录，都是在坏UART2硬件/电压遥测失效背景下得到的中间观察；这些记录保留作为排查过程，但最终根因已被本条硬件电气问题覆盖。后续不要再把这些旧条目当成定论去反复改光流转发；必须先保证电压链路和串口桥硬件正确。⚠️ 安全影响：该问题会触发运动解算失效复位，实机联调前必须把电压和外部传感状态作为起飞前检查项]
