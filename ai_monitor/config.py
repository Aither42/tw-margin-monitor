from __future__ import annotations

PILLARS = {
    "demand": {
        "name": "AI 終端需求",
        "weight": 0.20,
        "description": "Hyperscaler AI/Cloud 收入、Capex、產能限制與投資報酬。",
        "queries": [
            "Microsoft AI capex Azure demand",
            "Alphabet Google Cloud AI capex demand",
            "Amazon AWS AI capex demand",
            "Meta AI capex demand monetization",
            "Oracle OCI AI backlog capex",
        ],
        "companies": ["Microsoft", "Alphabet", "Amazon", "Meta", "Oracle"],
    },
    "compute": {
        "name": "GPU / ASIC 供需",
        "weight": 0.15,
        "description": "GPU/XPU/ASIC backlog、交期、ASP、毛利率與客戶拉貨強度。",
        "queries": [
            "NVIDIA AI GPU demand backlog lead time guidance",
            "AMD Instinct AI accelerator demand guidance",
            "Broadcom AI accelerator ASIC demand guidance",
            "Marvell custom AI accelerator demand",
        ],
        "companies": ["NVIDIA", "AMD", "Broadcom", "Marvell"],
    },
    "memory_packaging": {
        "name": "HBM / CoWoS",
        "weight": 0.15,
        "description": "HBM、先進封裝供需缺口、價格、利用率與擴產速度。",
        "queries": [
            "HBM supply shortage oversupply price SK hynix Micron Samsung",
            "TSMC CoWoS capacity shortage utilization demand",
            "advanced packaging CoWoS supply demand AI",
        ],
        "companies": ["SK hynix", "Micron", "Samsung", "TSMC", "ASE"],
    },
    "optical": {
        "name": "光通訊 / CPO",
        "weight": 0.15,
        "description": "800G/1.6T、InP、EML/CW laser、CPO 訂單與產能利用。",
        "queries": [
            "Lumentum AI optical demand 1.6T CPO guidance",
            "Coherent datacenter communications demand 1.6T CPO guidance",
            "AAOI 800G 1.6T demand capacity",
            "InP substrate shortage price AI optical",
            "CPO scale-up optical demand Broadcom NVIDIA",
        ],
        "companies": ["Lumentum", "Coherent", "AAOI", "Broadcom", "NVIDIA"],
    },
    "power": {
        "name": "電力 / 散熱 / 機房建設",
        "weight": 0.10,
        "description": "電力設備、變壓器、液冷、資料中心施工與併網是否成為瓶頸或轉為閒置。",
        "queries": [
            "AI data center power shortage transformer delay",
            "Vertiv AI data center demand guidance",
            "Eaton data center electrical demand AI",
            "data center construction delays AI capacity power",
        ],
        "companies": ["Vertiv", "Eaton", "Schneider Electric", "ABB"],
    },
    "financing": {
        "name": "AI 融資 / 資本壓力",
        "weight": 0.15,
        "description": "債務、SPV、租賃、vendor financing、FCF 壓力、違約與專案取消。",
        "queries": [
            "AI infrastructure debt financing SPV cash flow pressure",
            "CoreWeave debt refinancing AI infrastructure",
            "AI data center financing default cancelled project",
            "big tech AI capex free cash flow pressure",
        ],
        "companies": ["CoreWeave", "Nebius", "Applied Digital", "IREN"],
    },
    "market": {
        "name": "市場狂熱",
        "weight": 0.10,
        "description": "AI / 半導體股價動能、集中度、接近高點程度與估值狂熱的替代指標。",
        "queries": [
            "AI stocks valuation bubble semiconductor market enthusiasm",
            "AI IPO valuation investor mania",
        ],
        "companies": ["NVIDIA", "Broadcom", "TSMC"],
    },
}

