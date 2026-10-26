""" ข้อสำคัญ: เมธอดส่วนใหญ่คืน (bool, str) ไม่ throw exception
เมนูจึงแค่พิมพ์ข้อความที่ได้กลับมา และมี try/except กันโปรแกรมหยุดอีกชั้น
"""

import csv
import time
from pathlib import Path
from hash_ring import HashRing, ModuloNodeSelector
from common import RESULTS_DIR, load_statistics, measure_memory
from guest_room import GuestManager
from building_manager import BuildingManager

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
            print(f"  Expected Moved = {r.expected_moved:.2f} (Expected K/(N+1))")
    
    print(f"  Timing -> Ring adjust: {r.t_ring_adjust:.6f}s | Find affected: {r.t_find_affected:.6f}s | Update data: {r.t_update_data:.6f}s")
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
    show_change(st["buildings"].add_building(ask_str("New building ID: ")))


def do_remove_building(st):
    show_change(st["buildings"].remove_building(ask_str("Remove building ID: ")))


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
        print(" Don't have any guest")
        return
    for row in rows[:MAX_PRINT * 5]:
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
    """ Export CSV from menu (guests+rooms and latest moves)"""
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
    print(f"  -> Exported guests successfully: {guest_path.relative_to(Path.cwd())} ({len(rows)} rows)")

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
            writer = csv.DictWriter(fh, fieldnames=["action", "building_id", "channel_id", "sequence_id", "old_node", "new_node", "room_no"])
            writer.writeheader()
            writer.writerows(move_rows)
        print(f"  -> Exported last moves successfully: {move_path.relative_to(Path.cwd())} ({len(move_rows)} rows)")
    else:
        print("  (No recent move records or no building change performed yet)")
        
def do_compare_hashing(st):
    """2. Compare Consistent Hashing with hash mod N"""
    node_ids = sorted(list(st["ring"].nodes))
    if len(node_ids) < 2:
        print("  Need at least 2 buildings to compare.")
        return
    target_node = "COMPARE_NEW_NODE"
    
    import copy
    ring_copy = copy.deepcopy(st["ring"])
    guests_copy = copy.deepcopy(st["guests"])
    bm_consistent = BuildingManager(ring_copy, guests_copy, check_rules=False)
    res_c = bm_consistent.add_building(target_node)

    mod_selector = ModuloNodeSelector(node_ids, salt=st["ring"].salt)
    guests_mod = GuestManager(mod_selector)
    for (c, s), g in st["guests"].guests.items():
        guests_mod.add_guest(c, s)
    bm_modulo = BuildingManager(mod_selector, guests_mod, check_rules=False)
    res_m = bm_modulo.add_building(target_node)

    print("\n--- Comparison Results for Adding a New Building ---")
    print(f"  Total Guests K = {len(st['guests'])}")
    print(f"  Initial Buildings N = {len(node_ids)}")
    print(f"  Consistent Hashing moved: {res_c.moved_count} ({res_c.moved_rate:.2%}) | Expected K/(N+1): {res_c.expected_moved:.2f}")
    print(f"  Hash Mod N moved: {res_m.moved_count} ({res_m.moved_rate:.2%})")


def do_measure_performance(st):
    """3. Measure time + memory of core functions"""
    print("\n--- Performance Measurement ---")
    probes = list(st["guests"].guests.keys())[:1000]
    if not probes:
        print("  No guests available for lookup testing.")
        return

    t0 = time.perf_counter()
    for c, s in probes:
        st["guests"].find_by_guest(c, s)
    t_search = (time.perf_counter() - t0) / len(probes) * 1e6
    print(f"  Average lookup time per guest (find_by_guest): {t_search:.3f} microseconds")

    current, peak = measure_memory(lambda: (HashRing(list(st["ring"].nodes), v_nodes=st["ring"].v_nodes, salt=st["ring"].salt)))
    print(f"  Ring memory (current / peak): {current:.4f} MiB / {peak:.4f} MiB")


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