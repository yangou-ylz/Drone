# 一、将树梅派文件拷贝过来
```bash
scp ylz@192.168.0.80:树梅派文件绝对路径   此电脑绝对路径
```
```bash
#比如要传过来地图图片
scp ylz@192.168.0.80:/home/ylz/n10p_leishen/maps/n10p_map_with_ekf.png /home/ubuntu22/stm32/ANO_LX_FC/rviz2/map

#比如要传过来rviz配置
scp ylz@192.168.0.80:/home/ylz/n10p_leishen/rviz/n10p_nav_ekf.rviz /home/ubuntu22/stm32/ANO_LX_FC/rviz2/rviz
```

# 二、加载已有的rviz配置，打开rviz
```bash
rviz2 -d rviz文件路径
```
```bash
# 比如
rviz2 -d /home/ubuntu22/stm32/ANO_LX_FC/rviz2/rviz/n10p.rviz
```

# 三、从GUI一键打开rviz

GUI 顶部菜单栏有独立的 `rviz` 按键，点击后等价于在后台运行：

```bash
rviz2 -d /home/ubuntu22/stm32/ANO_LX_FC/rviz2/rviz/n10p.rviz
```

注意事项：

- RViz 是独立窗口，不嵌入 GUI，不影响原 GUI 串口、位置测试、IMU 测试等功能。
- RViz 的终端输出会转发到 GUI 底部日志栏，分类显示为紫色 `[rviz]`。
- 再次点击 `rviz` 或关闭 GUI 时，会停止 RViz 子进程，避免后台残留。
- GUI 从桌面启动时会自动尝试 `source /opt/ros/humble/setup.bash`，如果仍然打不开，优先看底部 `[rviz]` 日志。
