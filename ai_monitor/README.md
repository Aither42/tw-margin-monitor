# 🌡️ AI Overheat Monitor

一個可直接部署到 **GitHub + Streamlit Community Cloud** 的 AI 產業過熱偵測器。

它不是用「股價漲很多」判斷泡沫，而是監控 AI 產業的 **供需平衡是否開始反轉**：

- Hyperscaler AI / Cloud 需求與 Capex
- GPU / ASIC backlog、交期、ASP、guidance
- HBM / CoWoS 供需、價格、利用率
- 800G / 1.6T / InP / CPO 光通訊
- 電力、散熱與資料中心施工
- AI 基建融資、SPV、債務與 FCF 壓力
- 半導體 / AI 股市場狂熱
- 台灣 AI 供應鏈高頻「地震儀」

## 核心判讀

> 缺貨與需求強勁本身不是過熱。
>
> 真正危險的是：**產能 / Capex 仍高速增加，但訂單、價格、利用率、毛利或現金回收開始轉弱。**

### 風險分數

| 分數 | 狀態 | 解讀 |
|---:|---|---|
| 0–29 | 🟢 健康擴張 | 需求強、供給仍偏緊 |
| 30–44 | 🟢🟡 升溫 | Capex 大，但大多仍能被需求吸收 |
| 45–59 | 🟡 過熱初期 | 部分供應鏈開始鬆動 |
| 60–74 | 🟠 高風險 | 供給追上需求，獲利預期可能見頂 |
| 75–100 | 🔴 週期反轉 | 砍單 / 降價 / 庫存 / Capex 下修同時出現 |

## 七大雷達與權重

| 雷達 | 權重 |
|---|---:|
| AI 終端需求 | 20% |
| GPU / ASIC 供需 | 15% |
| HBM / CoWoS | 15% |
| 光通訊 / CPO | 15% |
| 電力 / 散熱 / 機房建設 | 10% |
| AI 融資 / 資本壓力 | 15% |
| 市場狂熱 | 10% |

## 六個硬性紅旗

如果同時出現 **3 個以上**，系統會把總風險至少升到橘燈；5 個以上至少紅燈。

1. 兩家以上 Hyperscaler 下修 AI Capex
2. NVIDIA / Broadcom / TSMC 等核心供應商同步下修需求
3. HBM / CoWoS 由缺貨轉為供需平衡或過剩
4. Lumentum + Coherent 同步轉弱
5. GPU lead time / 租賃價格快速下降
6. AI 基建融資壓力、違約或大型專案取消

## 資料來源

MVP 不需要 API Key：

- 新聞：Google News RSS
- 市場價格：Yahoo Finance（`yfinance`）
- 自動判讀：來源品質 × 時效 × 風險 / 缺貨關鍵詞

> 這是篩選器，不是事實裁判。重大訊號一定要回到原始財報、法說或高品質媒體確認。

## 專案結構

```text
ai_overheat_monitor/
├── streamlit_app.py
├── requirements.txt
├── README.md
├── LICENSE
├── .streamlit/
│   └── config.toml
├── src/
│   ├── config.py
│   ├── news.py
│   ├── market.py
│   ├── scoring.py
│   └── engine.py
├── scripts/
│   └── daily_snapshot.py
├── data/
│   └── .gitkeep
└── .github/workflows/
    └── daily_snapshot.yml
```

## 本機執行

建議 Python 3.12。

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## 放上 GitHub

```bash
git init
git add .
git commit -m "feat: AI Overheat Monitor MVP"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/ai-overheat-monitor.git
git push -u origin main
```

## 部署到 Streamlit Community Cloud

1. 把專案 push 到 GitHub。
2. 登入 Streamlit Community Cloud。
3. 選擇你的 GitHub repository。
4. Entry point 填：`streamlit_app.py`
5. Deploy。

`requirements.txt` 已放在 repo root，符合 Streamlit Community Cloud 的部署方式。

## 建立歷史分數

先手動跑：

```bash
python scripts/daily_snapshot.py
```

會建立：

```text
data/history.csv
```

App 之後會自動讀取並顯示歷史曲線。

### GitHub Actions 自動每日紀錄（可選）

`.github/workflows/daily_snapshot.yml` 已經做好，但預設只允許手動執行。

若要每天台北時間約 08:45 自動掃描，把：

```yaml
# schedule:
#   - cron: "45 0 * * *"
```

取消註解即可。

## 怎麼調整監控公司、權重與搜尋題目？

全部集中在：

```text
src/config.py
```

可以修改：

- `PILLARS`：七大雷達、權重、搜尋 query
- `RISK_TERMS`：過熱 / 反轉關鍵詞
- `COOLING_TERMS`：缺貨 / 強需求關鍵詞
- `SOURCE_WEIGHTS`：來源可信度
- `MARKET_TICKERS`：全球市場監控
- `TAIWAN_WATCHLIST`：台灣供應鏈地震儀

## 下一版建議

MVP 之後最值得加的三件事：

1. **台股每月營收 API / 公開資料**：把台灣地震儀從股價代理升級成基本面領先指標。
2. **法說逐字稿語意模型**：判斷管理層 wording 從 `capacity constrained` → `balanced` → `inventory correction` 的變化。
3. **供需時間序列**：HBM、CoWoS、GPU lead time、1.6T、InP 價格形成真正可回測的歷史資料庫。

## 免責聲明

本工具僅供研究、資訊整理與風險監控，不構成任何證券投資建議。自動新聞分類可能誤判，所有重大訊號均應回到原始來源驗證。
