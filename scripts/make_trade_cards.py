# -*- coding: utf-8 -*-
"""
通用「滚动回测逐笔交易卡片」生成器
================================================================
输入：trades.csv（需含列：sym,date,d,entry,sl,tp1,tp2,outcome,ret,bars,mae,mfe,entry_ts,exit_ts[,filled,offset,limit_off]）
输出：自包含 HTML，顶部 = 滚动窗口条带（90天/30步），下方 = 逐笔交易卡片（涨红跌绿，中国习惯）
用法：python make_trade_cards.py <trades.csv> <out.html> <版本名> [描述]
"""
import os, sys
import pandas as pd
import numpy as np

WIN_DAYS, STEP_DAYS = 90, 30


def fmt_ts(s):
    try:
        t = pd.Timestamp(s)
        return str(t)[:10]
    except Exception:
        return str(s)[:10]


def build(trades_csv, out_html, version, desc=''):
    df = pd.read_csv(trades_csv)
    df['entry_ts'] = pd.to_datetime(df['entry_ts'], utc=True)
    df['exit_ts'] = pd.to_datetime(df['exit_ts'], utc=True)
    df = df.sort_values('entry_ts').reset_index(drop=True)
    rets = df['ret'].astype(float)
    wins = rets[rets > 0]; losses = rets[rets <= 0]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        eq *= (1 + r / 100); peak = max(peak, eq); mdd = max(mdd, (peak - eq) / peak)
    pf = abs(wins.sum() / losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
    kpi = dict(n=len(df), wr=len(wins) / len(df) * 100, avg=rets.mean(),
               total=rets.sum(), comp=(eq - 1) * 100, pf=pf, mdd=mdd * 100)

    # 滚动窗口（与回测一致：最早 entry_ts 前 7 天起）
    e0 = pd.Timestamp(df['entry_ts'].iloc[0]).floor('D') - pd.Timedelta(days=7)
    e1 = pd.Timestamp(df['entry_ts'].iloc[-1]).ceil('D')
    bounds = []
    cur = e0
    while cur + pd.Timedelta(days=WIN_DAYS) <= e1:
        bounds.append((cur, cur + pd.Timedelta(days=WIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)

    def wsum(lo, hi):
        sub = df[(df['entry_ts'] >= lo) & (df['entry_ts'] < hi)]
        if len(sub) == 0:
            return None
        rr = sub['ret'].astype(float)
        e2, pk, md = 1.0, 1.0, 0.0
        for r in rr:
            e2 *= (1 + r / 100); pk = max(pk, e2); md = max(md, (pk - e2) / pk)
        return dict(n=len(sub), total=rr.sum(), wr=len(rr[rr > 0]) / len(rr) * 100, mdd=md * 100)

    wins_html = []
    for i, (lo, hi) in enumerate(bounds):
        w = wsum(lo, hi)
        if w is None:
            continue
        cls = 'up' if w['total'] >= 0 else 'down'
        wins_html.append(
            f'<div class="wcard {cls}"><div class="widx">W{i + 1}</div>'
            f'<div class="wrange">{str(lo)[:10]} ~ {str(hi)[:10]}</div>'
            f'<div class="wval">{w["total"]:+.1f}%</div>'
            f'<div class="wsub">n={w["n"]} · 胜率 {w["wr"]:.0f}% · 回撤 {w["mdd"]:.1f}%</div></div>')

    def outcome_badge(o):
        m = {'TP1': ('tp1', '止盈1'), 'TP2': ('tp2', '止盈2'), 'SL': ('sl', '止损'), 'None': ('opn', '未平')}
        cls, label = m.get(o, ('', o))
        return f'<span class="ob {cls}">{label}</span>'

    def dir_badge(d):
        return f'<span class="db {'long' if d == "long" else "short"}">{d.upper()}</span>'

    cards = []
    for _, t in df.iterrows():
        ret = float(t['ret']); cls = 'up' if ret >= 0 else 'down'
        star = ' <span class="star" title="限价回踩成交">★</span>' if (pd.notna(t.get('filled')) and t['filled'] == 1) else ''
        bars = int(t['bars']); days = bars / 6
        entry = float(t['entry'])
        extra = []
        if pd.notna(t.get('sl')):
            extra.append(f'SL {float(t["sl"]):,.0f}')
        if pd.notna(t.get('tp1')):
            extra.append(f'TP1 {float(t["tp1"]):,.0f}')
        sl_dist = f'<div class="tdetail">止损距离 {float(t["sl_dist"]):.2f}% · MAE {float(t["mae"]):.2f}% · MFE {float(t["mfe"]):.2f}%</div>' if pd.notna(t.get('sl_dist')) else ''
        cards.append(
            f'<div class="tcard {cls}">'
            f'<div class="thead"><span class="tdate">{str(t["entry_ts"])[5:10]}</span>'
            f'<span class="tsym">{t["sym"].split("-")[0]}</span>{dir_badge(t["d"])}{outcome_badge(t["outcome"])}{star}</div>'
            f'<div class="tret">{ret:+.2f}%</div>'
            f'<div class="tbody">{entry:,.0f} → {t["outcome"]}{" · ".join(extra) if extra else ""}</div>'
            f'<div class="tdetail">持有 {days:.1f}天（{bars}根4H）</div>{sl_dist}'
            f'</div>')

    # KPI 行
    kpi_html = (
        f'<div class="kpi"><div class="kv">{kpi["n"]}</div><div class="kl">交易笔数</div></div>'
        f'<div class="kpi"><div class="kv">{kpi["wr"]:.1f}%</div><div class="kl">胜率</div></div>'
        f'<div class="kpi"><div class="kv {"up" if kpi["avg"] >= 0 else "down"}">{kpi["avg"]:+.2f}%</div><div class="kl">平均/笔</div></div>'
        f'<div class="kpi"><div class="kv up">{kpi["total"]:+.1f}%</div><div class="kl">累计单利</div></div>'
        f'<div class="kpi"><div class="kv">{kpi["pf"]:.2f}</div><div class="kl">盈亏比 PF</div></div>'
        f'<div class="kpi"><div class="kv down">{kpi["mdd"]:.1f}%</div><div class="kl">最大回撤</div></div>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{version} · 逐笔交易卡片</title>
<style>
:root {{
  color-scheme: light;
  --bg: #F5F5F7; --surface: #FFFFFF; --text: #1A1A1A; --muted: #6E6E78;
  --border: rgba(0,0,0,.1); --up: #D92B1F; --upbg: #FDECEA; --down: #0E9F6E; --downbg: #E6F7F1;
  --brand: #4B3FE3; --warn: #B45309; --warnbg: #FEF3C7;
  --mono: "JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --sans: "SF Pro Text", "PingFang SC", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #131316; --surface: #1D1D21; --text: #E8E8EA; --muted: #9A9AA4;
    --border: rgba(255,255,255,.12); --up: #FF6B5E; --upbg: #3A1D1B; --down: #34D399; --downbg: #0F2E24;
    --brand: #7B6FF2; --warn: #FBBF24; --warnbg: #3A2E10;
  }}
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: var(--bg); color: var(--text); font: 400 14px/1.5 var(--sans); padding: 24px; }}
.page {{ max-width: 1180px; margin: 0 auto; }}
h1 {{ font-size: 22px; font-weight: 700; letter-spacing: -0.3px; }}
.sub {{ color: var(--muted); font-size: 13px; margin-top: 4px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 18px 0; }}
.kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; }}
.kv {{ font: 700 20px var(--mono); }}
.kl {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
.up {{ color: var(--up); }} .down {{ color: var(--down); }}
.windows {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 18px 0; }}
.wcard {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; border-left: 4px solid var(--down); }}
.wcard.up {{ border-left-color: var(--up); }}
.widx {{ font: 700 12px var(--mono); color: var(--muted); }}
.wrange {{ font: 500 11px var(--mono); color: var(--muted); margin-top: 2px; }}
.wval {{ font: 700 20px var(--mono); margin-top: 4px; }}
.wsub {{ color: var(--muted); font-size: 11px; margin-top: 2px; }}
.sect {{ font-size: 15px; font-weight: 600; margin: 22px 0 12px; display: flex; align-items: center; gap: 8px; }}
.sect::after {{ content: ""; flex: 1; height: 1px; background: var(--border); }}
.trades {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }}
.tcard {{ background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px 14px; border-top: 3px solid var(--down); }}
.tcard.up {{ border-top-color: var(--up); }}
.thead {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }}
.tdate {{ font: 600 13px var(--mono); color: var(--text); }}
.tsym {{ font: 600 12px var(--mono); }}
.db {{ font: 700 10px var(--mono); padding: 1px 6px; border-radius: 4px; }}
.db.long {{ color: var(--up); background: var(--upbg); }}
.db.short {{ color: var(--down); background: var(--downbg); }}
.ob {{ font: 700 10px var(--mono); padding: 1px 6px; border-radius: 4px; }}
.ob.tp1 {{ color: var(--up); background: var(--upbg); }}
.ob.tp2 {{ color: var(--brand); background: color-mix(in srgb, var(--brand) 14%, transparent); }}
.ob.sl {{ color: var(--down); background: var(--downbg); }}
.ob.opn {{ color: var(--warn); background: var(--warnbg); }}
.star {{ color: var(--warn); font-size: 12px; }}
.tret {{ font: 700 26px var(--mono); margin: 6px 0 4px; }}
.tbody {{ font: 500 12.5px var(--mono); color: var(--text); opacity: .85; }}
.tdetail {{ font: 400 11.5px var(--mono); color: var(--muted); margin-top: 3px; }}
.foot {{ color: var(--muted); font-size: 11px; margin-top: 26px; text-align: center; }}
</style>
</head>
<body>
<div class="page">
  <h1>{version} · 逐笔交易卡片</h1>
  <div class="sub">{desc} · 滚动窗口 {WIN_DAYS} 天 / {STEP_DAYS} 天步进 · 颜色约定：涨红跌绿 · ★ = 限价回踩成交</div>
  <div class="kpis">{kpi_html}</div>
  <div class="sect">滚动窗口（{len(bounds)} 个）</div>
  <div class="windows">{''.join(wins_html)}</div>
  <div class="sect">逐笔交易（{kpi["n"]} 笔，按入场时间排序）</div>
  <div class="trades">{''.join(cards)}</div>
  <div class="foot">由 make_trade_cards.py 生成 · 数据：{trades_csv}</div>
</div>
</body>
</html>"""
    with open(out_html, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'已生成卡片 → {out_html}（{kpi["n"]} 笔，{len(bounds)} 窗口）')


if __name__ == '__main__':
    if len(sys.argv) < 4:
        print('用法: python make_trade_cards.py <trades.csv> <out.html> <版本名> [描述]')
        sys.exit(1)
    desc = sys.argv[4] if len(sys.argv) > 4 else ''
    build(sys.argv[1], sys.argv[2], sys.argv[3], desc)