# 文章文字命中後，分數越高代表「過熱/反轉風險」越高。
RISK_TERMS = {
    18: [
        "cut capex", "cuts capex", "capex cut", "capital spending cut",
        "inventory correction", "oversupply", "excess inventory",
        "order cancellation", "orders cancelled", "cancelled orders",
        "lowers guidance", "cuts guidance", "guidance cut",
        "demand slowdown", "demand weakens", "weaker demand",
        "price cut", "pricing pressure", "utilization falls",
        "lead time shrinks", "lead times shrink", "underutilization",
        "default", "refinancing stress", "cancelled project", "canceled project",
    ],
    10: [
        "slows capex", "slower capex", "backlog declines", "backlog falls",
        "capacity exceeds demand", "supply catches up", "supply catches up with demand",
        "double ordering", "inventory builds", "inventory build",
        "free cash flow pressure", "cash flow pressure", "write-down", "impairment",
        "delay deployment", "deployment delay", "project delay",
    ],
    6: [
        "debt financing", "vendor financing", "special purpose vehicle", "spv",
        "lease financing", "high leverage", "debt load", "funding gap",
        "margin pressure", "gross margin declines", "price decline",
    ],
}

COOLING_TERMS = {
    12: [
        "demand exceeds supply", "sold out", "fully booked", "capacity constrained",
        "shortage", "allocation", "record backlog", "raises guidance", "raised guidance",
        "price increase", "prices increase", "stronger than expected demand",
    ],
    7: [
        "record demand", "orders exceed capacity", "capacity shortage",
        "tight supply", "strong demand", "accelerating demand", "backlog grows",
    ],
}

# 融資風險：即使需求很強，金融結構變脆弱仍應加分。
FINANCING_TERMS = {
    12: ["default", "distressed", "refinancing stress", "funding shortfall", "liquidity crunch"],
    8: ["spv", "special purpose vehicle", "vendor financing", "lease financing", "debt financing"],
    5: ["free cash flow pressure", "cash flow pressure", "higher borrowing costs", "debt load"],
}

SOURCE_WEIGHTS = {
    "reuters": 1.00,
    "bloomberg": 0.95,
    "financial times": 0.95,
    "the wall street journal": 0.95,
    "wsj": 0.95,
    "trendforce": 0.90,
    "nikkei asia": 0.88,
    "cnbc": 0.82,
    "nvidia": 0.98,
    "microsoft": 0.98,
    "alphabet": 0.98,
    "google": 0.95,
    "amazon": 0.98,
    "meta": 0.98,
    "oracle": 0.98,
    "tsmc": 0.98,
    "sk hynix": 0.98,
    "micron": 0.98,
    "lumentum": 0.98,
    "coherent": 0.98,
    "broadcom": 0.98,
    "amd": 0.98,
    "arista": 0.98,
    "vertiv": 0.98,
    "eaton": 0.98,
}
DEFAULT_SOURCE_WEIGHT = 0.58

MARKET_TICKERS = {
    "^SOX": "費城半導體",
    "^NDX": "Nasdaq 100",
    "NVDA": "NVIDIA",
    "AVGO": "Broadcom",
    "AMD": "AMD",
    "TSM": "TSMC ADR",
    "MU": "Micron",
    "LITE": "Lumentum",
    "COHR": "Coherent",
    "AAOI": "AAOI",
    "ANET": "Arista",
    "VRT": "Vertiv",
    "ETN": "Eaton",
    "CRWV": "CoreWeave",
}

TAIWAN_WATCHLIST = {
    "2330.TW": "台積電",
    "2368.TW": "金像電",
    "3711.TW": "日月光投控",
    "2308.TW": "台達電",
    "3081.TWO": "聯亞",
    "4971.TWO": "IET-KY",
    "2455.TW": "全新",
    "3450.TW": "聯鈞",
    "4979.TWO": "華星光",
    "6442.TW": "光聖",
    "3163.TWO": "波若威",
    "3363.TWO": "上詮",
}

RISK_BANDS = [
    (0, 29, "🟢 健康擴張"),
    (30, 44, "🟢🟡 升溫"),
    (45, 59, "🟡 過熱初期"),
    (60, 74, "🟠 高風險"),
    (75, 100, "🔴 週期反轉"),
]
