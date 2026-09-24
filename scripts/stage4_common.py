# -*- coding: utf-8 -*-
"""
阶段4 · 公共模块（两年数据 + 候选 + 交易模拟 + 簇标注）
================================================================
- 数据：1DUTC 900 根（2024-04-02 ~ 2026-09-18）、4H 5100 根（2024-05-21 ~ 2026-09-18）
- 回测口径与阶段3一致：限价回踩 mid∓0.5ATR + 24h 兜底，SL 锚入场价，同根 SL 优先
- 新增：候选可带方向集合、方向独立 SL/TP 参数、簇标注（按 同标的×方向 × 间隔天数）
"""
import os, json, glob, importlib.util
import pandas as pd
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE) if os.path.isdir(os.path.join(os.path.dirname(_HERE), 'data')) else _HERE
RAW = os.path.join(_ROOT, 'data', 'okx_raw')
SCANNER = os.path.join(_HERE, 'csb_signal_scanner.py')

spec = importlib.util.spec_from_file_location('S', SCANNER)
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)

INSTS = {'BTC-USDT': 'BTC-USDT-SWAP', 'ETH-USDT': 'ETH-USDT-SWAP'}
NOW = pd.Timestamp('2026-09-18 02:00:00', tz='UTC')
WIN_DAYS, STEP_DAYS = 90, 30
LIMIT_OFF = 0.5
LIMIT_BARS = 6


def load(inst, bar):
    rows = {}
    for fp in glob.glob(os.path.join(RAW, f'{inst}_{bar}_*.json')):
        for k in json.load(open(fp, encoding='utf-8'))['data']:
            rows[int(k[0])] = k
    ts = sorted(rows)
    return pd.DataFrame([{'timestamp': pd.Timestamp(t, unit='ms', tz='UTC'),
                          'open': float(rows[t][1]), 'high': float(rows[t][2]),
                          'low': float(rows[t][3]), 'close': float(rows[t][4])} for t in ts]).reset_index(drop=True)


DAILY, H4, H4_START = {}, {}, {}
for sym, inst in INSTS.items():
    d = load(inst, '1DUTC')
    f = load(inst, '4H')
    d['close_time'] = d['timestamp'] + pd.Timedelta(hours=24)
    f['close_time'] = f['timestamp'] + pd.Timedelta(hours=4)
    DAILY[sym] = d; H4[sym] = f; H4_START[sym] = f['timestamp'].iloc[0]


def add_features(df):
    c, h, l = df['close'], df['high'], df['low']
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = np.maximum(h - l, np.maximum((h - c.shift()).abs(), (l - c.shift()).abs()))
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    sma20 = c.rolling(20).mean()
    sma50 = c.rolling(50).mean()
    df['pos20_atr'] = ((c - sma20) / atr).values
    df['mom20'] = (c / c.shift(20) - 1) * 100
    df['sma20_lt_50'] = (sma20 < sma50).values
    df['close_lt_50'] = (c < sma50).values
    df['atr_pct'] = atr.rolling(100).apply(lambda x: (x.iloc[-1] > x).mean() * 100, raw=False).values
    return df


for sym in DAILY:
    S.build_daily(DAILY[sym])
    add_features(DAILY[sym])


def detect_candidates(dirs=('long', 'short')):
    out = []
    for sym in INSTS:
        df = DAILY[sym]
        for i in range(S.CONFIG['warm_days'], len(df)):
            day_close = df['close_time'].iloc[i]
            if day_close > NOW or day_close < H4_START[sym]:
                continue
            d = S.dir_full(df, i)
            if d is None or d not in dirs:
                continue
            g = S.touch_gap(df, i, d); b = S.breakout_day(df, i, d)
            if g > S.CONFIG['touch_max'] or b is None or i - b > S.CONFIG['breakout_max']:
                continue
            pname, pv = S.best_pivot(df, i, d)
            if pv is None or (isinstance(pv, float) and np.isnan(pv)):
                continue
            atr = df['ATR'].iloc[i]
            if np.isnan(atr) or atr <= 0:
                continue
            zlo, zhi, mid = S.mid_zone(pv, atr)
            lv = S.calc_levels(d, mid, zlo, zhi)
            ap = df['atr_pct'].iloc[i]
            if np.isnan(ap):
                ap = 50.0
            out.append(dict(sym=sym, i=i, date=str(df['timestamp'].iloc[i])[:10], d=d,
                            day_close=day_close, day_close_px=float(df['close'].iloc[i]),
                            zlo=zlo, zhi=zhi, mid=mid, sl_mid=lv['sl'], pivot=pname,
                            atr=float(atr), pos20=float(df['pos20_atr'].iloc[i]),
                            mom20=float(df['mom20'].iloc[i]),
                            s20lt50=bool(df['sma20_lt_50'].iloc[i]),
                            clt50=bool(df['close_lt_50'].iloc[i]),
                            gap=int(g), atr_pct=float(ap)))
    out.sort(key=lambda x: (x['day_close'], x['sym']))
    return out


