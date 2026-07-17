# 台股融資風險儀表板 V2

使用臺灣證券交易所（TWSE）與證券櫃檯買賣中心（TPEx）公開資料，監測近 30 週融資與市場壓力。

## 零付費原則（硬性限制）

本專案必須以零費用方式開發及運作：

- 只使用免費、無須信用卡的工具與公開資料來源
- 不使用付費 API、付費資料庫、付費雲端主機或可能自動計費的服務
- 部署以 GitHub Free 與 Streamlit Community Cloud 免費方案為限
- 若未來功能可能產生費用，必須先停止實作並取得專案擁有者明確同意
- 免費方案或資料授權條款若有變動，應先重新確認，不得自行升級或啟用付費方案

## V2 功能

- TWSE 加權指數每日歷史資料
- TPEx 櫃買指數每日歷史資料
- TWSE 上市融資餘額（每週最後交易日取樣）
- 0–100 融資風險分數與四項組成
- 8–52 週可調整觀察區間
- 官方 API 失敗時的部分資料降級與提示
- Streamlit 6 小時資料快取

風險分數是監測指標，不是整體市場的真實融資維持率，也不是投資建議。

## 本機執行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## 資料來源

- [臺灣證券交易所](https://www.twse.com.tw/)
- [證券櫃檯買賣中心](https://www.tpex.org.tw/)

## 專案結構

- `app.py`：Streamlit 頁面與 Plotly 圖表
- `data_fetcher.py`：官方 API 擷取、解析與週資料取樣
- `indicators.py`：風險分數與等級
- `config.py`：端點與應用設定
