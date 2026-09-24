# -*- coding: utf-8 -*-
"""
A5 补充：入场时 4H 短周期动量 / 近30日新高 是否可标记「即将爆发」的 long
================================================================
结论悬测：日线状态无法在入场时区分 2026-07/08 爆发窗口（详见 stageA5_tp_sweep）。
         最后的入场时可见信息 = 4H 粒度动量（signal 日当天 4H 收盘后）、
         与"价格距近30日高点的距离"（牛市常先突破后回踩）。
本轮：对 A4 long 各笔输出入场前最后一根 4H 的短周期动量，看爆发窗是否有异动。
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M

GAP = 4
LONG_P = dict(sl=0.04, tp1=1.25, tp2=3.0)


def cand_key(c):
    return (c['sym'], c['d'], c['date'], str(c['day_close']))


_INFO = C.cluster_label(M.POOL, GAP)
CONF = {k: v[1] >= 2 for k, v in _INFO.items()}


def h4_mom(sym, ts, n_last=8):
    """入场前最后一根 4H 之后（信号日收盘后）的动量特征：
    返回 前n根4H 的 max 涨幅 / 近30日高点突破度 等"""
    f4 = C.H4[sym]
    idx = f4.index[f4['timestamp'] <= ts]
    if len(idx) == 0:
        return None
    j = int(idx[-1])  # 入场后第一根4H（信号日收盘所在4H bar 起）
    if j + 2 >= len(f4):
        return None
    # 用 j 之前 8 根 4H（= 信号日前 ~32h）收盘动量
    k0 = max(0, j - n_last)
    cls = f4['close'].iloc[k0:j + 1].values
    o = f4['open'].iloc[k0:j + 1].values
    h4s = f4['high'].iloc[k0:j + 1].values
    mom8 = (cls[-1] / cls[0] - 1) * 100
    # 近 30 日高点突破度（用日线）
    d = C.DAILY[sym]
    di = d.index[d['timestamp'] <= ts]
    di = int(di[-1])
    hi30 = d['high'].iloc[di - 29:di + 1].max() if di >= 29 else d['high'].iloc[:di + 1].max()
    px = d['close'].iloc[di]
    return dict(mom8=mom8, hi30_off=(px - hi30) / hi30 * 100)


print(f"{'date':<10}{'sym':<10}{'mfe%':>6}{'bars':>6}{'4Hmom8%':>9}{'近30d高off%':>12}")
for c in M.POOL:
    if c['d'] != 'long' or not CONF[cand_key(c)]:
        continue
    t = M.run_trade_a(c, LONG_P['sl'], LONG_P['tp1'], LONG_P['tp2'], 0.5)
    if t is None:
        continue
    hm = h4_mom(c['sym'], c['day_close'])
    if hm is None:
        continue
    mark = ' <== 爆发窗' if c['date'] >= '2026-07-01' else ''
    print(f"{c['date']:<10}{c['sym']:<10}{t['mfe']:>6.1f}{t['bars']:>6}{hm['mom8']:>9.1f}{hm['hi30_off']:>12.1f}{mark}")