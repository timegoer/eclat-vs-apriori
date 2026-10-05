#!/usr/bin/env python3
"""根据 results/summary.csv 生成 PPT 用的图：

  figures/fig_time_combined.png   两个数据集的时间-支持度曲线（PPT 主图）
  figures/fig_speedup.png         加速比-支持度曲线
  figures/fig_time_<dataset>.png  单数据集视图（备用）

图注使用英文，避免不同环境下中文字体缺失导致乱码。
"""
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def series(rows):
    """{dataset: {algorithm: [(min_sup%, time, status), ...]}}"""
    out = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("status") == "skipped_after_failure":
            continue
        t = _f(row.get("time_min_s"))
        if t is None:
            continue
        out[row["dataset"]][row["algorithm"]].append(
            (float(row["min_sup_rel"]) * 100, t, row.get("status", "ok")))
    return out


def draw(ax, algos, title):
    for algo, points in sorted(algos.items()):
        points.sort()
        ok = [(s, t) for s, t, st in points if st == "ok"]
        bad = [(s, t) for s, t, st in points if st != "ok"]
        if ok:
            ax.plot([p[0] for p in ok], [p[1] for p in ok],
                    marker="o", label=algo.capitalize())
        if bad:
            ax.plot([p[0] for p in bad], [p[1] for p in bad], linestyle="none",
                    marker="^", markersize=10, color="crimson",
                    label="%s (timeout)" % algo.capitalize())
            for s, t in bad:
                ax.annotate("≥%.0fs" % t, (s, t), textcoords="offset points",
                            xytext=(6, 6), fontsize=8, color="crimson")
    ax.set_xlabel("min_sup (% of transactions)")
    ax.set_ylabel("runtime (s, log scale)")
    ax.set_yscale("log")
    ax.invert_xaxis()
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    ax.set_title(title, fontsize=10)


def main(argv=None):
    ap = argparse.ArgumentParser(description="根据 summary.csv 出图")
    ap.add_argument("--csv", default=os.path.join("results", "summary.csv"))
    ap.add_argument("--out-dir", default="figures")
    args = ap.parse_args(argv)

    rows = load_rows(args.csv)
    data = series(rows)
    os.makedirs(args.out_dir, exist_ok=True)

    for ds, algos in sorted(data.items()):
        fig, ax = plt.subplots(figsize=(5.2, 3.6))
        draw(ax, algos, ds)
        fig.tight_layout()
        fig.savefig(os.path.join(args.out_dir, "fig_time_%s.png" % ds), dpi=200)
        plt.close(fig)

    names = sorted(data)
    fig, axes = plt.subplots(1, max(1, len(names)),
                             figsize=(4.8 * max(1, len(names)), 3.8), squeeze=False)
    for ax, ds in zip(axes[0], names):
        draw(ax, data[ds], ds)
    fig.tight_layout()
    fig.savefig(os.path.join(args.out_dir, "fig_time_combined.png"), dpi=200)
    plt.close(fig)

    sp = defaultdict(list)
    for row in rows:
        value = _f(row.get("speedup_vs_apriori"))
        if value:
            sp[row["dataset"]].append((float(row["min_sup_rel"]) * 100, value))
    if sp:
        fig, ax = plt.subplots(figsize=(5.6, 3.6))
        for ds, points in sorted(sp.items()):
            points.sort()
            ax.plot([p[0] for p in points], [p[1] for p in points],
                    marker="s", label=ds)
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=1)
        ax.set_xlabel("min_sup (% of transactions)")
        ax.set_ylabel("speedup (Apriori / Eclat)")
        ax.set_yscale("log")
        ax.invert_xaxis()
        ax.grid(alpha=0.3, which="both")
        ax.legend()
        fig.tight_layout()
        fig.savefig(os.path.join(args.out_dir, "fig_speedup.png"), dpi=200)
        plt.close(fig)

    print("图表已输出到 %s/" % args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
