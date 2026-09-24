# -*- coding: utf-8 -*-
"""A3-自适应补测：short-only 趋势放大(长不动) + 弱段极低ADX降档 — 确认方向"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M

GAP = 4
LONG_BASE = dict(sl=0.04, tp1=1.25, tp2=3.0)
SHORT_SEL = M.SHORT_SEL
SHORT_BASE = dict(sl=0.04, tp1=1.5, tp2=5.03)


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


def build(st_tre, st_tp1, weak_skip_adx):
    allc = []
    for c in M.POOL:
        if not CONF[cand_key(c)]:
            continue
        adx = float(ADX[c['sym']][c['i']])
        if c['d'] == 'long':
            t = M.run_trade_a(c, LONG_BASE['sl'], LONG_BASE['tp1'], LONG_BASE['tp2'], 0.5)
        else:
            if not SHORT_SEL(c):
                continue
            # 弱段保护：极低 ADX 震荡期跳过 short（可选）
            if weak_skip_adx is not None and adx < weak_skip_adx:
                continue
            st1 = st_tp1 if (st_tre is not None and adx >= st_tre) else SHORT_BASE['tp1']
            t = M.run_trade_a(c, SHORT_BASE['sl'], st1, 5.03, 0.5)
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
    print(f'{tag:<36} 合计 n={g["n"]:>2} WR {g["wr"]:>4.1f}% 净 {g["total"]:>+7.1f}% ｜ long n={gl["n"]:>2} {gl["total"]:>+5.1f}% ｜ short n={gs["n"]:>2} WR{gs["wr"]:>4.0f}% {gs["total"]:>+5.1f}% ｜ 滚{wneg}负 ｜ W14/15 {win_total(kept,14)+win_total(kept,15):+6.1f}% ｜ W20+ {sum(win_total(kept,a) for a in range(20,25)):+6.1f}%')


print('基座 A3=V1：')
report('基座(long1.25 fixed, short A1)', build(None, 0, None))
print('\n--- short-only 趋势放大（long 恒 1.25 不动） ---')
for tre, st1 in [(20, 2.0), (20, 2.56), (25, 2.0), (25, 2.56), (30, 2.56)]:
    report(f'short TRE={tre}→{st1}R, long不动', build(tre, st1, None))
print('\n--- 弱段保护：极低 ADX 跳过 short ---')
for th in [12, 14, 15]:
    report(f'弱段skip short adx<{th}', build(None, 0, th))
print('\n--- 组合：short趋势放大 + 弱段跳过 ---')
for tre, st1, th in [(25, 2.56, 14), (30, 2.56, 14)]:
    report(f'short TRE={tre}→{st1} + skip<{th}', build(tre, st1, th))