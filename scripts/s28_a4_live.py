# -*- coding: utf-8 -*-
"""
A4 冻结策略实时信号推送器（S-28 策略源 + 飞书 webhook）
================================================================
- 复用 csb_signal_scanner（冻结的策略定义）做实时信号检测（MEXC 公共行情，无需 Key）
- 命中信号 → 推飞书交易卡（SDK内部计算 A4 档：long恒1.25R / short ADX≥20→2.25R）
- 去重：state.json 记录 (symbol|date|dir)，避免同一信号重复轰炸
- 用法：
    python s28_a4_live.py                # 正常扫描并推送
    python s28_a4_live.py --dry-run      # 只打印卡片，不发飞书
    python s28_a4_live.py --force-test   # 忽略去重，推送当前信号（用于测试通道）
"""
import os, sys, json, time
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import csb_signal_scanner as S   # 冻结的策略定义源
import feishu

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'live_state.json')

# A4 冻结执行参数（用于卡片展示）
A4_CFG = dict(
    long_sl=0.04, long_tp1=1.25, long_tp2=3.0,
    short_sl=0.04, short_tp1=1.5, short_tp2=5.03,
    short_tre_tp1=2.25, adx_tre=20.0,
)


def adx14(df):
    c, h, l, pc = df['close'], df['high'], df['low'], df['close'].shift(1)
    up = h.diff(); dn = -l.diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    tr = pd.Series(np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))).ewm(alpha=1/14, adjust=False).mean()
    pdi = 100 * plus / tr; mdi = 100 * minus / tr
    return (100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)).ewm(alpha=1/14, adjust=False).mean().values


def money(x):
    return '—' if x is None or (isinstance(x, float) and np.isnan(x)) else f'{x:,.0f}'


def build_card(inst, rec, adx):
    d = rec['d']; lv = rec['level']
    long = d == 'long'
    col = '#16b364' if long else '#f04438'
    dlab = 'LONG 做多' if long else 'SHORT 做空'
    if long:
        sl, tp1, tp2 = A4_CFG['long_sl'], A4_CFG['long_tp1'], A4_CFG['long_tp2']
        state = '恒 1.25R'
    else:
        st = '趋势窗' if adx >= A4_CFG['adx_tre'] else '震荡窗'
        tp1 = A4_CFG['short_tre_tp1'] if st == '趋势窗' else A4_CFG['short_tp1']
        sl, tp2 = A4_CFG['short_sl'], A4_CFG['short_tp2']
        state = f'{st} TP1 {tp1}R'
    # A4 SL锚 MID（与回测一致）
    sl_px = lv['mid'] * (1 - sl) if long else lv['mid'] * (1 + sl)
    Rv = abs(lv['mid'] - sl_px)
    tp1_px = lv['mid'] + tp1 * Rv if long else lv['mid'] - tp1 * Rv
    tp2_px = lv['mid'] + tp2 * Rv if long else lv['mid'] - tp2 * Rv
    symbol = inst.replace('-USDT', '')
    pvname = rec.get('pivot') or '—'
    b_days = '—' if rec.get('b') is None else (rec['sig_i'] - rec['b'])
    elements = [
        feishu.md(f"**{symbol} · {dlab} · {rec['date']}**"),
        feishu.md(f"📌 Pivot锚点 **{pvname}** = {money(lv['mid'])} ｜ 触锚 {rec['gap']}天前 ｜ 突破第{b_days}天"),
        feishu.md(f"🏛 入场区间 **{money(lv['zlo'])} ~ {money(lv['zhi'])}**（中 {money(lv['mid'])}）"),
        feishu.md(f"🛑 止损 **{money(sl_px)}**（{sl*100:.1f}%） ｜ ✅ TP1 **{money(tp1_px)}** ({tp1}R) ｜ 🚀 TP2 **{money(tp2_px)}** ({tp2}R)"),
        feishu.md(f"📊 市场状态: **{state}** ｜ ADX {adx:.1f}"),
        feishu.md(f"⚠️ 出手确认: 待人工/调度确认（二次确认机制）"),
    ]
    return feishu.send_card(f"S-系统信号 · {symbol} 做{'多' if long else '空'}", 'green' if long else 'red',
                            elements, note=f"A4 冻结策略 · {rec['date']} UTC")


def main():
    dry = '--dry-run' in sys.argv
    force = '--force-test' in sys.argv
    now = pd.Timestamp.now(tz='UTC')
    print(f'[scan] {now} (UTC)')
    dl, fl = S.load_data()
    results = S.scan_latest(dl, fl, now)

    try:
        seen = set(json.load(open(STATE_FILE, encoding='utf-8')))
    except Exception:
        seen = set()

    any_signal = False
    for inst, rec in results.items():
        if rec['status'] != 'signal':
            continue
        key = f"{inst}|{rec['date']}|{rec['d']}"
        if key in seen and not force:
            print(f'[skip] 已推送过 {key}')
            continue
        # ADX（A4 状态分类）
        do = dl[inst].reset_index(drop=True)
        adx = float(adx14(do)[rec['sig_i']])
        print(f'[SIGNAL] {key} ADX={adx:.1f}')
        if dry:
            print('[dry-run] 跳发送飞书'); any_signal = True; seen.add(key); continue
        try:
            resp = build_card(inst, rec, adx)
            print('  飞书响应:', resp)
            seen.add(key)
            any_signal = True
        except Exception as e:
            print('  推送失败:', e)

    if not dry and any_signal:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted(seen), f, ensure_ascii=False, indent=2)

    # 汇总状态（无信号时轻量提示）
    n_sig = sum(1 for r in results.values() if r['status'] == 'signal')
    n_pend = sum(1 for r in results.values() if r['status'] == 'pending')
    print(f'\n[summary] 信号={n_sig} 待确认={n_pend}')
    if not dry and n_sig == 0:
        lines = [f"⏳ **S-系统 v0.3 扫描** {now.strftime('%Y-%m-%d %H:%M')} UTC"]
        for inst, r in results.items():
            sym = inst.replace('-USDT', '')
            if r['status'] == 'signal':
                lines.append(f"🔴 **{sym}**: 信号触发！见交易卡")
            elif r['status'] == 'pending':
                lines.append(f"🟡 **{sym}**: 命中日线候选，等待4H方向确认")
            else:
                lines.append(f"⚪ **{sym}**: {r.get('reason','')}")
        try:
            feishu.send_card('等待信号中 · d-variant-strategy', 'grey', [feishu.md(l) for l in lines])
            print('  状态卡已推送')
        except Exception as e:
            print('  状态卡失败:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())