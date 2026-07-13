# -*- coding: utf-8 -*-
"""路径 K 段分桶工具（P8）。

提供 `segments_by_age(points, k)`：把按时间升序排列的 PathPoint 序列等长切成 k 段。
- 段索引 0 = 最旧（tail），段索引 k-1 = 最新（head）
- 相邻段共享端点，保证可视化时折线首尾相接不留缝
- 若点数不足以分 k 段，会在末尾追加空段填齐，便于 widget 维持固定数量 LineItem

`lerp_*` 系列：在 tail→head 之间按段下标比例插值宽度 / alpha / 颜色。
"""
from __future__ import annotations

from typing import Any, Sequence


def segments_by_age(points: Sequence[Any], k: int) -> list[list[Any]]:
    """把 points 等长切 k 段（含端点续接），返回长度恰为 k 的列表。

    Args:
        points: 按时间升序的路径点序列（最旧在前、最新在后）。
        k:       目标段数，应 ≥ 1。

    Returns:
        list[list[Any]]：长度=k；每个子列表至少 0 个点。
        - n=0 → 全部空段
        - n=1 → 仅最后一段含该点
        - 段 i 范围（含端点续接）：[floor(i*n/k), floor((i+1)*n/k)]，末段闭合到 n-1
    """
    if k <= 0:
        return []
    n = len(points)
    if n == 0:
        return [[] for _ in range(k)]
    if n == 1:
        out: list[list[Any]] = [[] for _ in range(k)]
        out[-1] = [points[0]]
        return out
    # 等长切分；每段尾点 = 下一段首点（共享端点）
    out = []
    for i in range(k):
        lo = (i * n) // k
        hi = ((i + 1) * n) // k  # 下一段的 lo
        # 含尾续接：除最后一段外，hi 加 1 让本段尾点 = 下段首点
        if i < k - 1:
            hi_inclusive = min(n, hi + 1)
        else:
            hi_inclusive = n
        if lo >= hi_inclusive:
            out.append([])
        else:
            out.append(list(points[lo:hi_inclusive]))
    return out


def lerp_scalar(tail: float, head: float, k: int, i: int) -> float:
    """段 i / 共 k 段时的线性插值标量：i=0→tail, i=k-1→head。"""
    if k <= 1:
        return float(head)
    t = i / float(k - 1)
    return float(tail) + (float(head) - float(tail)) * t


def lerp_alpha_byte(tail_alpha: int, head_alpha: int, k: int, i: int) -> int:
    """段透明度（0-255 整数），用于 RGBA 第四位。"""
    v = lerp_scalar(float(tail_alpha), float(head_alpha), k, i)
    return max(0, min(255, int(round(v))))
