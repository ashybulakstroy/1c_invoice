"""Детали разбора по чекам из пачки: python tools/inspect_receipt.py <json> <подстрока имени>"""
import json
import sys
from pathlib import Path

FIELDS = ("qty", "unit", "price", "sum", "kind", "source", "flags", "conf")


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    pat = sys.argv[2]
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 99
    for r in rows:
        if pat not in Path(r["source"]).name:
            continue
        if r["status"] != "ok":
            print(f"ERR {r['source']}: {r.get('error')}")
            continue
        b = r["result"]
        print(f"=== {Path(r['source']).name} mode={b['mode']} tbl={b['table_rows']}x{b['table_cols']} "
              f"words={b['words_count']} flags_q={b['quality_flags']}")
        for row in b["items"][:limit]:
            extra = " ".join(f"{k}={row[k]}" for k in FIELDS if row.get(k) not in (None, "") and k != "kind")
            print(f"  r{row['idx']:>2} [{row['kind']:>4}] {str(row['name'])[:48]:<48} {extra}")
        tt = b.get("totals") or {}
        print(f"  ИТОГИ: sum={tt.get('items_sum')} ttl={tt.get('total')} via={tt.get('source')} "
              f"delta={tt.get('delta')} ok={tt.get('ok')} flags={tt.get('flags')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
