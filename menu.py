"""ข้อสำคัญ: เมธอดส่วนใหญ่คืน (bool, str) ไม่ throw exception
เมนูจึงแค่พิมพ์ข้อความที่ได้กลับมา และมี try/except กันโปรแกรมหยุดอีกชั้น
"""

import copy
import csv
import time
from pathlib import Path

from building_manager import BuildingManager
from common import PROJECT_DIR, RESULTS_DIR, SEARCH_BATCH, load_statistics, measure_memory
from guest_room import GuestManager
from hash_ring import HashRing, ModuloNodeSelector

MAX_PRINT = 20  # จำนวนรายการย้าย/ห้องที่พิมพ์สูงสุดต่อครั้ง


def ask_int(prompt):
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("Please fill in an integer")
        except (KeyboardInterrupt, EOFError):
            print("\n Exit.")
            raise SystemExit


def ask_str(prompt):
    try:
        return input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\n Exit.")
        raise SystemExit


def show_result(res):
    """รองรับทั้ง (bool, str) และค่าที่ไม่ใช่ tuple"""
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool):
        ok, msg = res
        print(f"  {'Success ' if ok else 'Failed'}: {msg}")
    elif res is not None:
        print(f"  {res}")


def show_change(r):
    """แสดง BuildingChangeResult ตามหัวข้อ 4.4 ข้อ 3-4"""
    if not r.ok:
        print(f" Failed: {r.message}")
        return
    print(f"  Success: {r.message}")
    print(f"  Total Guests K = {r.total_guests}")
    print(f"  Moved Count = {r.moved_count}")
    if r.moved_rate is None:
        print(f"  Moved Rate: None ({r.rate_note})")
    else:
        print(f"  Moved Rate = {r.moved_rate:.2%}")
        if r.expected_moved is not None:
            expected_label = "Expected K/(N+1)" if r.action == "add" else "Expected K/N"
            print(f"  Expected Moved = {r.expected_moved:.2f} ({expected_label})")

    print(
        f"  Timing -> Ring adjust: {r.t_ring_adjust:.6f}s | "
        f"Find affected: {r.t_find_affected:.6f}s | Update data: {r.t_update_data:.6f}s"
    )
    print(f"  Consistent Status: {'Consistent' if r.consistent else 'Inconsistent'}")

    for m in r.moves[:MAX_PRINT]:
        print(f"    ({m.c},{m.s}) Room {m.room_no}: {m.old_node} -> {m.new_node}")
    if len(r.moves) > MAX_PRINT:
        print(f"    ... and more {len(r.moves) - MAX_PRINT} items")
    if r.rule_violations:
        print(f"  Warning! Violated the rules: {r.rule_violations}")


# ---------- คำสั่งเมนู ----------
def do_init(state):
    n = ask_int("Number of defult building N: ")
    v = ask_int("Virtual node (per building) V: ")
    salt = ask_int("salt (0,1,2,...): ")
    channels = ask_int("Number of channel: ")
    per = ask_int("Defult Guest (per channel): ")
    if n < 1 or v < 1:
        print("  N and V must more than 0")
        return
    if channels < 1 or per < 0:
        print("  Number of channels must be >= 1 and guests per channel must be >= 0")
        return
    ring = HashRing([f"NODE{i:02d}" for i in range(1, n + 1)], v_nodes=v, salt=salt)
    guests = GuestManager(ring)
    show_result(guests.populate_initial(channels, per))
    state["ring"], state["guests"] = ring, guests
    state["buildings"] = BuildingManager(ring, guests)
    state["last_change_result"] = None


def do_add_guest(st):
    show_result(st["guests"].add_guest(ask_int("c: "), ask_int("s: ")))


def do_add_range(st):
    c = ask_int("c: ")
    s0 = ask_int("Defult s : ")
    cnt = ask_int("Number of guest : ")
    show_result(st["guests"].add_guests_range(c, s0, cnt))


def do_remove_guest(st):
    show_result(st["guests"].remove_guest(ask_int("c: "), ask_int("s: ")))


