# -*- coding: utf-8 -*-
"""
A5 严测：long 腿是否可用【入场时状态】标记趋势窗 → 加大 TP 截获大 MFE
================================================================
背景：2026-08-19 平地一根大阳线爆发超级小牛，A4 里 07/08 月几笔 long MFE 9~11.5%
      但都被 TP1=1.25R(+5%) 封顶。问题：入场时有无状态能标记"趋势窗"？
本轮：对长期候选的各类趋势状态规则（s20p50&!clt50 / adx≥20 / slope20>0 / pos20>0.5 /
      roc20>0 / pos50>0.5 等）× 趋势窗长 TP1/TP2 网格，跑完整并发+成本。
量尺与 A4 完全一致：两年 + 二次确认(gap=4) + 同(sym,dir)并发 + 净额(扣fee+SL滑点)，
对照 A4 最终(净 +132.9% / WR77.8% / PF4.57 / 回撤9.1%)，并看滚动负窗数与 W14/15。
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M

GAP = 4
LONG_SIDE = dict(sl=0.04, tp1=1.25, tp2=3.0)   # 震荡窗 long
LONG_TRE = dict(sl=0.04, tp1=2.56, tp2=5.03)   # 趋势窗 long（放大）
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

# 预计算各趋势规则的入场态（无未来窥探，只用 <= day i）
def states(c):
    df = C.DAILY[c['sym']]; i = c['i']
    cl = df['close']
    sma20 = cl.rolling(20).mean().iloc[i]; sma50 = cl.rolling(50).mean().iloc[i]
    px = cl.iloc[i]
    a = df['ATR'].iloc[i] if not np.isnan(df['ATR'].iloc[i]) else 1.0
    slope20 = (sma20 - cl.rolling(20).mean().iloc[i-5]) / a if i-5 >= 0 else np.nan
    return dict(
        s20p50ok=not bool(df['sma20_lt_50'].iloc[i]) and not bool(df['close_lt_50'].iloc[i]),
        adx=float(ADX[c['sym']][i]),
        slope20=float(slope20) if not np.isnan(slope20) else 0.0,
        pos20=float((px - sma20) / a) if not np.isnan((px - sma20)/a) else 0.0,
        pos50=float((px - sma50) / a) if not np.isnan(sma50) else 0.0,
        roc20=float(c['mom20']),
    )


RULES = {
    's20p50&!clt50': lambda s: s['s20p50ok'],
    'adx>=20':       lambda s: s['adx'] >= 20,
    'slope20>0':     lambda s: s['slope20'] > 0,
    'pos20>0.5':     lambda s: s['pos20'] > 0.5,
    'roc20>0':       lambda s: s['roc20'] > 0,
    'pos50>0.5':     lambda s: s['pos50'] > 0.5,
    'ANY(adx|pos20)': lambda s: s['adx'] >= 20 or s['pos20'] > 0.5,
}

ST = {k: states(c) for k, c in enumerate(M.POOL)}


def build(long_tre_rule, long_tp):
    """long_tre_rule: None=不放大(全 long 用震荡 TP)；可调用对象→标记趋势窗用扩大 TP"""
    allc = []
    for c, cidx in zip(M.POOL, M.POOL):
        pass
    for c in M.POOL:
        if not CONF[cand_key(c)]:
            continue
        if c['d'] == 'long':
            if long_tre_rule is not None and long_tre_rule(ST[c['i'] if 'i' in c else 0]) if False else True:
                pass
    # 重新按索引
    idx = {c['date'] + c['sym'] + str(c['day_close']) + c['d']: i for i, c in enumerate(M.POOL)}
    for c in M.POOL:
        if not CONF[cand_key(c)]:
            continue
        adx = ST[idx[c['date'] + c['sym'] + str(c['day_close']) + c['d']]]
        if c['d'] == 'long':
            if long_tre_rule is not None and long_tre_rule(adx):
                lp = long_tp
            else:
                lp = LONG_SIDE
            t = M.run_trade_a(c, lp['sl'], lp['tp1'], lp['tp2'], 0.5)
        else:
            if not SHORT_SEL(c):
                continue
            st1 = S_TP1_TRE if adx['adx'] >= S_TRE else SHORT_BASE['tp1']
            t = M.run_trade_a(c, SHORT_BASE['sl'], st1, 5.03, 0.5)
        if t is None:
            continue
        allc.append(t)
    allc.sort(key=lambda t: (t['entry_ts'], t['sym']))
    open_pos, kept, blocked = {}, [], 0
    for t in allc:
        key = (t['sym'], t['d'])
        if key in open_pos and t['entry_ts'] < open_pos[key]:
            blocked += 1; continue
        open_pos[key] = t['exit_ts']
        kept.append(t)
    for t in kept:
        fee = 0.0005 * 2 * 100
        slip = t['sl_dist'] * 0.14 if t['outcome'] == 'SL' else 0.0
        t['ret'] = t['ret'] - fee - slip
    return kept, blocked


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, avg=0.0, total=0.0, pf=0.0, mdd=0.0)
    r = [t['ret'] for t in ts]; w = [x for x in r if x > 0]; l = [x for x in r if x <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in r:
        eq *= (1 + x / 100); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    pf = abs(sum(w) / sum(l)) if l and sum(l) != 0 else float('inf')
    return dict(n=len(ts), wr=len(w) / len(ts) * 100, avg=sum(r) / len(r), total=sum(r), pf=pf, mdd=mdd * 100)


def win_total(kept, w):
    e0 = pd.Timestamp(min(t['entry_ts'] for t in kept)).floor('D') - pd.Timedelta(days=7)
    return sum(t['ret'] for t in kept if ((t['entry_ts'].floor('D') - e0).days // 30) + 1 == w)


# ---- A4 基线 ----
base, _ = build(None, LONG_TRE)
gb = agg(base)
wb = sum(1 for a in range(1, 25) if win_total(base, a) < 0)
print(f'[A4 基线] n={gb["n"]} WR {gb["wr"]:.1f}% 净 {gb["total"]:+.1f}% PF {gb["pf"]:.2f} 回撤 {gb["mdd"]:.1f}% ｜ 滚动{wb}负 ｜ W14/15 {win_total(base,14)+win_total(base,15):+.1f}%')

# ---- long 趋势放大扫描 ----
print('\n=== long 趋势窗放大 TP（其余 long 恒 1.25/3.0） ===')
print(f"{'趋势规则':<14}{'长TP1/TP2':>12}{'n':>4}{'WR%':>6}{':long净':>8}{'总净':>8}{'PF':>5}{'回撤%':>7}{'滚负':>5}{'W14/15%':>8}")
for rname, rule in RULES.items():
    for r1, r2 in [(2.0, 3.0), (2.56, 3.0), (2.0, 5.03), (2.56, 5.03)]:
        k, _ = build(rule, dict(sl=0.04, tp1=r1, tp2=r2))
        g = agg(k); gl = agg([t for t in k if t['d'] == 'long'])
        wn = sum(1 for a in range(1, 25) if win_total(k, a) < 0)
        w14 = win_total(k, 14) + win_total(k, 15)
        print(f"{rname:<14}{f'{r1}/{r2}R':>12}{g['n']:>4}{g['wr']:>6.1f}{gl['total']:>+8.1f}{g['total']:>+8.1f}"
              f"{g['pf']:>5.2f}{g['mdd']:>7.1f}{wn:>5}{w14:>+8.1f}")
    print()

# ---- 直接量化"更大TP在哪些枪上兑现"，不依赖状态 ---- 
print('\n=== 每笔 long：当前(1.25/3.0) vs 全放大(2.56/5.03) 的净利差（看钱留在哪） ===')
win_only = []
for c in M.POOL:
    if c['d'] != 'long' or not CONF[cand_key(c)]:
        continue
    t0 = M.run_trade_a(c, 0.04, 1.25, 3.0, 0.5); t1 = M.run_trade_a(c, 0.04, 2.56, 5.03, 0.5)
    if t0 is None or t1 is None:
        continue
    fee = 0.0005 * 2 * 100
    r0 = round(t0['ret'] - fee, 1); r1 = round(t1['ret'] - fee, 1)
    d = ('+' if r1 - r0 > 0 else '')
    print(f"{c['date']} {c['sym']:<10} cur={r0:>+6.1f}  bigTP={r1:>+6.1f}  diff={d}{r1-r0:+.1f}  MFE={t0['mfe']:.1f}  bars={t0['bars']} {'<==' if r1-r0>0 else ''}")