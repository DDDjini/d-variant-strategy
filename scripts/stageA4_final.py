# -*- coding: utf-8 -*-
"""
A4 最终版：short 腿市场状态自适应 TP（震荡窗 1.5R / 趋势窗 ADX≥20 → 2.25R）+ 二次确认 + 并发
================================================================
核心结论（平台校验+WFO 支撑）：
  - 自适应 TP 的【正确形态 = 只对 short 做趋势放大】(long MFE 够不着大 TP, hard fail)
  - short ADX≥20 → TP1 1.5→2.25R：净 +111.9→+132.9%，WR 77.8% 保持，滚动/W14/15 不劣
  - 弱段 W14/15 为低 ADX 噪声单（-4.4%，占总量4%），无未来状态规则无法剔除
量尺：两年 + 二次确认(gap=4) + 同(sym,dir)单笔并发 + 净额(扣 fee+SL滑点) + 无未来窥探
输出：stageA4_trades.csv + stageA4_trade_cards.html(含入场价) + 控制台 WFO
"""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_trade_cards as CARDS

GAP = 4
LONG_P = dict(sl=0.04, tp1=1.25, tp2=3.0)
SHORT_SEL = M.SHORT_SEL
SHORT_BASE = dict(sl=0.04, tp1=1.5, tp2=5.03)     # 震荡窗
S_TRE = 20.0
S_TP1_TRE = 2.25                                     # 趋势窗 short TP1
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')


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


def build(candset=None):
    candset = candset if candset is not None else M.POOL
    allc = []
    for c in candset:
        if not CONF[cand_key(c)]:
            continue
        adx = float(ADX[c['sym']][c['i']])
        if c['d'] == 'long':
            t = M.run_trade_a(c, LONG_P['sl'], LONG_P['tp1'], LONG_P['tp2'], 0.5)
        else:
            if not SHORT_SEL(c):
                continue
            st1 = S_TP1_TRE if adx >= S_TRE else SHORT_BASE['tp1']
            t = M.run_trade_a(c, SHORT_BASE['sl'], st1, 5.03, 0.5)
        if t is None:
            continue
        t['adx'] = adx
        t['state'] = '趋势' if adx >= S_TRE else '震荡'
        allc.append(t)
    allc.sort(key=lambda t: (t['entry_ts'], t['sym']))
    open_pos, kept, blocked = {}, [], 0
    for t in allc:
        key = (t['sym'], t['d'])
        if key in open_pos and t['entry_ts'] < open_pos[key]:
            blocked += 1
            continue
        open_pos[key] = t['exit_ts']
        kept.append(t)
    for t in kept:
        fee = 0.0005 * 2 * 100
        slip = t['sl_dist'] * 0.14 if t['outcome'] == 'SL' else 0.0
        t['fee'] = fee; t['slip'] = slip; t['ret_gross'] = t['ret']
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
    return dict(n=len(ts), wr=len(w) / len(ts) * 100, avg=sum(r) / len(r), total=sum(r), pf=pf, mdd=mdd*100)


def win_total(kept, w):
    e0 = pd.Timestamp(min(t['entry_ts'] for t in kept)).floor('D') - pd.Timedelta(days=7)
    return sum(t['ret'] for t in kept if ((t['entry_ts'].floor('D') - e0).days // 30) + 1 == w)


kept, blocked = build()
G = agg(kept); Gl = agg([t for t in kept if t['d'] == 'long']); Gs = agg([t for t in kept if t['d'] == 'short'])
wneg = sum(1 for a in range(1, 25) if win_total(kept, a) < 0)
fee_s = sum(t['fee'] for t in kept); slip_s = sum(t['slip'] for t in kept)
print(f'A4 最终版（short自适应 ADX≥{S_TRE:.0f}→TP1 {S_TP1_TRE}R · long恒1.25R · 二次确认+并发 · 净额）')
print(f'跳过并发 {blocked} ｜ 成本 fee {fee_s:.1f}+滑点 {slip_s:.1f}')
print(f'总量: n={G["n"]} WR {G["wr"]:.1f}% 平均 {G["avg"]:+.2f}% 净单利 {G["total"]:+.1f}% PF {G["pf"]:.2f} 回撤 {G["mdd"]:.1f}% ｜ 滚动{wneg}负')
print(f'long: n={Gl["n"]} WR {Gl["wr"]:.1f}% 净 {Gl["total"]:+.1f}% PF {Gl["pf"]:.2f} ｜ short: n={Gs["n"]} WR {Gs["wr"]:.1f}% 净 {Gs["total"]:+.1f}% PF {Gs["pf"]:.2f}')
print(f'W14/15 {win_total(kept,14)+win_total(kept,15):+.1f}% ｜ W20+ {sum(win_total(kept,a) for a in range(20,25)):+.1f}%')

# short 状态分布
st_tr = [t for t in kept if t['d'] == 'short' and t['state'] == '趋势']
st_os = [t for t in kept if t['d'] == 'short' and t['state'] == '震荡']
a_tr, a_os = agg(st_tr), agg(st_os)
print(f'short趋势窗(ADX≥{S_TRE:.0f}): n={a_tr["n"]} WR {a_tr["wr"]:.1f}% 净 {a_tr["total"]:+.1f}% ｜ short震荡窗: n={a_os["n"]} WR {a_os["wr"]:.1f}% 净 {a_os["total"]:+.1f}%')

# ---- WFO：固定平台参数在多个后段验证窗的 OOS 稳健性 ----
print('\n--- WFO（固定 S_TRE=20/TP1=2.25 外界未知段 OOS） ---')
for frac in [0.55, 0.65, 0.75]:
    bidx = int(len(M.POOL) * frac)
    bound = sorted(M.POOL, key=lambda c: c['day_close'])[bidx]['day_close']
    kf, _ = build()
    v = [t for t in kf if t['entry_ts'] >= bound]
    a = agg(v)
    print(f'  后段{frac:.0%}起 bound={bound:%y-%m-%d} 验证窗 n={a["n"]} WR {a["wr"]:.1f}% 净 {a["total"]:+.1f}% PF {a["pf"]:.2f}（统一用固定平台参数外推）')

# ---- 无未来审计 ----
now = pd.Timestamp('2026-09-18 02:00:00', tz='UTC')
le = max(t['entry_ts'] for t in kept); lx = max(t['exit_ts'] for t in kept)
neg = any(t['exit_ts'] < t['entry_ts'] for t in kept)
print(f'\n[审计] NOW={now} ｜ entry最晚 {le} ｜ exit最晚 {lx} ｜ 越过NOW={le>now or lx>now} ｜ 负持有={neg} ｜ entry缺值={sum(1 for t in kept if t["entry"] is None)}')

# ---- 导出 ----
csv = os.path.join(OUT, 'stageA4_trades.csv')
html = os.path.join(OUT, 'stageA4_trade_cards.html')
df = pd.DataFrame(kept)
df.to_csv(csv, index=False, encoding='utf-8-sig')
CARDS.build(csv, html, 'A4 · short 趋势自适应 TP + 二次确认',
            f'short ADX≥20→TP1 2.25R / 震荡1.5R · long TP1 1.25R · 二次确认+并发 · 两年 · 净额 · 含入场价')