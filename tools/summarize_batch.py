"""Сводка по пачке: python tools/summarize_batch.py data/eval/phase1_batch.json"""
import json
import sys
from pathlib import Path


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    path = Path(sys.argv[1])
    rows = json.loads(path.read_text(encoding="utf-8"))
    ok_cnt = 0
    line_mode = 0
    for r in rows:
        if r["status"] != "ok":
            print(f"ERR {Path(r['source']).name}: {r.get('error')}")
            continue
        b = r["result"]
        tt = b.get("totals") or {}
        name = Path(r["source"]).name[:46]
        mode = b["mode"]
        if mode == "line":
            line_mode += 1
        items_full = sum(1 for i in b["items"] if i["sum"] is not None)
        ms = b["timings_ms"].get("total", 0)
        mark = "OK " if tt.get("ok") else "-- "
        print(f"{mark}{name:<46} {mode:<5} tbl={b['table_rows']}x{b['table_cols']:<2} "
              f"items={items_full:>2}/{len(b['items']):<2} "
              f"sum={str(tt.get('items_sum')):>9} ttl={str(tt.get('total')):>9} "
              f"{ms:>6.0f}ms")
        if tt.get("ok"):
            ok_cnt += 1
    print(f"\nсошлось: {ok_cnt}/{len(rows)} | line-mode: {line_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
