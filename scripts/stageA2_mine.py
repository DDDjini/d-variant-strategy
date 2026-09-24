# -*- coding: utf-8 -*-
"""
A系列第2轮 · LONG 腿独立参数挖掘（short 固定在 A1 参数）
================================================================
short 固定 = A1：ATR≥30 & mom20<0.5 · SL4% · TP1 1.5R / TP2 5.03R（22笔）
long   可变 = 扫描 过滤 / TP1 / SL / TP2（两点差异：long MFE~2.83R 触得到大TP，
               故与 short 路线相反——重点在环境过滤砍逆势多单，而非降TP1）
量尺：两年 + 同(sym,dir)单笔并发；无成本对齐阶段4；无未来函数。
"""
import os, sys
import pandas as pd
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C

POS20_MAX = 1.25
CANDS = C.detect_candidates(dirs=('long', 'short'))
POOL = [c for c in CANDS if abs(c['pos20']) <= POS20_MAX]

SHORT_SEL = lambda c: c['atr_pct'] >= 30 and c['mom20'] < 0.5
SHORT_P = dict(sl=0.04, tp1=1.5, tp2=5.03)


def run_trade_a(c, sl_pct, tp1_r, tp2_r, limit_off):
    f4 = C.H4[c['sym']]; d = c['d']
    entry = c['day_close_px']
    fidx = f4.index[f4['timestamp'] >= c['day_close']]
    if len(fidx) == 0 or f4['close_time'].iloc[fidx[0]] > C.NOW:
        return None
    j0 = int(fidx[0]); j = j0
    limit = c['mid'] - limit_off * c['atr'] if d == 'long' else c['mid'] + limit_off * c['atr']
    for k in range(j0, min(j0 + C.LIMIT_BARS, len(f4))):
        r = f4.iloc[k]
        if (d == 'long' and r['low'] <= limit) or (d == 'short' and r['high'] >= limit):
            j, entry = k, limit
            break
    sl = entry * (1 - sl_pct) if d == 'long' else entry * (1 + sl_pct)
    R = abs(entry - sl)
    if R <= 0:
        return None
    tp1 = entry + tp1_r * R if d == 'long' else entry - tp1_r * R
    tp2 = entry + tp2_r * R if d == 'long' else entry - tp2_r * R
    mae = mfe = 0.0; out = px = None; jj = len(f4) - 1
    for k in range(j, len(f4)):
        r = f4.iloc[k]
        if d == 'long':
            mae = max(mae, (entry - r['low']) / entry)
            mfe = max(mfe, (r['high'] - entry) / entry)
            if r['low'] <= sl:	out, px, jj = 'SL', sl, k; break
            if r['high'] >= tp2: out, px, jj = 'TP2', tp2, k; break
            if r['high'] >= tp1: out, px, jj = 'TP1', tp1, k; break
        else:
            mae = max(mae, (r['high'] - entry) / entry)
            mfe = max(mfe, (entry - r['low']) / entry)
            if r['high'] >= sl:  out, px, jj = 'SL', sl, k; break
            if r['low'] <= tp2:  out, px, jj = 'TP2', tp2, k; break
            if r['low'] <= tp1:  out, px, jj = 'TP1', tp1, k; break
    if out is None:
        px = float(f4.iloc[-1]['close'])
    ret = (px - entry) / entry * 100 if d == 'long' else (entry - px) / entry * 100
    return dict(sym=c['sym'], date=c['date'], d=d, entry=entry, sl=sl, tp1=tp1, tp2=tp2,
                outcome=out, ret=ret, bars=jj - j, filled=(j != j0),
                entry_ts=f4['timestamp'].iloc[j],
                exit_ts=f4['timestamp'].iloc[jj] + pd.Timedelta(hours=4),
                sl_dist=abs(entry - sl) / entry * 100, mae=mae * 100, mfe=mfe * 100,
                atr_pct=c['atr_pct'], mom20=c['mom20'], pos20_abs=abs(c['pos20']),
                gap=c['gap'], clt50=c['clt50'], s20lt50=c['s20lt50'],
                off_mid=(entry - c['mid']) / c['atr'] if d == 'long' else (c['mid'] - entry) / c['atr'])