def run_trade(c, sl_pct=0.04, tp1_r=2.56, tp2_r=3.0):
    f4 = H4[c['sym']]
    d = c['d']
    entry = c['day_close_px']
    fidx = f4.index[f4['timestamp'] >= c['day_close']]
    if len(fidx) == 0 or f4['close_time'].iloc[fidx[0]] > NOW:
        return None
    j0 = int(fidx[0])
    j = j0
    limit = c['mid'] - LIMIT_OFF * c['atr'] if d == 'long' else c['mid'] + LIMIT_OFF * c['atr']
    for k in range(j0, min(j0 + LIMIT_BARS, len(f4))):
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
    mae = mfe = 0.0
    out = px = None; jj = len(f4) - 1
    for k in range(j, len(f4)):
        r = f4.iloc[k]
        if d == 'long':
            mae = max(mae, (entry - r['low']) / entry)
            mfe = max(mfe, (r['high'] - entry) / entry)
            if r['low'] <= sl:   out, px, jj = 'SL', sl, k; break
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
    return dict(sym=c['sym'], date=c['date'], d=d, entry=entry, sl=sl, R=R,
                sl_dist=abs(entry - sl) / entry * 100,
                tp1=tp1, tp2=tp2, outcome=out, ret=ret, bars=jj - j,
                mae=mae * 100, mfe=mfe * 100,
                entry_ts=f4['timestamp'].iloc[j],
                exit_ts=f4['timestamp'].iloc[jj] + pd.Timedelta(hours=4),
                mid=c['mid'], atr=c['atr'], pos20=c['pos20'], pos20_abs=abs(c['pos20']),
                mom20=c['mom20'], gap=c['gap'], atr_pct=c['atr_pct'],
                s20lt50=c['s20lt50'], clt50=c['clt50'],
                off_mid=(entry - c['mid']) / c['atr'] if d == 'long' else (c['mid'] - entry) / c['atr'],
                filled=(j != j0))


def agg(ts):
    rets = [t['ret'] for t in ts]
    wins = [x for x in rets if x > 0]; losses = [x for x in rets if x <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1 + r / 100); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf')
    return dict(n=len(ts), wr=len(wins) / len(ts) * 100, avg=sum(rets) / len(rets),
                total=sum(rets), comp=(eq - 1) * 100, pf=pf, mdd=mdd * 100)


def rolling(ts):
    if not ts:
        return []
    e0 = pd.Timestamp(min(t['entry_ts'] for t in ts)).floor('D') - pd.Timedelta(days=7)
    e1 = pd.Timestamp(max(t['entry_ts'] for t in ts)).ceil('D')
    bounds, cur = [], e0
    while cur + pd.Timedelta(days=WIN_DAYS) <= e1:
        bounds.append((cur, cur + pd.Timedelta(days=WIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)
    return [sum(t['ret'] for t in ts if a <= t['entry_ts'] < b) for a, b in bounds]


def cluster_label(cands, gap_days):
    """按 同标的×方向 分组，间隔 <= gap_days 天的连续信号归为同一簇。
    返回 {(sym, d, date, day_close_str): (cluster_id, pos_in_cluster, cluster_size)}
    """
    groups = {}
    for c in cands:
        groups.setdefault((c['sym'], c['d']), []).append(c)
    info = {}
    cid = 0
    for key, lst in groups.items():
        lst.sort(key=lambda x: x['day_close'])
        start = 0
        for idx, c in enumerate(lst):
            k = (c['sym'], c['d'], c['date'], str(c['day_close']))
            if idx > 0 and (c['day_close'] - lst[idx - 1]['day_close']).days > gap_days:
                cid += 1
                start = idx
            info[k] = (cid, idx - start + 1)
        cid += 1
    from collections import Counter
    cc = Counter(v[0] for v in info.values())
    return {k: (v[0], v[1], cc[v[0]]) for k, v in info.items()}
