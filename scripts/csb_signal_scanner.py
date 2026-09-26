# -*- coding: utf-8 -*-
"""
S系统 v0.3 · 实盘扫描器（S-28 落地档：紧止损 多2.2%/空2.05%，SL/TP锚MID）
=================================================================
- 数据源：MEXC 公共行情 API（无需 Key），BTC-USDT / ETH-USDT 永续
- 扫描频率：每4小时（GitHub Actions cron 调用，与项目约定一致）
- 逻辑：完全移植冻结系统 Layer1~4 + 5 4H确认，与回测 detect 一致
- 无未来函数：只用最新一根【已收盘】日线做信号日；4H确认只数【此刻已收盘】的 bar
- 输出：触发信号 → 飞书交易卡（MID锚定 SL/TP）；未触发 → 飞书"等待信号中"状态卡
- 去重：GitHub Actions 内用 GITHUB_TOKEN 走 Contents API 持久化 state.json；本地用同目录 state.json
- 已推送标记 (symbol|date|dir)，避免重复轰炸

用法：
    python s28_live_scanner.py            # 正常扫描（读 env FEISHU_WEBHOOK；CI 内自动用 GITHUB_TOKEN 去重）
    python s28_live_scanner.py --dry-run  # 只打印卡内容，不发送飞书

需要环境变量：FEISHU_WEBHOOK（飞书机器人的 webhook URL）；CI 内 GITHUB_TOKEN/GITHUB_REPOSITORY 由 Actions 自动注入
"""
import os, io, sys, time, json, base64
import urllib.request
import numpy as np
import pandas as pd

# ---------------- 时间工具（pandas 2.x / 3.x 兼容） ----------------
def as_utc(x):
    """把任意时间量统一成 tz-aware 的 UTC pandas 时间戳。

    背景（2026-09-17 线上连续报错根因）：
    tz-aware 时间列取 `.values` 得到的是 **tz-naive** 的 datetime64（时区被丢弃，
    实测 pandas 2.3.3 与 3.0.x 均如此；`.array` / 逐元素取值才保留 tz）。
    一旦拿它和 tz-aware 的 now 比较，pandas 直接抛
    TypeError: Cannot compare tz-naive and tz-aware timestamps。
    故所有时间比较一律先过本函数，**不要用 .values 取时间列**。
    """
    t = pd.Timestamp(x)
    if t.tzinfo is None:
        return t.tz_localize('UTC')
    return t.tz_convert('UTC')


# ---------------- 配置（冻结参数，落地档仅改止损） ----------------
CONFIG = {
    'symbols':        ['BTC-USDT', 'ETH-USDT'],
    'sl_long':        0.022,          # S-28 落地档多单止损 2.2%
    'sl_short':       0.0205,         # S-28 落地档空单止损 2.05%
    'tp1_r':          2.56,
    'tp2_r':          5.03,
    'zone_atr':       1.0,            # Pivot ± 1ATR
    'touch_max':      3,              # 触锚≤3天
    'breakout_max':   5,              # 突破≤5天
    'warm_days':      70,             # 指标预热
    'da_span':        400,            # 拉取日线根数
    'f4_span':        2000,           # 拉取4H根数（≈333天）
    'confirm_4h':     12,             # 4H确认窗口 48h
}
MEXC_INTERVAL = {'1d': '1d', '4h': '4h'}
API = 'https://api.mexc.com/api/v3/klines'

# ---------------- 数据获取（MEXC 公共 API） ----------------
# 本地（Windows/代理环境）用 curl.exe 走代理；CI/海外直连（MEXC_PROXY 置空）用 urllib。
# 环境变量 MEXC_PROXY 覆盖：本地默认 http://127.0.0.1:7897，GitHub Actions 置空直连。
import subprocess

PROXY = os.environ.get('MEXC_PROXY', 'http://127.0.0.1:7897').strip()


