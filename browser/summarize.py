#!/usr/bin/env python3
"""Summarize browser trial runs into one markdown table.

usage: python browser/summarize.py [runs_dir]     (default: browser/runs)
"""
import glob
import json
import os
import statistics as st
import sys

if sys.argv[1:2] in (["-h"], ["--help"]):
    print(__doc__.strip())
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
runs = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "runs")

print("| run | tasks ok | scored steps correct | steps | median step s | mean step s | p90 step s "
      "| mean prompt tok | mean prompt ms | mean gen tok | mean gen ms |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for d in sorted(glob.glob(os.path.join(runs, "*"))):
    f = os.path.join(d, "steps.jsonl")
    if not os.path.exists(f):
        continue
    rows = [r for r in (json.loads(l) for l in open(f, encoding="utf-8")) if "wall_s" in r]
    if not rows:
        continue
    sp = os.path.join(d, "summary.json")
    sm = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else []
    sc = [r for r in rows if r["correct"] is not None]
    w = sorted(r["wall_s"] for r in rows)
    p90 = w[int(0.9 * (len(w) - 1))]
    tasks = ",".join(s["task"] + ("+" if s["success"] else "-") for s in sm)
    print(f"| {os.path.basename(d)} | {sum(s['success'] for s in sm)}/{len(sm)} ({tasks}) "
          f"| {sum(r['correct'] for r in sc)}/{len(sc)} | {len(rows)} "
          f"| {st.median(w):.1f} | {st.mean(w):.1f} | {p90:.1f} "
          f"| {st.mean(r['prompt_n'] for r in rows):.0f} | {st.mean(r['prompt_ms'] for r in rows):.0f} "
          f"| {st.mean(r['gen_n'] for r in rows):.0f} | {st.mean(r['gen_ms'] for r in rows):.0f} |")