def do_add_building(st):
    res = st["buildings"].add_building(ask_str("New building ID: "))
    if res.ok:
        st["last_change_result"] = res
    show_change(res)


def do_remove_building(st):
    res = st["buildings"].remove_building(ask_str("Remove building ID: "))
    if res.ok:
        st["last_change_result"] = res
    show_change(res)


def do_find_guest(st):
    res = st["guests"].find_by_guest(ask_int("c: "), ask_int("s: "))
    if res is None:
        print(" Not found guest ID")
    else:
        node, room = res
        print(f" Found at building {node} room {room}")


def do_find_room(st):
    res = st["guests"].find_by_room(ask_str("Building ID: "), ask_int("room_no: "))
    if res is None:
        print(" Not found any guest in this room")
    else:
        print(f" Guest ID {res}")


def do_list_rooms(st):
    rows = st["guests"].list_rooms()
    if not rows:
        print(" Don't have any guest (Total occupied rooms: 0)")
        return
    print(f"  Total occupied rooms: {len(rows)}")
    print("  node_id | room_no | channel_id | sequence_id")
    for row in rows[: MAX_PRINT * 5]:
        print("  " + " | ".join(str(x) for x in row))
    if len(rows) > MAX_PRINT * 5:
        print(f"  ... show {MAX_PRINT * 5} from {len(rows)} rooms ")


def do_load(st):
    loads = st["guests"].load_per_node()
    print(" Load per building:")
    for node in sorted(loads):
        print(f"    {node}: {loads[node]}")
    stats = load_statistics(list(loads.values()))
    if isinstance(stats, dict):
        for k, v in stats.items():
            print(f"  {k} = {v:.4f}" if isinstance(v, float) else f"  {k} = {v}")
    else:
        print(f"  {stats}")


def do_export_csv(st):
    """Export CSV from menu (guests+rooms and latest moves)"""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    guest_path = RESULTS_DIR / "menu_export_guests.csv"
    rows = [
        {"channel_id": c, "sequence_id": s, "node_id": node_id, "room_no": room_no}
        for node_id, room_no, c, s in st["guests"].list_rooms()
    ]
    with guest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["channel_id", "sequence_id", "node_id", "room_no"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> Exported guests successfully: {guest_path.relative_to(PROJECT_DIR)} ({len(rows)} rows)")

    last_res = st.get("last_change_result")
    if last_res and last_res.moves:
        move_path = RESULTS_DIR / "menu_export_last_moves.csv"
        move_rows = [
            {
                "action": last_res.action,
                "building_id": last_res.building_id,
                "channel_id": m.c,
                "sequence_id": m.s,
                "old_node": m.old_node,
                "new_node": m.new_node,
                "room_no": m.room_no,
            }
            for m in last_res.moves
        ]
        with move_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "action",
                    "building_id",
                    "channel_id",
                    "sequence_id",
                    "old_node",
                    "new_node",
                    "room_no",
                ],
            )
            writer.writeheader()
            writer.writerows(move_rows)
        print(f"  -> Exported last moves successfully: {move_path.relative_to(PROJECT_DIR)} ({len(move_rows)} rows)")
    else:
        print("  (No recent move records or no building change performed yet)")


def _format_move_summary(res) -> str:
    if res.moved_rate is None:
        return f"{res.moved_count} (N/A, {res.rate_note})"
    return f"{res.moved_count} ({res.moved_rate:.2%})"


