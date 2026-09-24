# -*- coding: utf-8 -*-
"""
A系列第2轮 · walk-forward (WFO) 切分验证 —— long TP 参数是否 in-sample 过拟合
================================================================
背景：A2/V1 的 long TP1=1.25R 是在两整年历史全场 in-sample 选出的最优，需验证稳健性。
方案：时间序列 WFO（交易生成无未来，参数外推）
  1. 候选按 day_close 有序；二次确认「簇内 pos>=2」只看该候选之前的同簇信号（无未来）
  2. 对每个切分点 mid：训练窗 [start, mid) 独立扫 long TP1 → 在训练窗内选「合计单利最高」的 TP1
  3. 用训练选出的 TP1 全程跑（含跨窗并发），只 report 验证窗 [mid, end) 的 OOS 表现
  4. 多切分点滑动聚合；并检查训练最优 TP1 是否落在「各验证窗自身最优」的平台内
输出：控制台 + results/stageA2_wfo.txt
"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stage4_common as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stageA2_mine as M

GAP = 4
TP1S = [1.0, 1.25, 1.5, 2.0, 2.56]
TP2 = 3.0
SL = 0.04
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'results')


def cand_key(c):
    return (c['sym'], c['d'], c['date'], str(c['day_close']))


# 确认判定：pos>=2 = 该候选之前同(sym,d) g 天内已有信号（历史信息，无未来）
_INFO = C.cluster_label(M.POOL, GAP)
CONF = {k: v[1] >= 2 for k, v in _INFO.items()}

# 有序候选
POOL = sorted(M.POOL, key=lambda c: c['day_close'])


def run_pool(tp1, candset):
    """用给定 long TP1 在 candset（有序候选子集）上跑：确认过滤 + 并发过滤，返回 kept。"""
    allc = []
    for c in candset:
        if not CONF[cand_key(c)]:          # 二次确认：非簇首
            continue
        if c['d'] == 'long':
            t = M.run_trade_a(c, SL, tp1, TP2, 0.5)
        else:
            if not M.SHORT_SEL(c):
                continue
            t = M.run_trade_a(c, M.SHORT_P['sl'], M.SHORT_P['tp1'], M.SHORT_P['tp2'], 0.5)
        if t:
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


def agg(ts):
    if not ts:
        return dict(n=0, wr=0.0, total=0.0, pf=0.0)
    rets = [t['ret'] for t in ts]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    return dict(n=len(ts), wr=len(wins) / len(ts) * 100, total=sum(rets), pf=pf)


lines = []
def log(s=''):
    print(s); lines.append(s)


# ============ ① 基准：全场最优（对照）============
base_full = run_pool(1.25, POOL)
g = agg(base_full); gl = agg([t for t in base_full if t['d'] == 'long'])
log(f'基准 全场 TP1=1.25R｜合计 n={g["n"]} WR {g["wr"]:.1f}% 单利 {g["total"]:+.1f}% PF {g["pf"]:.2f} ｜ long n={gl["n"]} WR {gl["wr"]:.1f}% 单利 {gl["total"]:+.1f}%')

# ============ ② WFO 切分 ============
MIDS = [0.45, 0.55, 0.65]      # 训练窗占前 45%/55%/65%，验证窗为剩余
log('\n' + '=' * 104)
log('② WFO：训练窗独立选 long TP1 → 外推到验证窗（OOS）')
log('=' * 104)

oos_rows = []
for frac in MIDS:
    bidx = int(len(POOL) * frac)
    bound = POOL[bidx]['day_close']
    train_set = [c for c in POOL if c['day_close'] < bound]
    valid_set = [c for c in POOL if c['day_close'] >= bound]
    # --- 训练窗选参 ---
    best_tp, best_gl, best_info = None, -1e9, None
    plat = []
    for tp in TP1S:
        kt = run_pool(tp, train_set)
        kl = [t for t in kt if t['d'] == 'long']
        al = agg(kl)
        plat.append((tp, al['n'], al['wr'], al['total'], al['pf']))
        if al['total'] > best_gl:
            best_gl, best_tp = al['total'], tp
    # --- 验证窗(该参数) OOS ---
    run_all = run_pool(best_tp, POOL)                 # 全窗跑，保持跨窗并发
    v_run = [t for t in run_all if t['entry_ts'] >= bound]
    vg = agg(v_run); vl = agg([t for t in v_run if t['d'] == 'long'])
    # --- 验证窗自身最优（评估漂移）---
    vbest_tp, vbest_gl = None, -1e9
    for tp in TP1S:
        vv = [t for t in run_pool(tp, POOL) if t['entry_ts'] >= bound]
        vt = agg([t for t in vv if t['d'] == 'long'])['total']
        if vt > vbest_gl:
            vbest_gl, vbest_tp = vt, tp
    log(f'切分点 {frac:.0%}  boundary={bound:%y-%m-%d} 训练窗选 long TP1={best_tp} (单利{best_gl:+.0f})')
    log(f'   训练窗平台: ' + '  '.join(f'TP1{t:>4} n={n}|WR{w:.0f}|单利{s:+.0f}' for (t, n, w, s, _) in plat))
    log(f'   → [OOS验证] TP1={best_tp} 合计 n={vg["n"]} WR {vg["wr"]:.1f}% 单利 {vg["total"]:+.1f}% PF {vg["pf"]:.2f} ｜ long n={vl["n"]} WR {vl["wr"]:.1f}% 单利 {vl["total"]:+.1f}%  ｜(验证窗自身最优 TP1={vbest_tp} 单利{vbest_gl:+.0f})')
    oos_rows.append((frac, best_tp, vg['n'], vg['total'], vg['pf'], vg['wr'], vbest_tp))

# ============ ③ 汇总 ============
log('\n' + '=' * 104)
log('③ WFO 汇总')
log('=' * 104)
for frac, tp, n, tot, pf, wr, vbt in oos_rows:
    consistent = '训练→验证一致' if (tp == 1.25 and vbt in (1.0, 1.25)) or (vbt == tp) else f'漂移(验证优={vbt})'
    log(f'  切分{frac:.0%}: 训练选 TP1={tp}, OOS 验证 n={n} WR {wr:.1f}% 单利 {tot:+.1f}% PF {pf:.2f} ｜ {consistent}')
tot = sum(r[3] for r in oos_rows); n = sum(r[2] for r in oos_rows)
log(f'\n  OOS 验证三段合计: n={n} 单利 {tot:+.1f}%（含全局并发，跑在各自不见于训练的参数上）')

with open(os.path.join(OUT, 'stageA2_wfo.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'\n已导出 → {OUT}/stageA2_wfo.txt')