def build(long_sel, lp):
    allc = []
    for c in POOL:
        if c['d'] == 'long':
            if not long_sel(c): continue
            t = run_trade_a(c, lp['sl'], lp['tp1'], lp['tp2'], 0.5)
        else:
            if not SHORT_SEL(c): continue
            t = run_trade_a(c, SHORT_P['sl'], SHORT_P['tp1'], SHORT_P['tp2'], 0.5)
        if t: allc.append(t)
    allc.sort(key=lambda t: (t['entry_ts'], t['sym']))
    open_pos, kept, blocked = {}, [], 0
    for t in allc:
        key = (t['sym'], t['d'])
        if key in open_pos and t['entry_ts'] < open_pos[key]:
            blocked += 1; continue
        open_pos[key] = t['exit_ts']
        kept.append(t)
    return kept, blocked


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, avg=0.0, total=0.0, pf=0.0, mdd=0.0, tp=0.0)
    rets = [t['ret'] for t in ts]
    wins = [x for x in rets if x > 0]; losses = [x for x in rets if x <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1 + r / 100); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    tp = sum(1 for t in ts if t['outcome'] in ('TP1', 'TP2'))
    return dict(n=len(ts), wr=len(wins) / len(ts) * 100, avg=sum(rets) / len(rets),
                total=sum(rets), pf=pf, mdd=mdd * 100, tp=tp / len(ts) * 100)


def wsums(ts):
    if not ts:
        return []
    e0 = pd.Timestamp(min(t['entry_ts'] for t in ts)).floor('D') - pd.Timedelta(days=7)
    e1 = pd.Timestamp(max(t['entry_ts'] for t in ts)).ceil('D')
    bounds, cur = [], e0
    while cur + pd.Timedelta(days=C.WIN_DAYS) <= e1:
        bounds.append((cur, cur + pd.Timedelta(days=C.WIN_DAYS)))
        cur += pd.Timedelta(days=C.STEP_DAYS)
    return [sum(t['ret'] for t in ts if a <= t['entry_ts'] < b) for a, b in bounds]


TRUE = lambda c: True
LONG_BASE = dict(sl=0.04, tp1=2.56, tp2=5.03)

ts_A1, _ = build(TRUE, LONG_BASE)
L1 = [t for t in ts_A1 if t['d'] == 'long']; S1 = [t for t in ts_A1 if t['d'] == 'short']
wA1 = wsums(ts_A1)
lbase = agg(L1)
print(f'A1 现状（long=阶段2spec, short=A1）总量 n={len(ts_A1)}')
print(f'  long: n={lbase["n"]} WR {lbase["wr"]:.1f}% avg {lbase["avg"]:+.2f}% 单利 {lbase["total"]:+.1f}% PF {lbase["pf"]:.2f} 回撤 {lbase["mdd"]:.1f}% TP {lbase["tp"]:.0f}%')
print(f'  short(A1固定): n={len(S1)} 总合计 WR {agg(ts_A1)["wr"]:.1f}% 单利 {agg(ts_A1)["total"]:+.1f}% PF {agg(ts_A1)["pf"]:.2f}')


def line(tag, ts):
    f = agg(ts); lo = agg([t for t in ts if t['d'] == 'long'])
    print(f'{tag:<34} long:n={lo["n"]:>3} WR {lo["wr"]:>5.1f}% avg {lo["avg"]:>+6.2f}% 单利 {lo["total"]:>+7.1f}% PF {lo["pf"]:>5.2f} 回撤 {lo["mdd"]:>5.1f}% TP {lo["tp"]:>4.0f}% ｜ 合计 WR {f["wr"]:>5.1f}% 单利 {f["total"]:>+7.1f}% PF {f["pf"]:>5.2f}')


print('\n--- P1: LONG 过滤扫描（SL4% TP1 2.56R TP2 5.03R） ---')
for name, sel in [
    ('全量', TRUE),
    ('mom20>0', lambda c: c['mom20'] > 0.0),
    ('close>=SMA50', lambda c: not c['clt50']),
    ('SMA20>SMA50', lambda c: not c['s20lt50']),
    ('ATR分位>=30', lambda c: c['atr_pct'] >= 30),
    ('ATR分位>=40', lambda c: c['atr_pct'] >= 40),
    ('mom>0 & 不clt50', lambda c: c['mom20'] > 0 and not c['clt50']),
]:
    ts, _ = build(sel, LONG_BASE)
    line(f'long:{name}', ts)

print('\n--- P2: LONG TP1 扫描（SL4%，TP2=5.03R） ---')
for r in (1.5, 2.0, 2.56, 3.0, 3.5):
    ts, _ = build(TRUE, dict(sl=0.04, tp1=r, tp2=5.03))
    line(f'long TP1={r}R', ts)

print('\n--- P3: LONG SL 扫描（TP1 2.56R） ---')
for sl in (0.035, 0.04, 0.05, 0.06):
    ts, _ = build(TRUE, dict(sl=sl, tp1=2.56, tp2=5.03))
    line(f'long SL={sl*100:.1f}%', ts)

print('\n--- P4: LONG TP2（5.03 vs 3.0，阶段3已知 5.03 是死参数） ---')
for r2 in (3.0, 5.03):
    ts, _ = build(TRUE, dict(sl=0.04, tp1=2.56, tp2=r2))
    line(f'long TP2={r2}R', ts)