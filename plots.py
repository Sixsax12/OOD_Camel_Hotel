"""วาดกราฟของการทดลอง A/B/C จากผลที่ experiments.py วัดมาแล้ว"""

from __future__ import annotations

import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # บันทึกไฟล์เท่านั้น ไม่เปิดหน้าต่าง
import matplotlib.pyplot as plt

from common import ( 
    A_N, A_V, B_K, B_METHODS, B_N_VALUES, B_V, C_K, C_N, C_V_VALUES,
    FIGURES_DIR, N_CHANNELS, PROJECT_DIR, SALT_LABEL, SEARCH_BATCH,
    summarize_rounds,
)


def _errorbars(entries: list):
    """แปลงค่าสรุปเป็น (median, yerr) สำหรับ plt.errorbar โดย yerr = ช่วงต่ำสุด-สูงสุด"""
    median = [e["median"] for e in entries]
    lower = [e["median"] - e["min"] for e in entries]
    upper = [e["max"] - e["median"] for e in entries]
    return median, [lower, upper]


def _axis(
    ax,
    xlabel: str,
    ylabel: str,
    title: str,
    *,
    grid_which: str = "major",
    grid_axis: str = "both",
    title_size: float | None = None,
    ylabel_color: str | None = None,
    legend_kw: dict | None = None,
) -> None:
    """ตั้งชื่อแกน ชื่อภาพ เส้นตาราง และคำอธิบายของหนึ่งแผง"""
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel, **({"color": ylabel_color} if ylabel_color else {}))
    ax.set_title(title, **({"fontsize": title_size} if title_size else {}))
    ax.grid(True, which=grid_which, axis=grid_axis, alpha=0.3)
    ax.legend(**{"fontsize": 8, **(legend_kw or {})})


def _save(fig, filename: str, attempts: int = 3) -> Path:
    """บันทึกกราฟเป็นไฟล์ PNG ลองใหม่ได้ถ้าไฟล์ถูกโปรแกรมอื่นเปิดค้างไว้"""
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / filename

    for attempt in range(1, attempts + 1):
        try:
            fig.savefig(path, dpi=150, bbox_inches="tight")
        except OSError as err:
            if attempt == attempts:
                plt.close(fig)
                raise RuntimeError(
                    f"บันทึก {path.name} ไม่สำเร็จหลังลอง {attempts} ครั้ง ({err}) "
                    f"สาเหตุที่พบบ่อยคือเปิดไฟล์รูปค้างไว้ในโปรแกรมดูรูป "
                    f"ให้ปิดหน้าต่างนั้นแล้วรันใหม่"
                ) from err
            time.sleep(0.5)
        else:
            plt.close(fig)
            print(f"  -> {path.relative_to(PROJECT_DIR)}")
            return path

    raise AssertionError("ไม่ควรมาถึงบรรทัดนี้")


