def risk_level(score):
    if score <= 2:
        return "🟢 安全"

    elif score <= 4:
        return "🟡 注意"

    elif score <= 6:
        return "🟠 危險"

    elif score <= 8:
        return "🔴 高風險"

    else:
        return "⚫ 崩盤風險"