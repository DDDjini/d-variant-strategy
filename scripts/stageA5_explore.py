# -*- coding: utf-8 -*-
"""
A5 探查：long 腿「趋势窗口」状态指标——先解剖 2026-07~09 超级小牛
================================================================
目标：找到能在【入场时】区分 long 趋势窗口（如 2026-08~09 牛市）的先行指标，
      以便对 long 趋势窗用更大量级 TP1/TP2 截获大 MFE。
本轮只看：A4 long 腿全部交易的 MFE 分布 + 入场时各类状态（无未来窥探），
          以及 2026-07~2026-09-18 两个标的的日线状态逐根 dump。
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
SHORT_SEL = M.SHORT_SEL
SHORT_BASE = dict(sl=0.04, tp1=1.5, tp2=5.03)
S_TRE, S_TP1_TRE = 20.0, 2.25


def cand_key(c):
    return (c['sym'], c['d'], c['date'], str(c['day_close']))


_INFO = C.cluster_label(M.POOL, GAP)
CONF = {k: v[1] >= 2 for k, v in _INFO.items()}


def adx14(df):
    c = df['close']; h = df['high']; l = df['low']; pc = c.shift(1)
    up = h.diff(); dn = -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    tr = pd.Series(np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))).ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * plus / tr; mdi = 100 * minus / tr
    return (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1/14, adjust=False).mean().values


ADX = {sym: adx14(C.DAILY[sym].reset_index(drop=True)) for sym in C.DAILY}


def probe(df, i):
    """在日线 i 位置计算状态指标（只用 <=i 的数据，无未来窥探），返回 dict"""
    c = df['close']; h = df['high']; l = df['low']
    a = df['ATR'].iloc[i]
    sma20 = c.rolling(20).mean().iloc[i]
    sma50 = c.rolling(50).mean().iloc[i]
    sma10 = c.rolling(10).mean().iloc[i]
    px = c.iloc[i]
    def roc(n):
        return (px / c.iloc[i - n] - 1) * 100 if i - n >= 0 else np.nan
    hi20 = h.iloc[i - 20:i + 1].max()
    lo20 = l.iloc[i - 20:i + 1].min()
    greens = 0; k = i
    while k > 0 and c.iloc[k] >= c.iloc[k - 1]:
        greens += 1; k -= 1
    # 斜率: sma20 近5日变化
    slope20 = (sma20 - c.rolling(20).mean().iloc[i - 5]) / a if i - 5 >= 0 else np.nan
    return dict(
        adx=float(ADX[_symcol(df)][i]) if False else float(ADX[df.attrs.get('_sym', 'BTC-USDT')][i]),
        pos20=(px - sma20) / a,      # 距SMA20（ATR单位）
        pos10=(px - sma10) / a,
        pos50=(px - sma50) / a if not np.isnan(sma50) else np.nan,
        s20p50=1.0 if sma20 > sma50 else 0.0,
        clt50=1.0 if px < sma50 else 0.0,
        dist_hi20=(px - hi20) / a,
        dist_lo20=(px - lo20) / a,
        roc5=roc(5), roc10=roc(10), roc20=roc(20),
        mom20=roc(20),
        slope20=slope20,
        greens=greens,
        atr_pct=float(df['atr_pct'].iloc[i]),
    )


pool_sym = {c['sym']: None for c in M.POOL}
# 给每日df标记符号，便于 probe 取 ADX
for sym in C.DAILY:
    C.DAILY[sym].attrs['_sym'] = sym

print('=== A4 long 腿各笔：入场态 + MFE ===')
print(f"{'date':<10}{'sym':<10}{'entry':>10}{'MFE%':>6}{'bars':>6}{'adx':>6}{'pos20':>8}{'pos50':>8}{'s20p50':>7}{'clt50':>7}"
      f"{'d_hi20':>8}{'roc5':>7}{'roc10':>7}{'roc20':>8}{'slope20':>8}{'grn':>4}")
for c in M.POOL:
    if c['d'] != 'long':
        continue
    if not CONF[cand_key(c)]:
        continue
    t = M.run_trade_a(c, LONG_P['sl'], LONG_P['tp1'], LONG_P['tp2'], 0.5)
    if t is None:
        continue
    p = probe(C.DAILY[c['sym']], c['i'])
    print(f"{c['date']:<10}{c['sym']:<10}{t['entry']:>10,.0f}{t['mfe']:>6.1f}{t['bars']:>6}"
          f"{p['adx']:>6.1f}{p['pos20']:>8.2f}{p['pos50']:>8.2f}{p['s20p50']:>7.0f}{p['clt50']:>7.0f}"
          f"{p['dist_hi20']:>8.2f}{p['roc5']:>7.1f}{p['roc10']:>7.1f}{p['roc20']:>8.1f}{p['slope20']:>8.2f}{p['greens']:>4d}")

print('\n=== 2026-07-20 ~ 2026-09-18 两标的日线状态逐根 dump（看牛市前指标异动先兆） ===')
print(f"{'dt':<10}{'sym':<10}{'close':>10}{'chg%':>7}{'adx':>6}{'pos20':>8}{'pos50':>8}{'s20p50':>7}{'d_hi20':>8}"
      f"{'roc5':>7}{'roc10':>7}{'slope20':>8}{'grn':>4}")
for sym in C.DAILY:
    df = C.DAILY[sym]
    for i in range(len(df)):
        dt = df['timestamp'].iloc[i]
        if dt >= pd.Timestamp('2026-07-01', tz='UTC') and dt <= pd.Timestamp('2026-09-18', tz='UTC'):
            p = probe(df, i)
            chg = (df['close'].iloc[i] / df['close'].iloc[i - 1] - 1) * 100
            print(f"{str(dt)[:10]:<10}{sym:<10}{df['close'].iloc[i]:>10,.0f}{chg:>7.1f}{p['adx']:>6.1f}"
                  f"{p['pos20']:>8.2f}{p['pos50']:>8.2f}{p['s20p50']:>7.0f}{p['dist_hi20']:>8.2f}"
                  f"{p['roc5']:>7.1f}{p['roc10']:>7.1f}{p['slope20']:>8.2f}{p['greens']:>4d}")