def fetch_klines(symbol, interval, limit):
    url = f'{API}?symbol={symbol}&interval={interval}&limit={limit}'
    last_err = None
    for attempt in range(5):
        try:
            if PROXY:
                cmd = ['curl.exe', '-sS', '--max-time', '30', '-H', 'User-Agent: trae',
                       '-x', PROXY, url]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise RuntimeError(proc.stderr.strip())
                raw = json.loads(proc.stdout)
            else:
                req = urllib.request.Request(url, headers={'User-Agent': 'trae'})
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = json.loads(r.read().decode())
            break
        except Exception as e:
            last_err = e
            time.sleep(1 + attempt)
    else:
        raise RuntimeError(f'拉取失败 {symbol}: {last_err}')
    rows = []
    for k in raw:
        rows.append({
            'timestamp': pd.Timestamp(k[0], unit='ms', tz='UTC'),  # 显式带 tz，避免 tz-naive
            'open': float(k[1]), 'high': float(k[2]),
            'low': float(k[3]), 'close': float(k[4]), 'volume': float(k[5]),
        })
    df = pd.DataFrame(rows).reset_index(drop=True)
    return df

def load_data():
    dl, fl = {}, {}
    for inst in CONFIG['symbols']:
        sym = inst.replace('-', '')
        dl[inst] = fetch_klines(sym, '1d', CONFIG['da_span'])
        fl[inst] = fetch_klines(sym, '4h', CONFIG['f4_span'])
        # 收盘时间列
        dl[inst]['close_time'] = dl[inst]['timestamp'] + pd.Timedelta(hours=24)
        fl[inst]['close_time'] = fl[inst]['timestamp'] + pd.Timedelta(hours=4)
    return dl, fl

# ---------------- 指标/结构（与回测完全一致） ----------------
def build_daily(df):
    c = df['close']; h = df['high']; l = df['low']
    df['MA20']  = c.rolling(20).mean()
    df['EMA26'] = c.ewm(span=26).mean()
    df['EMA50'] = c.ewm(span=50).mean()
    df['h20']   = h.rolling(20).max()
    df['l20']   = l.rolling(20).min()
    df['mid20'] = (df['h20'] + df['l20']) / 2
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()
    df['lo'] = l; df['hi'] = h
    return df

def dir_full(df, i):
    R = df.iloc[i]; c = R['close']
    if c > R['MA20'] and c > R['EMA26'] and (R['h20'] - c) / c * 100 < 6.0:
        return 'long'
    if c < R['MA20'] and c < R['EMA26'] and (c - R['l20']) / c * 100 < 6.0:
        return 'short'
    return None

def touch_gap(df, i, d):
    lo = df['lo'].values; hi = df['hi'].values; anch = df['EMA26'].values
    for j in range(i - 1, 0, -1):
        a = anch[j]
        if pd.isna(a): continue
        if d == 'long' and lo[j] <= a: return i - j
        if d == 'short' and hi[j] >= a: return i - j
    return 99

def breakout_day(df, i, d):
    c = df['close'].values; em = df['EMA26'].values; ma = df['MA20'].values
    for j in range(i - 1, 59, -1):
        if d == 'long':
            flag = c[j] > em[j] and c[j] > ma[j] and not(c[j-1] > em[j-1] and c[j-1] > ma[j-1])
        else:
            flag = c[j] < em[j] and c[j] < ma[j] and not(c[j-1] < em[j-1] and c[j-1] < ma[j-1])
        if flag: return j
    return None

def last_fractal(df, max_i, d):
    h = df['high'].values; l = df['low'].values
    for m in range(max_i - 2, 1, -1):
        if d == 'long' and l[m] < l[m-1] and l[m] < l[m-2] and l[m] < l[m+1] and l[m] < l[m+2]:
            return (m, df['low'].iloc[m])
        if d == 'short' and h[m] > h[m-1] and h[m] > h[m-2] and h[m] > h[m+1] and h[m] > h[m+2]:
            return (m, df['high'].iloc[m])
    return None

def best_pivot(df, i, d):
    R = df.iloc[i]; close = R['close']; atr = R['ATR']
    bot = last_fractal(df, i, 'long'); top = last_fractal(df, i, 'short')
    pool = {'mid20': R['mid20'], 'ema26': R['EMA26'], 'ema50': R['EMA50'], 'ma20': R['MA20']}
    pool['分型'] = (bot[1] if d == 'long' and bot else (top[1] if d == 'short' and top else None))
    best = None; bs = -999
    for name, pv in pool.items():
        if pv is None or np.isnan(pv): continue
        s = max(0.0, 1.0 - abs(close - pv) / (3 * atr))
        if d == 'long':
            if close > pv: s += 1.0
            if (close - pv) <= 1.5 * atr: s += 0.5
        else:
            if close < pv: s += 1.0
            if (pv - close) <= 1.5 * atr: s += 0.5
        if s > bs: bs = s; best = (name, pv)
    return best

