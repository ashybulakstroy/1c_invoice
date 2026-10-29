# -*- coding: utf-8 -*-
"""diff_batch: построчная разница двух batch-JSON (defaults: batch5 vs batch6).
Сверка по имени файла: mode / items / sum / ttl / ok / flags + geom-method (новое в batch6).
Результат: data/eval/batch_diff_<A>_vs_<B>.txt (UTF-8), читаем read-инструментом.
"""
import sys
from pathlib import Path

BATCH5 = Path("data/eval/phase1_batch5.json")


def _load(p: Path) -> dict[str, dict]:
    rows = __import__("json").loads(p.read_text(encoding="utf-8"))
    return {Path(r["source"]).name: r for r in rows if r.get("status") == "ok"}


def _row(name: str, r: dict | None) -> str:
    if r is None:
        return f"{name:<46} <нет в наборе>"
    b = r["result"]
    tt = b.get("totals") or {}
    g = []
    if b.get("geom_method"):
        g.append(f"geom={b['geom_method']}/{b.get('geom_confidence')}")
    if b.get("doc_found") is False and b.get("geom_method"):
        g.append("docmiss")
    if "needs_review" in b.get("flags", []):
        g.append("needs_review")
    line = (f"{name:<46} {b['mode']:<5} items={len(b['items']):>2} "
            f"sum={str(tt.get('items_sum')):>9} ttl={str(tt.get('total')):>8} "
            f"ok={str(tt.get('ok')):>5} " + " ".join(g)).rstrip()
    return line


def main() -> int:
    for st in (sys.stdout, sys.stderr):
        st.reconfigure(errors="replace")
    a, b = (Path(sys.argv[1]) if len(sys.argv) > 1 else BATCH5,
            Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/eval/phase1_batch6.json"))
    da, db = _load(a), _load(b)
    names = sorted(set(da) | set(db))
    out = [f"A={a}  B={b}"]
    for n in names:
        ra, rb = _row(n, da.get(n)), _row(n, db.get(n))
        mark = "SAME" if ra.split(" items=", 1)[1:] == rb.split(" items=", 1)[1:] else "DIFF"
        out.append(f"[{mark}] {ra}")
        if mark == "DIFF":
            out.append(f"        {rb}")
    Path(f"data/eval/batch_diff_{a.stem}_{b.stem}.txt").write_text(
        "\n".join(out), encoding="utf-8")
    print("done")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main())