def do_compare_hashing(st):
    """Compare Consistent Hashing with hash mod N on the same guest set and building changes"""
    node_ids = sorted(list(st["ring"].nodes))
    if not node_ids:
        print("  Need at least 1 building to compare.")
        return

    target_node = "COMPARE_NEW_NODE"
    idx = 1
    while target_node in st["ring"].nodes:
        target_node = f"COMPARE_NEW_NODE_{idx}"
        idx += 1

    guest_keys = sorted(st["guests"].guests.keys())

    # 1) เปรียบเทียบการเพิ่มอาคารใหม่ 1 หลัง
    ring_add, guests_add = copy.deepcopy((st["ring"], st["guests"]))
    bm_consistent_add = BuildingManager(ring_add, guests_add, check_rules=True)
    res_c_add = bm_consistent_add.add_building(target_node)

    mod_add = ModuloNodeSelector(node_ids, salt=st["ring"].salt)
    guests_mod_add = GuestManager(mod_add)
    guests_mod_add.add_guests(guest_keys)
    bm_modulo_add = BuildingManager(mod_add, guests_mod_add, check_rules=False)
    res_m_add = bm_modulo_add.add_building(target_node)

    print("\n--- Comparison Results: Consistent Hashing vs Hash Mod N ---")
    print(
        f"  Parameters: N={len(node_ids)}, V={st['ring'].v_nodes}, "
        f"K={len(guest_keys)}, salt={st['ring'].salt}"
    )
    print(f"  [1] Adding Building '{target_node}':")
    exp_add_str = f"{res_c_add.expected_moved:.2f}" if res_c_add.expected_moved is not None else "N/A"
    print(
        f"    Consistent Hashing moved: {_format_move_summary(res_c_add)} "
        f"| Expected K/(N+1): {exp_add_str} | Rule violations: {len(res_c_add.rule_violations)}"
    )
    print(f"    Hash Mod N moved:         {_format_move_summary(res_m_add)}")

    # 2) เปรียบเทียบการลบอาคาร 1 หลัง (เมื่อมีอย่างน้อย 2 อาคาร)
    if len(node_ids) >= 2:
        rem_node = node_ids[0]
        ring_rem, guests_rem = copy.deepcopy((st["ring"], st["guests"]))
        bm_consistent_rem = BuildingManager(ring_rem, guests_rem, check_rules=True)
        res_c_rem = bm_consistent_rem.remove_building(rem_node)

        mod_rem = ModuloNodeSelector(node_ids, salt=st["ring"].salt)
        guests_mod_rem = GuestManager(mod_rem)
        guests_mod_rem.add_guests(guest_keys)
        bm_modulo_rem = BuildingManager(mod_rem, guests_mod_rem, check_rules=False)
        res_m_rem = bm_modulo_rem.remove_building(rem_node)

        exp_rem_str = f"{res_c_rem.expected_moved:.2f}" if res_c_rem.expected_moved is not None else "N/A"
        print(f"  [2] Removing Building '{rem_node}':")
        print(
            f"    Consistent Hashing moved: {_format_move_summary(res_c_rem)} "
            f"| Expected K/N: {exp_rem_str} | Rule violations: {len(res_c_rem.rule_violations)}"
        )
        print(f"    Hash Mod N moved:         {_format_move_summary(res_m_rem)}")


