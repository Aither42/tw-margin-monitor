from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_monitor.engine import run_monitor  # noqa: E402


def main() -> None:
    result = run_monitor(days=30, max_items_per_query=12, fetch_market=True)
    row = {
        "timestamp": result["timestamp"].isoformat(),
        "score": round(result["score"], 2),
        "band": result["band"],
        "active_hard_flags": sum(1 for f in result["hard_flags"] if f["active"]),
    }
    for key, score in result["pillar_scores"].items():
        row[f"pillar_{key}"] = round(score, 2)

    path = ROOT / "data" / "ai_overheat" / "history.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new = pd.DataFrame([row])
    if path.exists():
        old = pd.read_csv(path)
        out = pd.concat([old, new], ignore_index=True)
        out = out.drop_duplicates(subset=["timestamp"], keep="last")
    else:
        out = new
    out.to_csv(path, index=False)
    print(f"Saved snapshot: {row}")


if __name__ == "__main__":
    main()