def plot_experiment_A(summary: list[dict]) -> Path:
    """กราฟ (ก) เวลาเทียบ K พร้อมแผงค้นหาต่อครั้งและหน่วยความจำ"""
    ks = [e["K"] for e in summary]
    fig, (ax_time, ax_search, ax_mem) = plt.subplots(1, 3, figsize=(16, 4.8))

    for field, label in (
        ("t_assign_guests_s", "Assign K guests"),
        ("t_sort_rooms_s", "Sort room list"),
        ("t_build_ring_s", "Build ring (N x V points)"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_time.errorbar(ks, median, yerr=yerr, marker="o", capsize=4, label=label)
    ax_time.set_xscale("log")
    ax_time.set_yscale("log")
    _axis(ax_time, "Number of guests K (log scale)", "Time (seconds, total)",
          "Total time vs K", grid_which="both")

    for field, label in (
        ("t_search_guest_us", "find_by_guest: guest id -> room  O(log M)"),
        ("t_compute_node_us", "ring.get_node only  O(log M)"),
        ("t_search_room_us", "find_by_room: room -> guest id  O(1)"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_search.errorbar(ks, median, yerr=yerr, marker="s", capsize=4, label=label)
    ax_search.set_xscale("log")
    _axis(ax_search, "Number of guests K (log scale)",
          "Time per lookup (microseconds)",
          f"Search cost (batch of {SEARCH_BATCH:,} lookups)", grid_which="both")

    for field, label, marker in (
        ("mem_peak_mib", "peak", "o"),
        ("mem_current_mib", "current", "s"),
    ):
        median, yerr = _errorbars([e[field] for e in summary])
        ax_mem.errorbar(ks, median, yerr=yerr, marker=marker, capsize=4, label=label)
    ax_mem.set_xscale("log")
    ax_mem.set_yscale("log")
    _axis(ax_mem, "Number of guests K (log scale)",
          "Memory traced by tracemalloc (MiB, log scale)",
          "Memory vs K (not whole-process RSS)", grid_which="both")

    fig.suptitle(
        f"Experiment A - Consistent hashing, N={A_N}, V={A_V},"
        f" guests from {N_CHANNELS} channels"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_A_time_vs_K.png")


def plot_experiment_B(rows: list[dict]) -> Path:
    """กราฟ (ข) อัตราการย้ายเทียบ N ของทั้งสองวิธี พร้อมเส้นค่าคาดหวัง"""
    ns = list(B_N_VALUES)
    fig, (ax_rate, ax_time) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    styles = {
        ("consistent", "add"): ("tab:blue", "-", "o"),
        ("consistent", "remove"): ("tab:cyan", "-", "s"),
        ("modulo", "add"): ("tab:red", "--", "^"),
        ("modulo", "remove"): ("tab:orange", "--", "v"),
    }

    for (method, operation), (color, line, marker) in styles.items():
        subset = [
            r for r in rows if r["method"] == method and r["operation"] == operation
        ]
        rate_entries = [
            summarize_rounds([r["move_rate"] for r in subset if r["N"] == n]) for n in ns
        ]
        median, yerr = _errorbars(rate_entries)
        ax_rate.errorbar(
            ns, median, yerr=yerr, color=color, linestyle=line, marker=marker,
            capsize=4, label=f"{method} / {operation} 1 node",
        )

    ax_rate.plot(ns, [1 / (n + 1) for n in ns], ":", color="gray", label="expected K/(N+1)")
    ax_rate.plot(ns, [1 / n for n in ns], ":", color="black", label="expected K/N")
    ax_rate.set_xticks(ns)
    ax_rate.set_ylim(0, 1.05)
    _axis(ax_rate, "Number of buildings N before the change",
          "Guests moved / K  (fraction)", "Move rate vs N")

    # แผงขวา: แยกเวลาของการเพิ่มอาคารเป็น 3 ขั้น
    stages = (
        ("t_ring_adjust_s", "(a) adjust ring", "tab:green"),
        ("t_find_affected_s", "(b) find affected guests", "tab:blue"),
        ("t_update_data_s", "(c) update guest data + index", "tab:purple"),
    )
    labels = [f"N={n}\n{m}" for n in ns for m in B_METHODS]
    positions = range(len(labels))
    bottoms = [0.0] * len(labels)
    for field, label, color in stages:
        heights = [
            summarize_rounds(
                [
                    r[field]
                    for r in rows
                    if r["N"] == n and r["method"] == m and r["operation"] == "add"
                ]
            )["median"]
            for n in ns
            for m in B_METHODS
        ]
        ax_time.bar(positions, heights, bottom=bottoms, color=color, label=label, width=0.65)
        bottoms = [b + h for b, h in zip(bottoms, heights)]

    ax_time.set_xticks(list(positions))
    ax_time.set_xticklabels(labels, fontsize=7)
    ax_time.set_ylim(0, max(bottoms) * 1.45)  # เว้นที่ไว้วาง legend
    _axis(ax_time, "", "Time (seconds, median of 3 rounds)",
          "Cost of adding 1 building, split into 3 stages\n"
          "(stage (a) is under 0.1 ms, too thin to see)",
          grid_axis="y", title_size=10,
          legend_kw={"loc": "upper left", "framealpha": 0.95})

    fig.suptitle(
        f"Experiment B - Consistent hashing (V={B_V}) vs hash mod N, K={B_K:,} guests"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_B_move_rate_vs_N.png")


def plot_experiment_C(rows: list[dict]) -> Path:
    """กราฟ (ค) ผลของ V ต่อ CV และหน่วยความจำ"""
    vs = list(C_V_VALUES)
    fig, (ax_cv, ax_load) = plt.subplots(1, 2, figsize=(12.5, 4.8))

    cv_entries = [summarize_rounds([r["load_cv"] for r in rows if r["V"] == v]) for v in vs]
    median, yerr = _errorbars(cv_entries)
    ax_cv.errorbar(
        vs, median, yerr=yerr, color="tab:blue", marker="o", capsize=4,
        label="Load CV = SD / mean",
    )
    ax_cv.set_xscale("log", base=2)
    ax_cv.set_xticks(vs)
    ax_cv.set_xticklabels([str(v) for v in vs])
    ax_cv.set_xlabel("Virtual nodes per building V (log2 scale)")
    ax_cv.set_ylabel("Load CV (dimensionless, lower = balanced)", color="tab:blue")
    ax_cv.tick_params(axis="y", labelcolor="tab:blue")
    ax_cv.grid(True, which="both", alpha=0.3)

    # แกนขวา: หน่วยความจำเฉพาะวงแหวน
    ax_mem = ax_cv.twinx()
    mem_entries = [
        summarize_rounds([r["mem_ring_peak_mib"] * 1024 for r in rows if r["V"] == v])
        for v in vs
    ]
    median, yerr = _errorbars(mem_entries)
    ax_mem.errorbar(
        vs, median, yerr=yerr, color="tab:red", marker="s", capsize=4,
        label="Ring peak memory (KiB)",
    )
    ax_mem.set_ylabel("tracemalloc peak memory of ring only (KiB)", color="tab:red")
    ax_mem.tick_params(axis="y", labelcolor="tab:red")
    ax_mem.set_ylim(bottom=0)

    handles = ax_cv.get_legend_handles_labels()[0] + ax_mem.get_legend_handles_labels()[0]
    labels = ax_cv.get_legend_handles_labels()[1] + ax_mem.get_legend_handles_labels()[1]
    ax_cv.legend(handles, labels, fontsize=8, loc="center right")
    ax_cv.set_title("Trade-off: load balance vs memory")

    for field, label, marker in (
        ("load_max", "max guests in a building", "^"),
        ("load_mean", "mean guests per building", "o"),
        ("load_min", "min guests in a building", "v"),
    ):
        entries = [summarize_rounds([r[field] for r in rows if r["V"] == v]) for v in vs]
        median, yerr = _errorbars(entries)
        ax_load.errorbar(vs, median, yerr=yerr, marker=marker, capsize=4, label=label)
    ax_load.set_xscale("log", base=2)
    ax_load.set_xticks(vs)
    ax_load.set_xticklabels([str(v) for v in vs])
    _axis(ax_load, "Virtual nodes per building V (log2 scale)",
          "Guests per building (count)", "Spread of guests per building",
          grid_which="both")

    fig.suptitle(
        f"Experiment C - Effect of V, N={C_N}, K={C_K:,} guests"
        f" | median of 3 rounds (salt {SALT_LABEL}), error bars = min-max",
        fontsize=10,
    )
    fig.tight_layout()
    return _save(fig, "graph_C_effect_of_V.png")