def do_measure_performance(st):
    """Measure time + memory of core functions according to Section 5(8) and 7.2"""
    node_ids = sorted(list(st["ring"].nodes))
    n = len(node_ids)
    v = st["ring"].v_nodes
    salt = st["ring"].salt
    guest_keys = sorted(st["guests"].guests.keys())
    k = len(guest_keys)

    print("\n--- Performance Measurement (Time & Memory) ---")
    print(f"  Parameters: N={n}, V={v}, M=N*V={n * v}, K={k}, salt={salt}, search_batch={SEARCH_BATCH}")

    # 1. เวลาสร้างวงแหวน และเวลาจัดแขกเริ่มต้น
    t0 = time.perf_counter()
    temp_ring = HashRing(node_ids, v_nodes=v, salt=salt)
    t_build_ring = time.perf_counter() - t0

    t0 = time.perf_counter()
    temp_guests = GuestManager(temp_ring)
    if guest_keys:
        temp_guests.add_guests(guest_keys)
    t_assign_guests = time.perf_counter() - t0

    print(f"  Build ring time:    {t_build_ring * 1e3:.3f} ms")
    print(f"  Assign guests time: {t_assign_guests * 1e3:.3f} ms")

    # 2. เวลาค้นหาเป็นชุด 1,000 ครั้ง แล้วหารต่อครั้ง และเวลาเรียงลำดับห้อง
    if guest_keys:
        step = max(1, len(guest_keys) // SEARCH_BATCH)
        probes = guest_keys[::step][:SEARCH_BATCH]
        while len(probes) < SEARCH_BATCH:
            probes.extend(guest_keys[: SEARCH_BATCH - len(probes)])

        room_probes = [(st["guests"].guests[key].node_id, st["guests"].guests[key].room_no) for key in probes]

        t0 = time.perf_counter()
        for c, s in probes:
            st["ring"].get_node(c, s)
        t_get_node_us = (time.perf_counter() - t0) / len(probes) * 1e6

        t0 = time.perf_counter()
        for c, s in probes:
            st["guests"].find_by_guest(c, s)
        t_find_guest_us = (time.perf_counter() - t0) / len(probes) * 1e6

        t0 = time.perf_counter()
        for nid, rno in room_probes:
            st["guests"].find_by_room(nid, rno)
        t_find_room_us = (time.perf_counter() - t0) / len(room_probes) * 1e6

        t0 = time.perf_counter()
        st["guests"].list_rooms()
        t_sort_rooms_ms = (time.perf_counter() - t0) * 1e3

        print(f"  Ring lookup (get_node, avg of {len(probes)}):      {t_get_node_us:.3f} microseconds")
        print(f"  Average lookup time per guest (find_by_guest): {t_find_guest_us:.3f} microseconds")
        print(f"  Room lookup (find_by_room, avg of {len(room_probes)}): {t_find_room_us:.3f} microseconds")
        print(f"  Sort occupied rooms (list_rooms):              {t_sort_rooms_ms:.3f} ms")
    else:
        print("  No guests available for lookup/sorting timing (K = 0).")

    del temp_guests, temp_ring

    # 3. วัดหน่วยความจำด้วย tracemalloc แยกรอบจากเวลา
    ring_cur, ring_peak = measure_memory(
        lambda: HashRing(node_ids, v_nodes=v, salt=salt)
    )

    def _build_full():
        r = HashRing(node_ids, v_nodes=v, salt=salt)
        gm = GuestManager(r)
        if guest_keys:
            gm.add_guests(guest_keys)
        return r, gm

    total_cur, total_peak = measure_memory(_build_full)
    print(f"  Ring memory (current / peak):   {ring_cur:.4f} MiB / {ring_peak:.4f} MiB")
    print(f"  System memory (current / peak): {total_cur:.4f} MiB / {total_peak:.4f} MiB")
    print("  (Note: Memory measured via Python tracemalloc in a separate pass, not whole-process RSS)")


MENU = [
    ("Run System", do_init),
    ("Add Guest (per person)", do_add_guest),
    ("Add Group (c, defult s, number of guest)", do_add_range),
    ("Remove Guest", do_remove_guest),
    ("Add Building", do_add_building),
    ("Remove Building", do_remove_building),
    ("Find Guest by ID", do_find_guest),
    ("Find Room by ID (building , room)", do_find_room),
    ("Room Lists", do_list_rooms),
    ("Load Reports", do_load),
    ("Export CSV (Guests & Last Moves)", do_export_csv),
    ("Compare Consistent vs Modulo Hashing", do_compare_hashing),
    ("Measure Performance (Time & Memory)", do_measure_performance),
]


def main():
    state = {}
    while True:
        print("\n=== Distributed Hilbert's Hotel ===")
        for i, (name, _) in enumerate(MENU, 1):
            print(f"{i:>2}. {name}")
        print(" 0. Exit")
        choice = ask_int("Select Number: ")
        if choice == 0:
            break
        if not 1 <= choice <= len(MENU):
            print(" Don't have this menu")
            continue
        if choice != 1 and "guests" not in state:
            print(" Please run system first (Select 1)")
            continue
        try:
            MENU[choice - 1][1](state)
        except Exception as e:  # กันโปรแกรมหยุดทุกกรณี
            print(f" Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
