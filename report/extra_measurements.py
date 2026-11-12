"""วัดค่าที่ตารางเปรียบเทียบในรายงาน (หัวข้อ 8) ต้องใช้ แต่ results/*.csv ไม่มี
คือเวลาค้นหา ความสมดุลของโหลด (CV) และหน่วยความจำของ hash mod N

วัดทั้งสองวิธีในรอบเดียวกันด้วยคลาสของโปรเจกต์ พารามิเตอร์และ salt ชุดเดียวกับ
การทดลอง A/C (N = 10, V = 32, K = 10,000, salt 0/1/2) ไม่เขียนทับไฟล์ใน results/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (  # noqa: E402
    N_CHANNELS, NEW_NODE_ID, SALTS, SALT_LABEL, SEARCH_BATCH,
    load_statistics, measure_memory, summarize_rounds,
)
from experiments import build_system, pick_probes  # noqa: E402
from guest_room import GuestManager  # noqa: E402
from hash_ring import HashRing, ModuloNodeSelector  # noqa: E402

N, V, K = 10, 32, 10_000
NODE_IDS = [f"NODE{i:02d}" for i in range(1, N + 1)]
REMOVE_NODE_ID = NODE_IDS[0]
METHODS = ("modulo", "consistent")
PER_CHANNEL = K // N_CHANNELS


def make_selector(method: str, salt: int):
    """สร้างตัวเลือกอาคารเปล่า ๆ โดยไม่นับ NODE_IDS เป็นหน่วยความจำที่วัด"""
    if method == "consistent":
        return HashRing(NODE_IDS, v_nodes=V, salt=salt)
    return ModuloNodeSelector(NODE_IDS, salt=salt)


def time_get_node(selector, probes: list[tuple[int, int]]) -> float:
    """เวลาเฉลี่ยต่อครั้งของ get_node วัดเป็นชุดแล้วหารจำนวนครั้ง (ไมโครวินาที)"""
    start = time.perf_counter()
    for c, s in probes:
        selector.get_node(c, s)
    return (time.perf_counter() - start) / len(probes) * 1e6


def measure_round(method: str, salt: int) -> dict:
    """วัดหนึ่งวิธีหนึ่ง salt คืนค่าทุกตัวที่ตารางหัวข้อ 8 ต้องใช้"""
    selector, guests, buildings = build_system(method, NODE_IDS, V, salt)
    ok, message = guests.populate_initial(N_CHANNELS, PER_CHANNEL)
    if not ok:
        raise RuntimeError(f"Initial guest placement failed: {message}")

    stats = load_statistics(list(guests.load_per_node().values()))
    t_get_node = time_get_node(selector, pick_probes(K))

    added = buildings.add_building(NEW_NODE_ID)
    if not added.ok:
        raise RuntimeError(f"Command unexpectedly rejected: {added.message}")

    # ลบต้องเริ่มจากสถานะเดิม จึงสร้างระบบใหม่
    _, guests2, buildings2 = build_system(method, NODE_IDS, V, salt)
    ok, message = guests2.populate_initial(N_CHANNELS, PER_CHANNEL)
    if not ok:
        raise RuntimeError(f"Initial guest placement failed: {message}")
    removed = buildings2.remove_building(REMOVE_NODE_ID)
    if not removed.ok:
        raise RuntimeError(f"Command unexpectedly rejected: {removed.message}")

    del selector, guests, buildings, guests2, buildings2

    def build_routing(method=method, salt=salt):
        return make_selector(method, salt)

    def build_total(method=method, salt=salt):
        sel = make_selector(method, salt)
        gm = GuestManager(sel)
        gm.populate_initial(N_CHANNELS, PER_CHANNEL)
        return sel, gm

    routing_current, routing_peak = measure_memory(build_routing)
    total_current, total_peak = measure_memory(build_total)

    return {
        "t_get_node_us": t_get_node,
        "load_cv": stats["cv"],
        "mem_routing_current_kib": routing_current * 1024,
        "mem_routing_peak_kib": routing_peak * 1024,
        "mem_total_current_mib": total_current,
        "mem_total_peak_mib": total_peak,
        "add_ring_adjust_us": added.t_ring_adjust * 1e6,
        "add_find_affected_ms": added.t_find_affected * 1e3,
        "add_update_data_ms": added.t_update_data * 1e3,
        "remove_ring_adjust_us": removed.t_ring_adjust * 1e6,
        "remove_find_affected_ms": removed.t_find_affected * 1e3,
        "remove_update_data_ms": removed.t_update_data * 1e3,
        "add_rate": added.moved_rate,
        "remove_rate": removed.moved_rate,
    }


METRICS = [
    ("t_get_node_us", "คำนวณอาคาร 1 ครั้ง (µs, ชุด {batch:,})", 2),
    ("load_cv", "ความสมดุลของโหลด CV (ไม่มีหน่วย)", 4),
    ("mem_routing_current_kib", "พื้นที่จัดเส้นทาง current (KiB)", 2),
    ("mem_routing_peak_kib", "พื้นที่จัดเส้นทาง peak (KiB)", 2),
    ("mem_total_current_mib", "พื้นที่ข้อมูลรวม current (MiB)", 3),
    ("mem_total_peak_mib", "พื้นที่ข้อมูลรวม peak (MiB)", 3),
    ("add_ring_adjust_us", "เพิ่มอาคาร: ปรับวงแหวน (µs)", 1),
    ("add_find_affected_ms", "เพิ่มอาคาร: หาผู้ย้าย (ms)", 2),
    ("add_update_data_ms", "เพิ่มอาคาร: ย้ายและปรับดัชนี (ms)", 2),
    ("remove_ring_adjust_us", "ลบอาคาร: ปรับวงแหวน (µs)", 1),
    ("remove_find_affected_ms", "ลบอาคาร: หาผู้ย้าย (ms)", 2),
    ("remove_update_data_ms", "ลบอาคาร: ย้ายและปรับดัชนี (ms)", 2),
    ("add_rate", "อัตราย้ายเมื่อเพิ่ม 1 อาคาร", 4),
    ("remove_rate", "อัตราย้ายเมื่อลบ NODE01", 4),
]


def main() -> None:
    print("การวัดเพิ่มสำหรับตารางเปรียบเทียบหัวข้อ 8")
    print(f"N = {N}, V = {V}, K = {K:,}, salt {SALT_LABEL}, ชุดค้นหา {SEARCH_BATCH:,} ครั้ง")

    rounds = {m: [measure_round(m, salt) for salt in SALTS] for m in METHODS}

    width = 44
    print(f"\n{'ค่าที่วัด':<{width}}{'hash mod N':>26}{'Consistent Hashing':>26}")
    print("-" * (width + 52))
    for field, label, digits in METRICS:
        cells = []
        for method in METHODS:
            entry = summarize_rounds([r[field] for r in rounds[method]])
            cells.append(
                f"{entry['median']:.{digits}f}"
                f" ({entry['min']:.{digits}f}-{entry['max']:.{digits}f})"
            )
        print(f"{label.format(batch=SEARCH_BATCH):<{width}}{cells[0]:>26}{cells[1]:>26}")

    print(f"\nรูปแบบค่า: มัธยฐานของ {len(SALTS)} รอบ (ต่ำสุด-สูงสุด)")


if __name__ == "__main__":
    main()
