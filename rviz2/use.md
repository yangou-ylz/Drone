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