# ---------------- 信号与 4H 确认（无未来函数） ----------------
def mid_zone(pv, atr):
    zlo, zhi = pv - atr, pv + atr
    mid = (zlo + zhi) / 2.0
    return zlo, zhi, mid

def calc_levels(d, mid, zlo, zhi):
    sl_pct = CONFIG['sl_long'] if d == 'long' else CONFIG['sl_short']
    sl = mid * (1 - sl_pct) if d == 'long' else mid * (1 + sl_pct)
    Rv = abs(mid - sl)
    if Rv <= 0: return None
    tp1 = mid + CONFIG['tp1_r'] * Rv if d == 'long' else mid - CONFIG['tp1_r'] * Rv
    tp2 = mid + CONFIG['tp2_r'] * Rv if d == 'long' else mid - CONFIG['tp2_r'] * Rv
    return {'zlo': zlo, 'zhi': zhi, 'mid': mid, 'sl': sl, 'Rv': Rv,
            'tp1': tp1, 'tp2': tp2, 'risk_pct': sl_pct}

def is_short(d): return d == 'short'

def zone_confirm_live(f4, day_close, d, zlo, zhi, now):
    """只看【已收盘】4H bar：确认 window=48h。返回 (confirm_j, touch_j) 或 None。

    时间列一律逐元素转 tz-aware UTC（不要用 .values，pandas 3.x 会丢时区）。
    """
    now = as_utc(now)
    day_close = as_utc(day_close)
    ct = [as_utc(x) for x in f4['close_time']]
    idx = [j for j in range(len(f4)) if ct[j] <= now]
    if not idx: return None
    # 找信号日收盘后的第一个 bar
    start = None
    for j in idx:
        if ct[j] > day_close: start = j; break
    if start is None: return None
    end = min(start + CONFIG['confirm_4h'], len(f4))
    touch = None
    for j in range(start, end):
        if ct[j] > now: break
        R = f4.iloc[j]
        if d == 'long' and R['low'] <= zhi: touch = j; break
        if d == 'short' and R['high'] >= zlo: touch = j; break
    if touch is None: return None
    for j in range(touch, min(touch + 1 + CONFIG['confirm_4h'], len(f4))):
        if ct[j] > now: break
        c4 = f4.iloc[j]['close']
        if d == 'long' and c4 > zhi: return (j, touch)
        if d == 'short' and c4 < zlo: return (j, touch)
    return None

def line_status(df, i, d):
    """候选生命周期快照用于卡片。"""
    g = touch_gap(df, i, d); b = breakout_day(df, i, d)
    return g, (None if b is None else i - b)

def scan_latest(dl, fl, now):
    """扫描最新一根已收盘日线，返回 {inst: status}，status ∈ signal/pending/none。"""
    out = {}
    now = as_utc(now)
    for inst in CONFIG['symbols']:
        df = dl[inst]; f4 = fl[inst]
        build_daily(df)
        # 最新已收盘日线 index
        sig_i = None
        for i in range(len(df) - 1, -1, -1):
            if as_utc(df['close_time'].iloc[i]) <= now: sig_i = i; break
        rec = {'inst': inst, 'sig_i': sig_i,
               'date': str(df['timestamp'].iloc[sig_i])[:10] if sig_i is not None else None}
        if sig_i is None or sig_i < CONFIG['warm_days']:
            out[inst] = dict(rec, status='none', reason='预热不足'); continue
        d = dir_full(df, sig_i)
        rec['dir'] = d
        if d is None:
            out[inst] = dict(rec, status='none', reason='无方向趋势'); continue
        g = touch_gap(df, sig_i, d)
        b = breakout_day(df, sig_i, d)
        rec['gap'] = g; rec['b'] = b
        if g > CONFIG['touch_max'] or b is None or sig_i - b > CONFIG['breakout_max']:
            out[inst] = dict(rec, status='none', reason='未在触发窗口')
            continue
        pname, pv = best_pivot(df, sig_i, d)
        if pv is None or np.isnan(pv) or np.isnan(df['ATR'].iloc[sig_i]) or df['ATR'].iloc[sig_i] <= 0:
            out[inst] = dict(rec, status='none', reason='无有效Pivot'); continue
        zlo, zhi, mid = mid_zone(pv, df['ATR'].iloc[sig_i])
        lv = calc_levels(d, mid, zlo, zhi)
        Rbar = df.iloc[sig_i]
        rec.update({'d': d, 'pivot': pname, 'zlo': zlo, 'zhi': zhi, 'close': float(Rbar['close']),
                    'level': lv})
        conf = zone_confirm_live(f4, df['close_time'].iloc[sig_i], d, zlo, zhi, now)
        if conf is not None:
            rec.update(status='signal', confirm_j=conf[0], touch_j=conf[1])
        else:
            rec.update(status='pending', confirm_j=None)
        out[inst] = rec
    return out

