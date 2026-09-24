# -*- coding: utf-8 -*-
"""
A系列第2轮 · 最终版落地（双版本对照：无确认 V0 = A2 原版 vs 有确认 V1 = 叠加阶段4二次确认）
================================================================
long  = SL4% · TP1 1.25R · TP2 3.0R（网格历遍确认的普适最优 TP1=1.25R）
short = A1：ATR≥30 & mom20<0.5 · SL4% · TP1 1.5R · TP2 5.03R
V0 = A2 原版（无二次确认）      V1 = 叠加 stage4 二次确认（仅簇内 pos>=2, gap=4）
量尺：两年 + 同(sym,dir)单笔并发；导出净额（扣 fee+SL滑点）；无未来窥探（NOW 硬截止）。
"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_trade_cards as CARDS

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')
TAKER_EACH = 0.0005
SL_SLIP_MED = 1.14
GAP = 4

LONG_P = dict(sl=0.04, tp1=1.25, tp2=3.0)
SHORT_SEL = lambda c: c['atr_pct'] >= 30 and c['mom20'] < 0.5
SHORT_P = dict(sl=0.04, tp1=1.5, tp2=5.03)


def cand_key(c):
    return (c['sym'], c['d'], c['date'], str(c['day_close']))


# 二次确认标注（pos20 过滤后的 POOL 全集上聚类）
_INFO = C.cluster_label(M.POOL, GAP)
_CONF = {k: v[1] >= 2 for k, v in _INFO.items()}


def run(c, lp):
    t = M.run_trade_a(c, lp['sl'], lp['tp1'], lp['tp2'], 0.5)
    if t is None:
        return None
    t['date'] = c['date']  # entry 保留 run_trade_a 算出的实际成交价
    return t


def build(use_confirm):
    allc = []
    for c in M.POOL:
        if use_confirm and not _CONF[cand_key(c)]:
            continue
        if c['d'] == 'long':
            t = run(c, LONG_P)
        else:
            if not SHORT_SEL(c):
                continue
            t = run(c, SHORT_P)
        if t:
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
    return kept, blocked


def cost(kept):
    for t in kept:
        fee = TAKER_EACH * 2 * 100
        slip = t['sl_dist'] * (SL_SLIP_MED - 1.0) if t['outcome'] == 'SL' else 0.0
        t['fee'] = fee
        t['slip'] = slip
        t['ret_gross'] = t['ret']
        t['ret'] = t['ret'] - fee - slip


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, avg=0.0, total=0.0, pf=0.0, mdd=0.0)
    rets = [t['ret'] for t in ts]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1 + r / 100); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    return dict(n=len(ts), wr=len(wins) / len(ts) * 100, avg=sum(rets) / len(rets),
                total=sum(rets), pf=pf, mdd=mdd * 100)


def wneg(ts):
    r = M.wsums(ts)
    return len(r), sum(1 for x in r if x < 0)


for use_confirm, tag in ((False, 'V0 无确认'), (True, 'V1 有确认')):
    kept, blocked = build(use_confirm)
    cost(kept)
    G = agg(kept); Gl = agg([t for t in kept if t['d'] == 'long'])
    Gs = agg([t for t in kept if t['d'] == 'short'])
    fee_sum = sum(t['fee'] for t in kept); slip_sum = sum(t['slip'] for t in kept)
    win_s = max(wneg(kept), (0, 0))
    print(f'[{tag}] 毛单利 +{sum(t["ret_gross"] for t in kept):.1f}% → 净单利 +{G["total"]:.1f}% ｜ 成本 fee {fee_sum:.1f}+滑点 {slip_sum:.1f}')
    print(f'  合计: n={G["n"]} WR {G["wr"]:.1f}% 平均 {G["avg"]:+.2f}% PF {G["pf"]:.2f} 回撤 {G["mdd"]:.1f}% ｜ 滚动{win_s[0]}窗/{win_s[1]}负')
    print(f'  long: n={Gl["n"]} WR {Gl["wr"]:.1f}% 单利 {Gl["total"]:+.1f}% PF {Gl["pf"]:.2f} ｜ short: n={Gs["n"]} WR {Gs["wr"]:.1f}% 单利 {Gs["total"]:+.1f}% PF {Gs["pf"]:.2f}')

    df = pd.DataFrame(kept)
    csv = os.path.join(OUT, f'stageA2_{"V1c" if use_confirm else "V0"}_trades.csv')
    html = os.path.join(OUT, f'stageA2_{"V1c" if use_confirm else "V0"}_trade_cards.html')
    df.to_csv(csv, index=False, encoding='utf-8-sig')
    CARDS.build(csv, html,
                f'A2-{tag} · long TP1=1.25R/TP2=3.0R + short A1',
                f'{"叠加阶段4二次确认(簇内pos>=2, gap=4天)" if use_confirm else "无二次确认"} · int 同标的同时单笔 · 两年 · 净额已扣成本 · 含实际入场价')