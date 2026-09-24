# d-variant-strategy

加密货币 **S-28 策略 · D 口径（冻结版 A4）**

用 OKX 永续 BTC/ETH 两年日线滚动回测筛选出的最优执行口径。核心思想：**去掉 4H 突破确认，在信号日收盘直接市价入场，止损止盈锚定区间中点（MID）**。

## 最终参数（A4，冻结版）

| 腿 | 入场 | 止损 | 止盈1 | 止盈2 |
|---|---|---|---|---|
| **long** | 信号日收盘市价（回踩 mid∓0.5ATR + 24h 兜底） | SL 4%（锚入场价） | TP1 1.25R | TP2 3.0R |
| **short 震荡窗**（ADX<20） | 同上 | SL 4% | TP1 1.5R | TP2 5.03R |
| **short 趋势窗**（ADX≥20） | 同上 | SL 4% | TP1 **2.25R（自适应放大）** | TP2 5.03R |

## 两年净额回测结论（2024-10 ~ 2026-09，36 笔，含费用+滑点）

| 指标 | 值 |
|---|---|
| 笔数 / 胜率 | 36 / **77.8%** |
| 累计净单利 | **+132.9%** |
| 盈亏比 PF | **4.57** |
| 最大回撤 | 9.1% |

- **自适应 TP 只对 short 趋势放大**：ADX≥20 时 short TP1 1.5→2.25R，short 净 +52.2→+73.2%，WR 与滚动负窗数保持不变（零质量代价纯增益）。
- **long 必须恒 1.25R**：long 的 MFE 天花板仅 ~8~11.5%，且超级小牛（如 2026-08 暴涨）在入场时不可预测（无先行指标），放大 TP 只会把已握 +4.9% 换成止损。A5 已全网格证伪。
- 二次确认机制：信号需在 4 天内二次触锚才入场，跳过首单提纯信号。

## 关键设计决策

1. **同步线上同一份扫描器源码** `scripts/csb_signal_scanner.py`（`importlib` 直接加载，杜绝实现漂移）。
2. **无未来函数**：`if day_close > NOW: continue` 硬保护 + 4H 覆盖保护；同根 K 线 SL/TP 同时触发一律 SL 优先。
3. **标称 R ≠ 实际止损距离**：`Rv=|MID-sl|` 与 `实际=|entry-sl|` 分开统计。
4. **成本建模**：扣手续费 0.10% 往返 + 止损滑点（14% 中位）。

## 复现

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # pandas / numpy
.venv/Scripts/python scripts/stageA4_final.py    # 冻结版 A4 全量回测 + 导出
.venv/Scripts/python scripts/stageA4_validate.py # 平台校验 + Walk-forward（OOS）
.venv/Scripts/python scripts/stageA2_wfo.py      # Walk-forward 外推验证
```

> 数据：OKX 永续 `BTC-USDT-SWAP` / `ETH-USDT-SWAP`，1DUTC 两年 + 4H 5100 根，见 `scripts/stage4_common.py`。拉取用 `curl`（python urllib 走代理会 502）。

## 目录

- `scripts/` — 策略源码 + A系列冻结回测/校验脚本
  - `csb_signal_scanner.py` 策略定义（S-28 信号生成源）
  - `stage4_common.py` 公共模块（数据/候选/交易模拟/簇标注）
  - `stageA4_final.py` 冻结版最终回测 + 审计 + 导出
  - `stageA4_validate.py` short 自适应参数平台校验 + WFO
  - `stageA5_*.py` long 趋势窗放大 TP 证伪性探查
- `results/` — 冻结版逐笔明细（CSV）+ 逐笔交易卡片（HTML）+ 校验输出

## 数据来源与坑

- OKX 日线必须用 `bar=1Dutc`（`1D` 是 UTC+8 切分）。
- 时间列一律 tz-aware UTC，禁 `.values`。
- 详见过往研究笔记（PROJECT_MEMORY 内部文档，未公开）。