# ---------------- 飞书推送 ----------------
def feishu_card(card, webhook):
    payload = {'msg_type': 'interactive', 'card': card}
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def money(x, dec=None):
    if x is None: return '—'
    s = f'{x:,.0f}'
    return s

def signal_card(rec):
    lv = rec['level']; d = rec['d']
    long = d == 'long'
    col = '#16b364' if long else '#f04438'
    dlab = 'LONG 做多' if long else 'SHORT 做空'
    pvname = rec.get('pivot') or '—'
    header = f"{rec['inst'].replace('-USDT','')} · {dlab} · {rec['date']}"
    el = []
    def t(line): return {'tag': 'div', 'text': {'tag': 'lark_md', 'content': line}}
    el.append(t(f"**{header}**"))
    el.append(t(f"📌 Pivot锚点: **{pvname}** = {money(rec['level']['mid'])} ｜ 触锚 {rec['gap']}天前 ｜ 突破{(rec['b']-rec['sig_i'])}"))
    b_days = '' if rec.get('b') is None else (rec['sig_i'] - rec['b'])
    el.append(t(f"生命周期: 突破第{b_days}天 ｜ 入场区间 = {pvname}±1ATR"))
    el.append(t(f"🏛 入场区间: **{money(lv['zlo'])} ~ {money(lv['zhi'])}** (中 {money(lv['mid'])})"))
    el.append(t(f"🛑 止损(MID锚定): **{money(lv['sl'])}** 风险 {lv['risk_pct']*100:.2f}%"))
    el.append(t(f"✅ TP1 (2.56R): **{money(lv['tp1'])}**"))
    el.append(t(f"🚀 TP2 (5.03R): **{money(lv['tp2'])}**"))
    el.append(t(f"⚠️ 出手确认: 待机会调度/人工确认 (第6层)"))
    return {'header': {'title': {'tag': 'plain_text', 'content': f"S-系统信号 · {rec['inst']} 做{'多' if long else '空'}"}},
            'elements': el}

def status_card(results, now):
    el = []
    def t(line): return {'tag': 'div', 'text': {'tag': 'lark_md', 'content': line}}
    el.append(t("**⏳ 等待信号中 · S-系统 v0.3（紧止损档）**"))
    el.append(t(f"⏰ 扫描时刻: {now.strftime('%Y-%m-%d %H:%M')} (UTC)"))
    for inst, rec in results.items():
        sym = inst.replace('-USDT', '')
        if rec['status'] == 'signal':
            el.append(t(f"🔴 **{sym}**: 信号触发！见交易卡"))
        elif rec['status'] == 'pending':
            el.append(t(f"🟡 **{sym}**: 命中日线候选，等待4H回方向确认中"))
        else:
            d = rec.get('dir')
            ds = ({'long': '多头'}.get(d) or '空头' if d else '无方向')
            el.append(t(f"⚪ **{sym}**: {rec.get('reason','')} (方向:{ds})"))
    return {'header': {'title': {'tag': 'plain_text', 'content': "S-系统 · 等待信号中"}},
            'elements': el}

# ---------------- 去重状态 ----------------
def load_seen(path):
    try:
        with open(path, encoding='utf-8') as f: return set(json.load(f))
    except Exception:
        return set()

def save_seen(path, s):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sorted(s), f, ensure_ascii=False, indent=2)

