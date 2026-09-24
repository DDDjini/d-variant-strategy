# -*- coding: utf-8 -*-
"""
A3-自适应：趋势窗(ADX高)放大 TP 吃主升段 / 震荡窗维持小 TP 保命中 → 验证边际价值
================================================================
基座 A3=V1：long TP1=1.25/TP2=3.0 · short A1(TP1=1.5/TP2=5.03) · 二次确认+并发 · 净额
自适应：信号日 adx >= ADX_TRE → 长/短用大 TP1 捕捉趋势；否则维持基座小 TP1。
规则（对 long）：TP1_TRE / TP2 作用于趋势窗；震荡窗用基座 1.25/3.0。
对 short：趋势窗放大 TP1_STR；震荡窗维持 A1 的 1.5。
输出：各 ADX_TRE 下 合计/long/short 净额 + 滚动正负 + W14/15 与 W20+ 窗口单利。
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M

GAP = 4
SHORT_SEL = M.SHORT_SEL
SHORT_BASE = dict(sl=0.04, tp1=1.5, tp2=5.03)
LONG_BASE = dict(sl=0.04, tp1=1.25, tp2=3.0)


def cand_key(c):
    return (c['sym'], c['d'], c['date'], str(c['day_close']))


_INFO = C.cluster_label(M.POOL, GAP)
CONF = {k: v[1] >= 2 for k, v in _INFO.items()}


def adx14(df):
    c = df['close']; h = df['high']; l = df['low']
    pc = c.shift(1)
    up = h.diff(); dn = -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    tr = pd.Series(np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))).ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * plus / tr; mdi = 100 * minus / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1/14, adjust=False).mean().values


ADX = {sym: adx14(C.DAILY[sym].reset_index(drop=True)) for sym in C.DAILY}


def build(adx_tre, lt1, lt2, st1, st2):
    allc = []
    for c in M.POOL:
        if not CONF[cand_key(c)]:
            continue
        adx = float(ADX[c['sym']][c['i']])
        if c['d'] == 'long':
            if adx >= adx_tre:
                t = M.run_trade_a(c, 0.04, lt1, lt2, 0.5)
            else:
                t = M.run_trade_a(c, LONG_BASE['sl'], LONG_BASE['tp1'], LONG_BASE['tp2'], 0.5)
        else:
            if not SHORT_SEL(c):
                continue
            if adx >= adx_tre:
                t = M.run_trade_a(c, 0.04, st1, st2, 0.5)
            else:
                t = M.run_trade_a(c, SHORT_BASE['sl'], SHORT_BASE['tp1'], SHORT_BASE['tp2'], 0.5)
        if t is None:
            continue
        t['adx'] = adx
        allc.append(t)
    allc.sort(key=lambda t: (t['entry_ts'], t['sym']))
    open_pos, kept = {}, []
    for t in allc:
        key = (t['sym'], t['d'])
        if key in open_pos and t['entry_ts'] < open_pos[key]:
            continue
        open_pos[key] = t['exit_ts']
        kept.append(t)
    for t in kept:
        fee = 0.0005 * 2 * 100
        slip = t['sl_dist'] * 0.14 if t['outcome'] == 'SL' else 0.0
        t['ret'] = t['ret'] - fee - slip
    return kept


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, total=0.0)
    r = [t['ret'] for t in ts]; w = [x for x in r if x > 0]
    return dict(n=len(ts), wr=len(w) / len(ts) * 100, total=sum(r))


def win_total(kept, w):
    e0 = pd.Timestamp(min(t['entry_ts'] for t in kept)).floor('D') - pd.Timedelta(days=7)
    return sum(t['ret'] for t in kept if ((t['entry_ts'].floor('D') - e0).days // 30) + 1 == w)


def report(tag, kept):
    g = agg(kept); gl = agg([t for t in kept if t['d'] == 'long'])
    gs = agg([t for t in kept if t['d'] == 'short'])
    wneg = sum(1 for a in range(1, 25) if win_total(kept, a) < 0)
    print(f'{tag:<34} 合计 n={g["n"]:>2} WR {g["wr"]:>4.1f}% 净 {g["total"]:>+7.1f}% ｜ long n={gl["n"]:>2} {gl["total"]:>+6.1f}% ｜ short n={gs["n"]:>2} {gs["total"]:>+6.1f}% ｜ 滚动{wneg}负 ｜ W14/15 {win_total(kept,14)+win_total(kept,15):+6.1f}% ｜ W20+ {sum(win_total(kept,a) for a in range(20,25)):+6.1f}%')


print('基座 A3=V1（固定小 TP1）：')
report('基座', build(1e9, 0, 3.0, 0, 5.03))

print('\n--- 自适应 TP：趋势窗(adx>=TRE) 放大 TP ---')
print('long-TP1/TRE→TP1, short-TP1/TRE→TP1（TP2 趋势窗用 5.03 吃趋势）：')
configs = [
    ('TRE=20 long1.5 short1.5', 20, 1.5, 5.03, 1.5, 5.03),
    ('TRE=20 long2.0 short2.0', 20, 2.0, 5.03, 2.0, 5.03),
    ('TRE=20 long2.56 short2.56', 20, 2.56, 5.03, 2.56, 5.03),
    ('TRE=25 long1.5 short1.5', 25, 1.5, 5.03, 1.5, 5.03),
    ('TRE=25 long2.0 short2.0', 25, 2.0, 5.03, 2.0, 5.03),
    ('TRE=25 long2.56 short2.56', 25, 2.56, 5.03, 2.56, 5.03),
    ('TRE=30 long2.0 short2.0', 30, 2.0, 5.03, 2.0, 5.03),
    ('TRE=30 long2.56 short2.56', 30, 2.56, 5.03, 2.56, 5.03),
    ('TRE=30 long3.0 short2.0', 30, 3.0, 5.03, 2.0, 5.03),
]
for tag, tre, lt1, lt2, st1, st2 in configs:
    report(tag, build(tre, lt1, lt2, st1, st2))