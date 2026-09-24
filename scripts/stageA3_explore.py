# -*- coding: utf-8 -*-
"""
A3 探查：市场状态特征（ADX/方向环境）能否区分 W14/W15 弱段坏单 vs 强段好单
================================================================
对 A3=V1（二次确认+并发）实际 36 笔，标注信号日可得的无未来状态特征：
  - figure_ADX(14)           趋势强度（Wilder 平滑，用截至信号日的日线计算）
  - clt50 / s20lt50          熊市/均线方向  （已由候选带出）
  - atr_pct                  波动率分位
输出：各状态子集净额指标 + W14/W15 窗口覆盖子集分布，判断能否干净切分。
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


def adx14(df):
    c = df['close']; h = df['high']; l = df['low']
    pc = c.shift(1)
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    pdm = pd.Series(plus_dm).ewm(alpha=1 / 14, adjust=False).mean()
    mdm = pd.Series(minus_dm).ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pdm / atr; mdi = 100 * mdm / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, adjust=False).mean()
    return adx


# 逐标的预计算 ADX 序列，索引对齐 DAILY
ADX = {}
for sym in C.DAILY:
    d = C.DAILY[sym].reset_index(drop=True)
    ADX[sym] = adx14(d).values


def idx_of(c):
    # c['i'] 是 DAILY 行号，直接拿到该行的 adx
    return c['i']


def build():
    allc = []
    for c in M.POOL:
        if not CONF[cand_key(c)]:
            continue
        if c['d'] == 'long':
            t = M.run_trade_a(c, LONG_P['sl'], LONG_P['tp1'], LONG_P['tp2'], 0.5)
            sel = True
        else:
            if not M.SHORT_SEL(c):
                continue
            t = M.run_trade_a(c, M.SHORT_P['sl'], M.SHORT_P['tp1'], M.SHORT_P['tp2'], 0.5)
        if t is None:
            continue
        t['adx'] = float(ADX[c['sym']][c['i']])
        t['clt50'] = c['clt50']; t['s20lt50'] = c['s20lt50']
        allc.append(t)
    allc.sort(key=lambda t: (t['entry_ts'], t['sym']))
    open_pos, kept = {}, []
    for t in allc:
        key = (t['sym'], t['d'])
        if key in open_pos and t['entry_ts'] < open_pos[key]:
            continue
        open_pos[key] = t['exit_ts']
        kept.append(t)
    return kept


# 净额成本
def cost(kept):
    for t in kept:
        fee = 0.0005 * 2 * 100
        slip = t['sl_dist'] * (1.14 - 1.0) if t['outcome'] == 'SL' else 0.0
        t['ret'] = t['ret'] - fee - slip


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, total=0.0)
    r = [t['ret'] for t in ts]; w = [x for x in r if x > 0]
    return dict(n=len(ts), wr=len(w) / len(ts) * 100, total=sum(r))


kept = build(); cost(kept)
g = agg(kept)
print(f'A3=V1 基座合计: n={g["n"]} WR {g["wr"]:.1f}% 净单利 {g["total"]:+.1f}%\n')

# 时间窗定位 W14/W15
e0 = pd.Timestamp(min(t['entry_ts'] for t in kept)).floor('D') - pd.Timedelta(days=7)
def win_no(t):
    return int((t['entry_ts'].floor('D') - e0).days // 30) + 1
for t in kept:
    t['w'] = win_no(t)
weak = [t for t in kept if t['w'] in (14, 15)]
strong = [t for t in kept if t['w'] >= 20]
print(f'W14/15 弱段: n={len(weak)} 净单利 {agg(weak)["total"]:+.1f}%')
for t in weak:
    print(f'    {t["sym"][:3]:3} {t["d"]:5} {str(t["entry_ts"])[5:10]} adx={t["adx"]:5.1f} clt50={t["clt50"]} s20lt50={t["s20lt50"]} {t["outcome"]:3} {t["ret"]:+.1f}%')
print(f'\nW20+ 强段: n={len(strong)} 净单利 {agg(strong)["total"]:+.1f}%')
for t in strong:
    print(f'    {t["sym"][:3]:3} {t["d"]:5} {str(t["entry_ts"])[5:10]} adx={t["adx"]:5.1f} clt50={t["clt50"]} s20lt50={t["s20lt50"]} {t["outcome"]:3} {t["ret"]:+.1f}%')

print('\n--- ADX 分档（全样本净额） ---')
for lo, hi in [(0, 20), (20, 25), (25, 35), (35, 100)]:
    s = [t for t in kept if lo <= t['adx'] < hi]
    a = agg(s)
    print(f'  ADX [{lo},{hi}): n={a["n"]:>2} WR {a["wr"]:>5.1f}% 净单利 {a["total"]:>+7.1f}%')

print('\n--- 熊市环境 short 表现（s20lt50 / clt50）---')
for name, sel in [('s20lt50=T(空头均线)', lambda t: t['s20lt50']),
                  ('s20lt50=F(多头均线)', lambda t: not t['s20lt50']),
                  ('clt50=T(close<SMA50)', lambda t: t['clt50']),
                  ('clt50=F(close>=SMA50)', lambda t: not t['clt50'])]:
    s = [t for t in kept if sel(t)]
    sh = [t for t in s if t['d'] == 'short']
    a = agg(s); as_ = agg(sh)
    print(f'  {name:<22} 全部 n={a["n"]:>2} 净{a["total"]:>+7.1f}% ｜ short n={as_["n"]:>2} WR {as_["wr"]:>4.0f}% 净{as_["total"]:>+7.1f}%')

print('\n--- 弱段交易所处状态集（找公共模式）---')
for t in weak:
    print(f'  {t["sym"][:3]:3} {t["d"]:5} {str(t["entry_ts"])[5:10]} w{t["w"]} adx={t["adx"]:5.1f} s20lt50={t["s20lt50"]} clt50={t["clt50"]} atr_pct={t["atr_pct"]:.0f} {t["outcome"]}')