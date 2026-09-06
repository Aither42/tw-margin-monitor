"""Application configuration."""

DEFAULT_WEEKS = 30
HTTP_TIMEOUT = (5, 25)
MAX_WORKERS = 2
REQUEST_HEADERS = {
    "User-Agent": "tw-margin-monitor/3.3 (public market-data dashboard)",
    "Accept": "application/json,text/html,text/plain,*/*",
}

TWSE_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_INDEX_URL = "https://www.tpex.org.tw/www/zh-tw/indexInfo/inx"
TPEX_MARGIN_URL = (
    "https://www.tpex.org.tw/web/stock/margin_trading/"
    "margin_balance/margin_bal_result.php"
)
TPEX_MARGIN_JSON_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
