# -*- coding: utf-8 -*-
"""
A4 平台校验 + WFO：short 腿趋势自适应（ADX≥TRE → TP1 1.5→TP1_S）是否稳健平台、非过拟合
================================================================
候选落地：市场状态自适应 TP 的【正确形态】= 只对 short 腿做趋势放大（long 恒 1.25R）
  理由：阶段3 MFE 证明 short 够得着大 TP、long 够不着；手动验证 short-only 放大
        净 +111.9→+125.9 而 WR 77.8% 保持/滚动4负/W20+ 增强。
本脚本：① TRE × TP1_S 邻域平台校验（防尖峰）② walk-forward 切分验证 OOS
"""
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


def build(st_tre, st_tp1, candset=None):
    candset = candset if candset is not None else M.POOL
    allc = []
    for c in candset:
        if not CONF[cand_key(c)]:
            continue
        adx = float(ADX[c['sym']][c['i']])
        if c['d'] == 'long':
            t = M.run_trade_a(c, LONG_BASE['sl'], LONG_BASE['tp1'], LONG_BASE['tp2'], 0.5)
        else:
            if not SHORT_SEL(c):
                continue
            st1 = st_tp1 if adx >= st_tre else SHORT_BASE['tp1']
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
        return dict(n=0, wr=0.0, total=0.0, pf=0.0)
    r = [t['ret'] for t in ts]; w = [x for x in r if x > 0]; l = [x for x in r if x <= 0]
    pf = abs(sum(w) / sum(l)) if l and sum(l) != 0 else float('inf')
    return dict(n=len(ts), wr=len(w) / len(ts) * 100, total=sum(r), pf=pf)


def win_total(kept, w):
    e0 = pd.Timestamp(min(t['entry_ts'] for t in kept)).floor('D') - pd.Timedelta(days=7)
    return sum(t['ret'] for t in kept if ((t['entry_ts'].floor('D') - e0).days // 30) + 1 == w)


lines = []
def log(s=''):
    print(s); lines.append(s)


log('基座（short 恒 1.5）：')
kb = build(1e9, 0); g = agg(kb); gs = agg([t for t in kb if t['d'] == 'short'])
log(f'  基座A3=V1: n={g["n"]} WR {g["wr"]:.1f}% 净 {g["total"]:+.1f}% PF {g["pf"]:.2f} ｜ short n={gs["n"]} WR{gs["wr"]:.0f}% {gs["total"]:+.1f}%')

log('\n① TRE × short-TP1 邻域平台校验：')
log('   行=TRE, 列=short趋势TP1; 单元= 净总利%(WR%)')
hdr = '      ' + '  '.join(f'TP1={v}' for v in [1.75, 2.0, 2.25, 2.5])
log(hdr)
for tre in [16, 18, 20, 22, 24]:
    cells = []
    for st1 in [1.75, 2.0, 2.25, 2.5]:
        k = build(tre, st1); a = agg(k)
        cells.append(f'{a["total"]:+.1f}({a["wr"]:.0f})')
    log(f' TRE={tre:<3}' + '  '.join(f'{x:>10}' for x in cells))

log('\n② WFO：训练窗选 short 趋势参数 → OOS 验证')
for frac in [0.55, 0.65]:
    bidx = int(len(M.POOL) * frac)
    bound = sorted(M.POOL, key=lambda c: c['day_close'])[bidx]['day_close']
    train_set = [c for c in M.POOL if c['day_close'] < bound]
    # 训练窗独立扫 short(2.0/2.56)×TRE 选 short 贡献最高
    best = None; bestv = -1e9
    for tre in [18, 20, 22]:
        for st1 in [1.5, 2.0, 2.56]:
            k = build(tre, st1, train_set)
            sv = agg([t for t in k if t['d'] == 'short'])['total']
            if sv > bestv:
                bestv, best = sv, (tre, st1)
    tre, st1 = best
    kf = build(tre, st1)   # 全窗
    v = [t for t in kf if t['entry_ts'] >= bound]
    a = agg(v)
    log(f'  frac={frac:.0%} bound={bound:%y-%m-%d} → 训练选 short TRE={tre}/TP1={st1} (short{bestv:+.0f})｜OOS验证窗 n={a["n"]} WR {a["wr"]:.1f}% 净 {a["total"]:+.1f}% PF {a["pf"]:.2f}')

log('\n③ 最终候选 short ADX≥20 → 2.0R 滚动切分（确认 W14/15、W20+ 改善）：')
kf = build(20, 2.0); kb_base = build(1e9, 0)
log(f'  基座:  W14/15 {win_total(kb_base,14)+win_total(kb_base,15):+.1f}% ｜ W20+ {sum(win_total(kb_base,a) for a in range(20,25)):+.1f}%（滚动{sum(1 for a in range(1,25) if win_total(kb_base,a)<0)}负）')
log(f'  A4:    W14/15 {win_total(kf,14)+win_total(kf,15):+.1f}% ｜ W20+ {sum(win_total(kf,a) for a in range(20,25)):+.1f}%（滚动{sum(1 for a in range(1,25) if win_total(kf,a)<0)}负）')

with open(os.path.join(OUT, 'stageA3_validate.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
with open(os.path.join(OUT, 'stageA4_validate.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('\n已导出 → results/stageA3_validate.txt & stageA4_validate.txt')