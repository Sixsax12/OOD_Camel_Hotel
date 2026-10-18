from __future__ import annotations

import csv
import gc
import statistics
import time
import tracemalloc
from pathlib import Path

from building_manager import BuildingManager
from common import (
    A_K_VALUES, A_N, A_V, B_K, B_METHODS, B_N_VALUES, B_OPERATIONS, B_V,
    C_K, C_N, C_V_VALUES, MIB, N_CHANNELS, NEW_NODE_ID, PROJECT_DIR,
    RESULTS_DIR, SALT_LABEL, SALTS, SEARCH_BATCH, summarize_rounds,
)
from guest_room import GuestManager
from hash_ring import HashRing, ModuloNodeSelector
from plots import plot_experiment_A, plot_experiment_B, plot_experiment_C


def build_node_ids(n: int) -> list[str]:
    """รหัสอาคารคงที่ ไม่เปลี่ยนตามจำนวนอาคาร"""
    if n < 1:
        raise ValueError("จำนวนอาคาร (N) ต้องมีอย่างน้อย 1")
    return [f"NODE{i:02d}" for i in range(1, n + 1)]


def pick_probes(k: int, count: int = SEARCH_BATCH) -> list[tuple[int, int]]:
    """เลือกรหัสแขก `count` รายการจากแขก k คน เพื่อวัดการค้นหาเป็นชุด"""
    keys = [
        (c, s)
        for c in range(1, N_CHANNELS + 1)
        for s in range(1, k // N_CHANNELS + 1)
    ]
    if not keys:
        return []
    step = max(1, len(keys) // count)
    probes = keys[::step][:count]
    while len(probes) < count:  # กรณี K < count ให้วนซ้ำจนครบชุด
        probes.extend(keys[: count - len(probes)])
    return probes


def build_system(method: str, node_ids: list[str], v_nodes: int, salt: int):
    """สร้างระบบหนึ่งชุด คืน (selector, GuestManager, BuildingManager)"""
    if method == "consistent":
        selector = HashRing(node_ids, v_nodes=v_nodes, salt=salt)
    else:
        selector = ModuloNodeSelector(node_ids, salt=salt)
    guests = GuestManager(selector)
    return selector, guests, BuildingManager(selector, guests, check_rules=True)


def load_statistics(counts: list[int]) -> dict:
    """max / min / mean / SD / CV ของโหลดต่ออาคาร (ไม่มีแขก -> CV เป็น None)"""
    if not counts:
        raise ValueError("ต้องมีอาคารอย่างน้อย 1 หลัง")

    if sum(counts) == 0:
        return {"max": 0, "min": 0, "mean": 0.0, "sd": 0.0, "cv": None}

    mean = statistics.fmean(counts)
    sd = statistics.pstdev(counts)
    return {
        "max": max(counts),
        "min": min(counts),
        "mean": mean,
        "sd": sd,
        "cv": sd / mean if mean > 0 else None,
    }


def measure_memory(build) -> tuple[float, float]:
    """วัดหน่วยความจำที่ `build()` ใช้ด้วย tracemalloc คืน (current_mib, peak_mib)"""
    gc.collect()
    tracemalloc.start()
    baseline, _ = tracemalloc.get_traced_memory()
    keep = build()  # ถือ reference ไว้จนวัดเสร็จ
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del keep
    gc.collect()
    return (current - baseline) / MIB, (peak - baseline) / MIB


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """เขียน CSV แบบ UTF-8"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> {path.relative_to(PROJECT_DIR)}  ({len(rows)} แถว)")


def group_summary(
    rows: list[dict], key_field: str, key_values, metric_fields: list[str]
) -> list[dict]:
    """ยุบผลหลายรอบของแต่ละค่าตัวแปร -> {metric: {median, min, max, rounds}}"""
    summary = []
    for value in key_values:
        group = [r for r in rows if r[key_field] == value]
        entry: dict = {key_field: value}
        for field in metric_fields:
            entry[field] = summarize_rounds([r[field] for r in group])
        summary.append(entry)
    return summary


def write_summary_csv(
    path: Path,
    summary: list[dict],
    key_field: str,
    metric_fields: list[str],
    constants: dict,
) -> None:
    """เขียนค่าสรุป median/min/max แบบ long format"""
    rows = []
    for entry in summary:
        for field in metric_fields:
            stats = entry.get(field)
            if stats is None:
                continue
            rows.append(
                {
                    **constants,
                    key_field: entry[key_field],
                    "metric": field,
                    "median": stats["median"],
                    "min": stats["min"],
                    "max": stats["max"],
                    "rounds": stats["rounds"],
                }
            )
    fields = list(constants) + [key_field, "metric", "median", "min", "max", "rounds"]
    write_csv(path, rows, fields)


A_FIELDS = [
    "experiment", "salt", "N", "V", "K",
    "t_build_ring_s", "t_assign_guests_s", "t_sort_rooms_s",
    "t_compute_node_us", "t_search_guest_us", "t_search_room_us",
    "mem_current_mib", "mem_peak_mib",
]
A_METRICS = [f for f in A_FIELDS if f.startswith(("t_", "mem_"))]


def run_experiment_A() -> list[dict]:
    """เวลาจัดแขก ค้นหา เรียงลำดับ และหน่วยความจำ เมื่อ K เปลี่ยน (N=10, V=32)"""
    print(f"\n=== การทดลอง A : เวลา/หน่วยความจำ เทียบ K (N={A_N}, V={A_V}) ===")
    node_ids = build_node_ids(A_N)
    rows: list[dict] = []

    for k in A_K_VALUES:
        assert k % N_CHANNELS == 0, "K ต้องหารจำนวนช่องทางลงตัว เพื่อใช้ populate_initial ได้"
        per_channel = k // N_CHANNELS
        probes = pick_probes(k)

        for salt in SALTS:
            # รอบจับเวลา
            gc.collect()

            t0 = time.perf_counter()
            ring = HashRing(node_ids, v_nodes=A_V, salt=salt)
            t_build_ring = time.perf_counter() - t0

            guests = GuestManager(ring)
            t0 = time.perf_counter()
            ok, message = guests.populate_initial(N_CHANNELS, per_channel)
            t_assign = time.perf_counter() - t0
            if not ok:
                raise RuntimeError(f"จัดแขกเริ่มต้นไม่สำเร็จ: {message}")

            probe_rooms = [guests.find_by_guest(c, s) for (c, s) in probes]

            t0 = time.perf_counter()
            sorted_rooms = guests.list_rooms()
            t_sort = time.perf_counter() - t0

            # ค้นหาเป็นชุดแล้วหารต่อครั้ง หน่วยไมโครวินาที
            t0 = time.perf_counter()
            for c, s in probes:
                ring.get_node(c, s)
            t_compute_node = (time.perf_counter() - t0) / len(probes) * 1e6

            t0 = time.perf_counter()
            for c, s in probes:
                guests.find_by_guest(c, s)
            t_search_guest = (time.perf_counter() - t0) / len(probes) * 1e6

            t0 = time.perf_counter()
            for node_id, room_no in probe_rooms:
                guests.find_by_room(node_id, room_no)
            t_search_room = (time.perf_counter() - t0) / len(probes) * 1e6

            assert len(sorted_rooms) == k, "จำนวนห้องที่เรียงได้ต้องเท่ากับจำนวนแขก"
            assert len(guests.room_index) == k, "ที่อยู่ห้องต้องไม่ซ้ำกันเลย"
            assert guests.verify_consistency(), "ข้อมูลแขกกับดัชนีต้องสอดคล้องกับวงแหวน"
            del probe_rooms, sorted_rooms, guests, ring

            # รอบวัดหน่วยความจำ แยกจากรอบจับเวลา
            def build(salt=salt, per_channel=per_channel):
                mem_ring = HashRing(node_ids, v_nodes=A_V, salt=salt)
                mem_guests = GuestManager(mem_ring)
                mem_guests.populate_initial(N_CHANNELS, per_channel)
                return mem_ring, mem_guests

            mem_current, mem_peak = measure_memory(build)

            rows.append(
                {
                    "experiment": "A",
                    "salt": salt,
                    "N": A_N,
                    "V": A_V,
                    "K": k,
                    "t_build_ring_s": round(t_build_ring, 9),
                    "t_assign_guests_s": round(t_assign, 9),
                    "t_sort_rooms_s": round(t_sort, 9),
                    "t_compute_node_us": round(t_compute_node, 6),
                    "t_search_guest_us": round(t_search_guest, 6),
                    "t_search_room_us": round(t_search_room, 6),
                    "mem_current_mib": round(mem_current, 6),
                    "mem_peak_mib": round(mem_peak, 6),
                }
            )

        group = [r for r in rows if r["K"] == k]
        print(
            f"  K={k:>7,} | จัดแขก {statistics.median(r['t_assign_guests_s'] for r in group):8.4f} s"
            f" | เรียง {statistics.median(r['t_sort_rooms_s'] for r in group):7.4f} s"
            f" | ค้นรหัสแขก {statistics.median(r['t_search_guest_us'] for r in group):6.3f} us"
            f" | ค้นห้อง {statistics.median(r['t_search_room_us'] for r in group):6.3f} us"
            f" | peak {statistics.median(r['mem_peak_mib'] for r in group):7.2f} MiB"
        )

    return rows


B_FIELDS = [
    "experiment", "salt", "N", "V", "K", "method", "operation", "target_node",
    "moved", "move_rate", "expected_moved", "expected_rate",
    "t_ring_adjust_s", "t_find_affected_s", "t_update_data_s",
    "rule_violations", "consistent",
]
B_MOVE_FIELDS = [
    "experiment", "salt", "N", "V", "K", "method", "operation", "target_node",
    "channel_id", "sequence_id", "old_node", "new_node", "room_no",
]
B_METHODS = ("consistent", "modulo")
B_OPERATIONS = ("add", "remove")


def run_experiment_B() -> tuple[list[dict], list[dict]]:
    """เพิ่ม/ลบ 1 อาคาร วัดจำนวนย้าย อัตราย้าย และเวลา เทียบกับ hash mod N

    คืน (rows, move_rows) โดย move_rows คือรายการย้ายรายคน
    """
    print(f"\n=== การทดลอง B : การย้ายเทียบ N (K={B_K:,}, V={B_V}) ===")
    rows: list[dict] = []
    move_rows: list[dict] = []

    for n in B_N_VALUES:
        node_ids = build_node_ids(n)
        removed_id = node_ids[0]

        for salt in SALTS:
            for method in B_METHODS:
                for operation in B_OPERATIONS:
                    # สร้างระบบใหม่ทุกครั้ง ให้ "เพิ่ม" และ "ลบ" ออกตัวจากจุดเดียวกัน
                    selector, guests, buildings = build_system(method, node_ids, B_V, salt)
                    ok, message = guests.populate_initial(N_CHANNELS, B_K // N_CHANNELS)
                    if not ok:
                        raise RuntimeError(f"จัดแขกเริ่มต้นไม่สำเร็จ: {message}")

                    target = NEW_NODE_ID if operation == "add" else removed_id
                    if operation == "add":
                        result = buildings.add_building(target)
                        expected_moved = B_K / (n + 1)
                    else:
                        result = buildings.remove_building(target)
                        expected_moved = B_K / n
                    if not result.ok:
                        raise RuntimeError(f"คำสั่งถูกปฏิเสธโดยไม่คาดคิด: {result.message}")

                    assert result.moved_count == len(result.moves), (
                        "จำนวนที่รายงานว่าย้ายต้องเท่ากับจำนวนรายการย้ายจริง"
                    )
                    assert len(guests) == B_K, "จำนวนแขกรวมต้องไม่หายไม่เพิ่ม"

                    rows.append(
                        {
                            "experiment": "B",
                            "salt": salt,
                            "N": n,
                            "V": B_V if method == "consistent" else 0,
                            "K": B_K,
                            "method": method,
                            "operation": operation,
                            "target_node": target,
                            "moved": result.moved_count,
                            "move_rate": round(result.moved_rate, 6),
                            "expected_moved": round(expected_moved, 3),
                            "expected_rate": round(expected_moved / B_K, 6),
                            "t_ring_adjust_s": round(result.t_ring_adjust, 9),
                            "t_find_affected_s": round(result.t_find_affected, 9),
                            "t_update_data_s": round(result.t_update_data, 9),
                            "rule_violations": len(result.rule_violations),
                            "consistent": result.consistent,
                        }
                    )

                    # เก็บรายการย้ายรายคนเฉพาะ consistent hashing รอบ salt แรก
                    if method == "consistent" and salt == SALTS[0]:
                        move_rows.extend(
                            {
                                "experiment": "B",
                                "salt": salt,
                                "N": n,
                                "V": B_V if method == "consistent" else 0,
                                "K": B_K,
                                "method": method,
                                "operation": operation,
                                "target_node": target,
                                "channel_id": m.c,
                                "sequence_id": m.s,
                                "old_node": m.old_node,
                                "new_node": m.new_node,
                                "room_no": m.room_no,
                            }
                            for m in result.moves
                        )

        for method in B_METHODS:
            for operation in B_OPERATIONS:
                group = [
                    r
                    for r in rows
                    if r["N"] == n
                    and r["method"] == method
                    and r["operation"] == operation
                ]
                rate = statistics.median(r["move_rate"] for r in group)
                expected = group[0]["expected_rate"]
                violations = max(r["rule_violations"] for r in group)
                print(
                    f"  N={n:>2} | {method:<10} | {operation:<6}"
                    f" | อัตราย้าย {rate:7.2%} (คาดหวัง {expected:6.2%})"
                    f" | กฎการย้าย {'ผ่าน' if violations == 0 else f'ผิด {violations} ราย'}"
                )

    return rows, move_rows


C_FIELDS = [
    "experiment", "salt", "N", "V", "K", "ring_points",
    "load_max", "load_min", "load_mean", "load_sd", "load_cv",
    "moved_on_add", "move_rate_on_add",
    "mem_ring_current_mib", "mem_ring_peak_mib",
    "mem_total_current_mib", "mem_total_peak_mib",
]
C_METRICS = [
    "load_max", "load_min", "load_mean", "load_sd", "load_cv",
    "moved_on_add", "move_rate_on_add",
    "mem_ring_current_mib", "mem_ring_peak_mib",
    "mem_total_current_mib", "mem_total_peak_mib",
]


def run_experiment_C() -> list[dict]:
    """จำนวนแขกต่ออาคาร ความสมดุล (CV) หน่วยความจำ และการย้าย เมื่อ V เปลี่ยน"""
    print(f"\n=== การทดลอง C : ผลของ V (N={C_N}, K={C_K:,}) ===")
    node_ids = build_node_ids(C_N)
    per_channel = C_K // N_CHANNELS
    rows: list[dict] = []

    for v in C_V_VALUES:
        for salt in SALTS:
            ring, guests, buildings = build_system("consistent", node_ids, v, salt)
            ok, message = guests.populate_initial(N_CHANNELS, per_channel)
            if not ok:
                raise RuntimeError(f"จัดแขกเริ่มต้นไม่สำเร็จ: {message}")

            # นับโหลด รวมอาคารที่มี 0 คนด้วย
            stats = load_statistics(list(guests.load_per_node().values()))

            result = buildings.add_building(NEW_NODE_ID)
            if not result.ok:
                raise RuntimeError(f"คำสั่งถูกปฏิเสธโดยไม่คาดคิด: {result.message}")
            assert result.consistent, "ข้อมูลแขกกับดัชนีต้องสอดคล้องกันหลังย้าย"
            moved = result.moved_count
            del ring, guests, buildings, result

            # รอบวัดหน่วยความจำ แยกเป็นวงแหวนอย่างเดียว และวงแหวน + ข้อมูลแขก
            def build_ring_only(v=v, salt=salt):
                return HashRing(node_ids, v_nodes=v, salt=salt)

            def build_ring_and_guests(v=v, salt=salt):
                mem_ring = HashRing(node_ids, v_nodes=v, salt=salt)
                mem_guests = GuestManager(mem_ring)
                mem_guests.populate_initial(N_CHANNELS, per_channel)
                return mem_ring, mem_guests

            mem_ring_current, mem_ring_peak = measure_memory(build_ring_only)
            mem_total_current, mem_total_peak = measure_memory(build_ring_and_guests)

            rows.append(
                {
                    "experiment": "C",
                    "salt": salt,
                    "N": C_N,
                    "V": v,
                    "K": C_K,
                    "ring_points": C_N * v,  # M = N x V
                    "load_max": stats["max"],
                    "load_min": stats["min"],
                    "load_mean": round(stats["mean"], 3),
                    "load_sd": round(stats["sd"], 3),
                    "load_cv": round(stats["cv"], 6) if stats["cv"] is not None else None,
                    "moved_on_add": moved,
                    "move_rate_on_add": round(moved / C_K, 6),
                    "mem_ring_current_mib": round(mem_ring_current, 6),
                    "mem_ring_peak_mib": round(mem_ring_peak, 6),
                    "mem_total_current_mib": round(mem_total_current, 6),
                    "mem_total_peak_mib": round(mem_total_peak, 6),
                }
            )

        group = [r for r in rows if r["V"] == v]
        print(
            f"  V={v:>2} | M={C_N * v:>4} จุด"
            f" | CV {statistics.median(r['load_cv'] for r in group):.4f}"
            f" | โหลด {statistics.median(r['load_min'] for r in group):>5.0f}"
            f"-{statistics.median(r['load_max'] for r in group):<5.0f}"
            f" | วงแหวน {statistics.median(r['mem_ring_peak_mib'] for r in group) * 1024:7.1f} KiB"
            f" | รวมข้อมูลแขก {statistics.median(r['mem_total_peak_mib'] for r in group):5.2f} MiB"
        )

    return rows


def _write_experiment_B_summary(rows: list[dict]) -> None:
    """เขียนค่าสรุปของ B แยกตาม (N, method, operation)"""
    summary_rows = []
    for n in B_N_VALUES:
        for method in B_METHODS:
            for operation in B_OPERATIONS:
                subset = [
                    r
                    for r in rows
                    if r["N"] == n
                    and r["method"] == method
                    and r["operation"] == operation
                ]
                for field in (
                    "moved", "move_rate",
                    "t_ring_adjust_s", "t_find_affected_s", "t_update_data_s",
                ):
                    stats = summarize_rounds([r[field] for r in subset])
                    summary_rows.append(
                        {
                            "experiment": "B",
                            "K": B_K,
                            "V": B_V,
                            "salts": SALT_LABEL,
                            "N": n,
                            "method": method,
                            "operation": operation,
                            "metric": field,
                            "median": stats["median"],
                            "min": stats["min"],
                            "max": stats["max"],
                            "rounds": stats["rounds"],
                            "expected_rate": subset[0]["expected_rate"],
                            "move_rule_ok": all(r["rule_violations"] == 0 for r in subset),
                        }
                    )
    write_csv(
        RESULTS_DIR / "experiment_B_summary.csv",
        summary_rows,
        [
            "experiment", "K", "V", "salts", "N", "method", "operation", "metric",
            "median", "min", "max", "rounds", "expected_rate", "move_rule_ok",
        ],
    )


GUEST_FIELDS = ["channel_id", "sequence_id", "node_id", "room_no"]


def write_sample_guests() -> None:
    """ส่งออกข้อมูลแขกเป็น CSV (channel_id, sequence_id, node_id, room_no)"""
    node_ids = build_node_ids(A_N)
    _, guests, _ = build_system("consistent", node_ids, A_V, SALTS[0])
    ok, message = guests.populate_initial(N_CHANNELS, B_K // N_CHANNELS)
    if not ok:
        raise RuntimeError(f"จัดแขกเริ่มต้นไม่สำเร็จ: {message}")

    rows = [
        {"channel_id": c, "sequence_id": s, "node_id": node_id, "room_no": room_no}
        for node_id, room_no, c, s in guests.list_rooms()
    ]
    assert len(rows) == len(guests), "จำนวนแถวใน CSV ต้องเท่ากับจำนวนแขกในระบบ"
    write_csv(RESULTS_DIR / "sample_guests.csv", rows, GUEST_FIELDS)


def main() -> None:
    started = time.perf_counter()
    print("Distributed Hilbert's Hotel - Part 4: การทดลองและกราฟ")
    print(f"salt ที่ใช้: {SALT_LABEL}  |  แขกสร้างจาก {N_CHANNELS} ช่องทาง")

    rows_a = run_experiment_A()
    rows_b, move_rows_b = run_experiment_B()
    rows_c = run_experiment_C()

    print("\n=== เขียนไฟล์ CSV ===")
    write_csv(RESULTS_DIR / "experiment_A_rounds.csv", rows_a, A_FIELDS)
    write_csv(RESULTS_DIR / "experiment_B_rounds.csv", rows_b, B_FIELDS)
    write_csv(RESULTS_DIR / "experiment_C_rounds.csv", rows_c, C_FIELDS)
    write_csv(RESULTS_DIR / "experiment_B_moves.csv", move_rows_b, B_MOVE_FIELDS)
    write_sample_guests()

    summary_a = group_summary(rows_a, "K", A_K_VALUES, A_METRICS)
    summary_c = group_summary(rows_c, "V", C_V_VALUES, C_METRICS)

    write_summary_csv(
        RESULTS_DIR / "experiment_A_summary.csv", summary_a, "K", A_METRICS,
        {"experiment": "A", "N": A_N, "V": A_V, "salts": SALT_LABEL},
    )
    _write_experiment_B_summary(rows_b)
    write_summary_csv(
        RESULTS_DIR / "experiment_C_summary.csv", summary_c, "V", C_METRICS,
        {"experiment": "C", "N": C_N, "K": C_K, "salts": SALT_LABEL},
    )

    # วาดทีละภาพ ภาพที่พังต้องไม่ทำให้ภาพอื่นหายไปด้วย
    print("\n=== วาดกราฟ ===")
    failures: list[str] = []
    for plot, data in (
        (plot_experiment_A, summary_a),
        (plot_experiment_B, rows_b),
        (plot_experiment_C, rows_c),
    ):
        try:
            plot(data)
        except RuntimeError as err:
            failures.append(str(err))
            print(f"  !! {err}")

    print(f"\nเสร็จสิ้น ใช้เวลารวม {time.perf_counter() - started:.1f} วินาที")
    if failures:
        print(f"มีกราฟบันทึกไม่สำเร็จ {len(failures)} ภาพ -- CSV ทั้งหมดเขียนครบแล้ว")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
