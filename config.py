"""Application configuration."""

DEFAULT_WEEKS = 30
HTTP_TIMEOUT = (5, 20)
MAX_WORKERS = 8
REQUEST_HEADERS = {
    "User-Agent": "tw-margin-monitor/2.0 (public market-data dashboard)",
    "Accept": "application/json,text/plain,*/*",
}

TWSE_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_INDEX_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx"
