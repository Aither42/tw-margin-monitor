import datetime

def get_market_data():
    return {
        "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "maintenance": 182.8,
        "margin_balance": 6156,
        "margin_change": -18,
        "temperature": 2
    }