# 状态文件：默认放脚本同目录 state.json，可用 env STATE_FILE 覆盖（供 GitHub state-branch 复用）
def state_path():
    return os.environ.get('STATE_FILE',
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state.json'))

# ---------------- GitHub 去重状态（CI 内用 GITHUB_TOKEN 走 Contents API） ----------------
def _token_from_git():
    """从 actions/checkout 写入的 git 凭据（local+global+system）提取运行时 GITHUB_TOKEN。"""
    import subprocess
    def extract(out):
        low = out.lower()
        if 'basic' in low:
            b64 = out.split('basic', 1)[1].split(']', 1)[0].strip().rstrip('"')
            dec = base64.b64decode(b64 + '=' * (-len(b64) % 4)).decode(errors='ignore')
            if 'x-access-token:' in dec:
                return dec.split('x-access-token:', 1)[1].strip()
        if 'bearer' in low:
            return out.rsplit('Bearer', 1)[1].split(']', 1)[0].strip().rstrip('"')
        return ''
    for args in (['config', '--list', '--show-origin'],
                 ['config', '--global', '--list']):
        try:
            out = subprocess.check_output(['git'] + args, text=True,
                                          stderr=subprocess.DEVNULL, timeout=10)
            for line in out.splitlines():
                if 'extraheader' in line.lower() and ('auth' in line.lower() or 'http' in line.lower()):
                    tok = extract(line.split('=', 1)[1] if '=' in line else line)
                    if tok:
                        return tok
        except Exception:
            continue
    return ''

def gh_repo_path():
    tok = os.environ.get('GITHUB_TOKEN', '').strip()
    if not tok:
        tok = _token_from_git()
    repo = os.environ.get('GITHUB_REPOSITORY', '').strip()
    if tok and repo:
        return tok, f'https://api.github.com/repos/{repo}/contents/state.json'
    return None, None

def gh_read_seen(tok, url):
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {tok}',
                                               'Accept': 'application/vnd.github.v3+json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        seen = set(json.loads(base64.b64decode(j['content']).decode('utf-8')))
        return seen, j['sha']
    except Exception:
        return set(), None

def gh_write_seen(tok, url, sha, items):
    body = {'message': f"update state {len(items)} keys", 'content':
            base64.b64encode(json.dumps(sorted(items), ensure_ascii=False).encode()).decode()}
    if sha: body['sha'] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={'Authorization': f'Bearer {tok}',
                                          'Accept': 'application/vnd.github.v3+json'}, method='PUT')
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status

# ---------------- 主流程 ----------------
def main():
    dry = '--dry-run' in sys.argv
    now = as_utc(pd.Timestamp.now(tz='UTC'))   # 原 Timestamp.utcnow() 在 pandas 3.x 已弃用
    webhook = os.environ.get('FEISHU_WEBHOOK', '').strip()
    if not webhook and not dry:
        print('缺少 FEISHU_WEBHOOK 环境变量'); return 1
    # 排除尚未收盘的4H，避免用未收盘bar
    print(f'[fetch] {now} UTC')
    dl, fl = load_data()
    results = scan_latest(dl, fl, now)
    # 去重状态：CI 内优先用 GitHub Contents API（免改 workflow），本地用 state.json
    gh_tok, gh_url = gh_repo_path()
    seen_sha = None
    if gh_tok:
        seen, seen_sha = gh_read_seen(gh_tok, gh_url)
        print(f'[gh-state] loaded {len(seen)} keys from {gh_url}')
    else:
        seen_path = state_path()
        seen = load_seen(seen_path)
    seen0 = len(seen)
    for inst, rec in results.items():
        if rec['status'] == 'signal':
            key = f"{inst}|{rec['date']}|{rec['d']}"
            if key in seen:
                rec['posted'] = 'already'; continue
            card = signal_card(rec)
            if dry:
                print('[SIGNAL][dry]', key, json.dumps(card, ensure_ascii=False)[:400])
            else:
                resp = feishu_card(card, webhook)
                print('[SIGNAL]', key, '->', resp)
            seen.add(key)
    # 状态卡（无论是否触发都发，符合"每次扫描发卡片"约定）
    st_card = status_card(results, now)
    if dry:
        print('[STATUS][dry]', json.dumps(st_card, ensure_ascii=False)[:300])
    else:
        resp = feishu_card(st_card, webhook)
        print('[STATUS] ->', resp)
    if not dry and len(seen) > seen0:  # 仅在新增信号时写状态，避免每次提交
        if gh_tok:
            st = gh_write_seen(gh_tok, gh_url, seen_sha, seen)
            print(f'[gh-state] saved {len(seen)} keys -> HTTP {st}')
        else:
            save_seen(seen_path, seen)
    return 0

if __name__ == '__main__':
    sys.exit(main())