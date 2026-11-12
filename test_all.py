import csv
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from building_manager import BuildingManager
from common import RESULTS_DIR, load_statistics
from guest_room import GuestManager, cantor_room_no
from hash_ring import HashRing, ModuloNodeSelector, compute_sha256_64bit
from menu import (
    do_add_building,
    do_add_guest,
    do_compare_hashing,
    do_export_csv,
    do_init,
    do_list_rooms,
    do_measure_performance,
    do_remove_building,
)


""" Test Section 1 -- Hash Ring Core """
class TestPart1_HashRingCore(unittest.TestCase):
    """Test ส่วนหลักของ hash ring (หัวข้อ 4.3-4.5, 7.1, 9.1, 9.2 ข้อ 4)"""

    def test_sha256_64bit_and_prefix_separation(self) -> None:
        """hash 64-bit ต้องได้ค่าเดิมทุกครั้ง และ guest กับ node ต้องไม่ปนกัน"""
        ring = HashRing(["A", "B"], v_nodes=4, salt=0)
        h1 = ring.hash_guest(1, 1)
        h2 = ring.hash_guest(1, 1)
        self.assertEqual(h1, h2)
        self.assertGreaterEqual(h1, 0)
        self.assertLess(h1, 1 << 64)

        ring_num = HashRing(["1"], v_nodes=2, salt=0)
        self.assertNotEqual(ring_num.hash_guest(1, 1), ring_num.hash_vnode("1", 1))

    def test_section_9_1_small_ring_example(self) -> None:
        """ลองตาม ring เล็กๆ ในโจทย์ 9.1"""
        guest_positions = [10, 20, 25, 35, 50, 70, 90]

        # เริ่มที่ A=20, B=50, C=80
        ring_init = HashRing(v_nodes=1)
        ring_init.add_node("A", custom_positions=[20])
        ring_init.add_node("B", custom_positions=[50])
        ring_init.add_node("C", custom_positions=[80])

        initial_assigned = [ring_init.get_node_by_position(p) for p in guest_positions]
        self.assertEqual(initial_assigned, ["A", "A", "B", "B", "B", "C", "A"])

        # เพิ่ม D ที่ 35 จะมีคนย้าย 2 คน (25 และ 35)
        ok, _ = ring_init.add_node("D", custom_positions=[35])
        self.assertTrue(ok)
        after_add_d = [ring_init.get_node_by_position(p) for p in guest_positions]
        self.assertEqual(after_add_d, ["A", "A", "D", "D", "B", "C", "A"])
        moved_add_d = sum(1 for o, n in zip(initial_assigned, after_add_d) if o != n)
        self.assertEqual(moved_add_d, 2)

        # ลบ B จากสถานะเริ่มต้น จะมีคนย้าย 3 คน (25, 35, 50)
        ring_rem_b = HashRing(v_nodes=1)
        ring_rem_b.add_node("A", custom_positions=[20])
        ring_rem_b.add_node("B", custom_positions=[50])
        ring_rem_b.add_node("C", custom_positions=[80])

        ok, _ = ring_rem_b.remove_node("B")
        self.assertTrue(ok)
        after_rem_b = [ring_rem_b.get_node_by_position(p) for p in guest_positions]
        self.assertEqual(after_rem_b, ["A", "A", "C", "C", "C", "C", "A"])
        moved_rem_b = sum(1 for o, n in zip(initial_assigned, after_rem_b) if o != n)
        self.assertEqual(moved_rem_b, 3)

    def test_section_9_2_4_search_and_collision(self) -> None:
        """ลองค้นหาทั้งแบบตรงจุด อยู่ระหว่างจุด วนกลับต้นวง และ virtual node ที่ position ชนกัน"""
        ring = HashRing(v_nodes=2)
        ring.add_node("B", custom_positions=[50, 50])
        ring.add_node("A", custom_positions=[50, 80])

        self.assertEqual(len(ring.ring), 4)
        # ชนกันที่ 50 ได้ A เพราะเรียงตาม (position, node_id, j)
        self.assertEqual(ring.get_node_by_position(50), "A")
        # อยู่ระหว่าง 50 กับ 80 ได้ A ที่ 80
        self.assertEqual(ring.get_node_by_position(65), "A")
        # เลย 80 ไปแล้วจะวนกลับมาที่จุดแรก (50, 'A', 0)
        self.assertEqual(ring.get_node_by_position(95), "A")

        # ลบ A แล้ว B ที่ 50 ต้องยังทำงานได้
        ring.remove_node("A")
        self.assertEqual(ring.get_node_by_position(50), "B")

    def test_section_4_4_2_ring_movement_rules(self) -> None:
        """เมื่อ V > 1 การเพิ่ม node ต้องย้ายเฉพาะคนที่ไป node ใหม่ และการลบต้องไม่กระทบคนอื่น"""
        ring = HashRing(["N1", "N2", "N3"], v_nodes=16, salt=0)
        guests = [(c, s) for c in range(1, 6) for s in range(1, 101)]

        before_add = {g: ring.get_node(*g) for g in guests}
        ring.add_node("N4")
        after_add = {g: ring.get_node(*g) for g in guests}
        for g in guests:
            if before_add[g] != after_add[g]:
                self.assertEqual(after_add[g], "N4")

        ring.remove_node("N2")
        after_rem = {g: ring.get_node(*g) for g in guests}
        for g in guests:
            if after_add[g] != "N2":
                self.assertEqual(after_rem[g], after_add[g])
            else:
                self.assertNotEqual(after_rem[g], "N2")

    def test_section_4_5_node_edge_cases_and_modulo(self) -> None:
        """กรณีขอบ (เพิ่มซ้ำ, ลบที่ไม่มี, ลบตัวสุดท้าย) และ ModuloNodeSelector"""
        ring = HashRing(["N1", "N2"], v_nodes=8)
        snapshot = list(ring.ring)

        ok_dup, _ = ring.add_node("N1")
        self.assertFalse(ok_dup)
        self.assertEqual(ring.ring, snapshot)

        ok_missing, _ = ring.remove_node("N99")
        self.assertFalse(ok_missing)
        self.assertEqual(ring.ring, snapshot)

        self.assertTrue(ring.remove_node("N2")[0])
        self.assertFalse(ring.remove_node("N1")[0])

        mod_ring = ModuloNodeSelector(["A", "B", "C"], salt=0)
        self.assertTrue(mod_ring.remove_node("B")[0])
        self.assertEqual(mod_ring.nodes, ["A", "C"])
        self.assertNotEqual(
            compute_sha256_64bit("guest:1:1", salt=0),
            compute_sha256_64bit("guest:1:1", salt=1),
        )


""" Test Section 2 -- Guest Room Manager """
class TestPart2_CantorRoomNo(unittest.TestCase):
    """ทดสอบสูตร Cantor pairing ที่ใช้คำนวณเลขห้อง (room_no)"""

    def test_known_values(self) -> None:
        """เช็คค่าที่คำนวณมือได้จากตารางในหัวข้อ 4.2: (1,1)->1, (2,1)->2, (1,2)->3, (3,1)->4, (2,2)->5
        ถ้าสูตรผิด (เช่นลืม +1 หรือสลับ a กับ b) เทสนี้จะล้ม"""
        self.assertEqual(cantor_room_no(1, 1), 1)
        self.assertEqual(cantor_room_no(2, 1), 2)
        self.assertEqual(cantor_room_no(1, 2), 3)
        self.assertEqual(cantor_room_no(3, 1), 4)
        self.assertEqual(cantor_room_no(2, 2), 5)

    def test_unique(self) -> None:
        """เช็คว่ารหัสแขกคนละคู่ต้องได้เลขห้องไม่ซ้ำกัน
        ลองทุกคู่ c, s ในช่วง 1..59 (3,481 คู่) แล้วนับว่าจำนวนเลขห้องที่ไม่ซ้ำเท่ากับจำนวนคู่"""
        rooms = {cantor_room_no(c, s) for c in range(1, 60) for s in range(1, 60)}
        self.assertEqual(len(rooms), 59 * 59)

    def test_invalid(self) -> None:
        """เช็คว่า c หรือ s ที่เป็น 0 หรือติดลบ ต้องโดนปฏิเสธด้วย ValueError (ไม่คำนวณต่อ)"""
        for bad in [(0, 1), (1, 0), (-1, 5)]:
            with self.assertRaises(ValueError):
                cantor_room_no(*bad)


class TestPart2_GuestManager(unittest.TestCase):
    """ทดสอบ GuestManager: การเพิ่ม/ลบแขก ดัชนี 2 ทาง และการทำงานร่วมกับ HashRing"""

    def setUp(self) -> None:
        """ก่อนทุกเทส: สร้างวงแหวนใหม่ (อาคาร A, B, C, V=8, salt=0) และ GuestManager ว่างๆ"""
        self.ring = HashRing(["A", "B", "C"], v_nodes=8, salt=0)
        self.gm = GuestManager(self.ring)

    def test_add_remove_and_duplicates(self) -> None:
        """กรณีขอบเรื่องแขก: เพิ่มรหัสซ้ำต้องถูกปฏิเสธ, ลบแขกที่ไม่มีต้องถูกปฏิเสธ
        (ได้ False) และลบแขกที่มีอยู่ต้องสำเร็จ จนจำนวนแขกกลับเป็น 0"""
        self.assertTrue(self.gm.add_guest(1, 1)[0])
        self.assertFalse(self.gm.add_guest(1, 1)[0])
        self.assertFalse(self.gm.remove_guest(9, 9)[0])
        self.assertTrue(self.gm.remove_guest(1, 1)[0])
        self.assertEqual(len(self.gm), 0)

    def test_group_all_or_nothing(self) -> None:
        """กฎเพิ่มแขกเป็นกลุ่ม: ถ้ามีรหัสซ้ำแม้ 1 รายการ ต้องปฏิเสธทั้งกลุ่ม
        กรณีซ้ำกับแขกที่มีอยู่แล้ว, กรณีซ้ำกันเองภายในกลุ่ม
        แล้วเช็คว่าจำนวนแขกยังเป็น 1 (คนเดิม) ไม่มีแขกหลุดเข้ามาครึ่งๆ กลางๆ"""
        self.gm.add_guest(1, 1)
        ok, _ = self.gm.add_guests([(2, 1), (3, 1), (1, 1)])
        self.assertFalse(ok)
        self.assertEqual(len(self.gm), 1)
        ok, _ = self.gm.add_guests([(2, 1), (2, 1)])
        self.assertFalse(ok)
        self.assertEqual(len(self.gm), 1)

    def test_two_way_lookup(self) -> None:
        """ดัชนีค้นหา 2 ทางต้องสอดคล้องกัน: รหัสแขก -> (อาคาร, ห้อง) แล้วเอาผลนั้นไปค้นกลับ
        ต้องได้รหัสแขกเดิม ทดสอบหลายคน และเช็คกรณีค้นไม่พบ (ต้องได้ None ไม่ใช่ error)"""
        self.gm.populate_initial(3, 20)
        for (c, s) in [(1, 1), (2, 7), (3, 20)]:
            node, room = self.gm.find_by_guest(c, s)
            self.assertEqual(self.gm.find_by_room(node, room), (c, s))
        self.assertIsNone(self.gm.find_by_guest(99, 99))
        self.assertIsNone(self.gm.find_by_room("A", 10**9))

    def test_empty_and_sorted_listing(self) -> None:
        """กรณีไม่มีแขกเลย (K=0): list_rooms ต้องได้ลิสต์ว่าง และผลรวมโหลดต้องเป็น 0 (ไม่ error)
        จากนั้นเพิ่มแขก 60 คน: รายการห้องต้องเรียงตาม node_id แล้ว room_no
        และผลรวมแขกทุกอาคารต้องได้ 60 พอดี (ไม่มีใครหายหรือซ้ำ)"""
        self.assertEqual(self.gm.list_rooms(), [])
        self.assertEqual(sum(self.gm.load_per_node().values()), 0)
        self.gm.populate_initial(2, 30)
        rows = self.gm.list_rooms()
        self.assertEqual(rows, sorted(rows))
        self.assertEqual(sum(self.gm.load_per_node().values()), 60)

    def test_room_unchanged_after_ring_change(self) -> None:
        """เทสหลักที่เชื่อมกับวงแหวน: หลังเพิ่มอาคาร D
        1) find_misplaced ต้องเจอแขกที่ต้องย้าย และทุกคนที่ย้ายต้องย้ายไป D เท่านั้น
           (ตามหลัก consistent hashing)
        2) หลัง move_guest ครบ ดัชนีต้องสอดคล้องกับวงแหวน (verify_consistency เป็น True)
        3) เลขห้อง (room_no) ของทุกคนต้องไม่เปลี่ยน เปลี่ยนแค่ node_id"""
        self.gm.populate_initial(3, 50)
        rooms_before = {k: g.room_no for k, g in self.gm.guests.items()}
        self.assertTrue(self.ring.add_node("D")[0])
        moved = self.gm.find_misplaced()
        self.assertFalse(self.gm.verify_consistency() and moved)
        for c, s, _old, new in moved:
            self.assertEqual(new, "D")
            self.gm.move_guest(c, s, new)
        self.assertTrue(self.gm.verify_consistency())
        self.assertEqual(rooms_before, {k: g.room_no for k, g in self.gm.guests.items()})

    def test_add_guests_range(self) -> None:
        """ทดสอบการเพิ่มแขกแบบระบุช่วง (c, s_start, count) ตามหัวข้อ 4.1 ข้อ 3"""
        ok, _ = self.gm.add_guests_range(1, 1, 5)
        self.assertTrue(ok)
        self.assertEqual(len(self.gm), 5)
        self.assertEqual(sorted(self.gm.guests), [(1, s) for s in range(1, 6)])

        ok, _ = self.gm.add_guests_range(2, 10, 0)
        self.assertTrue(ok)
        self.assertEqual(len(self.gm), 5)

        for bad in (-1, 1.5, True, "3"):
            self.assertFalse(self.gm.add_guests_range(2, 1, bad)[0])
        self.assertFalse(self.gm.add_guests_range(0, 1, 3)[0])
        self.assertEqual(len(self.gm), 5)

        ok, _ = self.gm.add_guests_range(1, 3, 5)
        self.assertFalse(ok)
        self.assertEqual(len(self.gm), 5)
        self.assertTrue(self.gm.verify_consistency())


""" Test Section 3 -- Building Manager (เพิ่ม/ลบอาคาร และการย้ายแขก) """
class TestPart3_BuildingManager(unittest.TestCase):
    """ทดสอบการเพิ่ม/ลบอาคารตามหัวข้อ 4.4 และกรณีขอบ 4.5"""

    def setUp(self) -> None:
        """ก่อนทุกเทส: อาคาร N1-N4 (V=16, salt=0) แขก 5 ช่องทาง ช่องละ 200 คน (K=1000)"""
        self.ring = HashRing(["N1", "N2", "N3", "N4"], v_nodes=16, salt=0)
        self.gm = GuestManager(self.ring)
        self.gm.populate_initial(5, 200)
        self.bm = BuildingManager(self.ring, self.gm)

    def test_add_building_moves_only_to_new_building(self) -> None:
        """เพิ่มอาคาร N5: ผู้ย้ายต้องเข้า N5 เท่านั้น (4.4 ข้อ 2) จำนวนย้ายนับเป็นรหัสแขก
        อัตราย้าย = ย้าย/K, เลขห้องไม่เปลี่ยน, ดัชนีสอดคล้องกับวงแหวน และจำนวนแขกไม่หาย"""
        rooms_before = {k: g.room_no for k, g in self.gm.guests.items()}
        nodes_before = {k: g.node_id for k, g in self.gm.guests.items()}
        r = self.bm.add_building("N5")
        self.assertTrue(r.ok)
        self.assertGreater(r.moved_count, 0)
        self.assertEqual(r.rule_violations, [])
        self.assertTrue(all(m.new_node == "N5" for m in r.moves))
        self.assertEqual(r.total_guests, 1000)
        self.assertEqual(r.moved_count, len(r.moves))
        self.assertAlmostEqual(r.moved_rate, r.moved_count / 1000)
        changed = {k for k, g in self.gm.guests.items() if g.node_id != nodes_before[k]}
        self.assertEqual(changed, {(m.c, m.s) for m in r.moves})
        self.assertTrue(self.gm.verify_consistency())
        self.assertEqual(len(self.gm), 1000)
        self.assertEqual(rooms_before, {k: g.room_no for k, g in self.gm.guests.items()})

    def test_remove_building_moves_only_its_guests(self) -> None:
        """ลบอาคาร N2: ย้ายเฉพาะแขกของ N2 (เท่ากับจำนวนแขกใน N2 ก่อนลบ) และไม่มีใครค้างที่ N2"""
        victims = self.gm.load_per_node()["N2"]
        r = self.bm.remove_building("N2")
        self.assertTrue(r.ok)
        self.assertEqual(r.rule_violations, [])
        self.assertEqual(r.moved_count, victims)
        self.assertTrue(all(m.old_node == "N2" and m.new_node != "N2" for m in r.moves))
        self.assertNotIn("N2", self.gm.load_per_node())
        self.assertTrue(self.gm.verify_consistency())
        self.assertEqual(len(self.gm), 1000)

    def test_move_records_and_room_lookup(self) -> None:
        """รายการย้ายต้องมี รหัสแขก อาคารเดิม อาคารใหม่ เลขห้อง ที่ถูกต้อง
        และหลังย้าย ค้นด้วย (อาคารใหม่, ห้อง) ต้องเจอแขกคนเดิม ส่วนอาคารเก่าต้องค้นไม่เจอ"""
        r = self.bm.add_building("N5")
        self.assertGreater(len(r.moves), 0)
        for m in r.moves:
            self.assertEqual(m.room_no, cantor_room_no(m.c, m.s))
            self.assertEqual(self.gm.find_by_room(m.new_node, m.room_no), (m.c, m.s))
            self.assertIsNone(self.gm.find_by_room(m.old_node, m.room_no))
            self.assertEqual(self.gm.find_by_guest(m.c, m.s), (m.new_node, m.room_no))

    def test_edge_cases_leave_everything_unchanged(self) -> None:
        """กรณีขอบ 4.5: เพิ่มซ้ำ, ลบที่ไม่มี, รหัสว่าง ต้องถูกปฏิเสธ (ok=False) โดยวงแหวนและแขกไม่เปลี่ยน
        แล้วลบจนเหลืออาคารเดียว ตัวสุดท้ายต้องลบไม่ได้ และแขกทั้ง 1000 คนยังอยู่ครบ"""
        ring_snapshot = list(self.ring.ring)
        guests_snapshot = {k: g.node_id for k, g in self.gm.guests.items()}
        for r in (self.bm.add_building("N1"), self.bm.remove_building("N99"),
                  self.bm.add_building("  "), self.bm.remove_building("")):
            self.assertFalse(r.ok)
            self.assertEqual(r.moved_count, 0)
            self.assertTrue(r.message)
        self.assertEqual(self.ring.ring, ring_snapshot)
        self.assertEqual({k: g.node_id for k, g in self.gm.guests.items()}, guests_snapshot)

        for nid in ("N1", "N2", "N3"):
            self.assertTrue(self.bm.remove_building(nid).ok)
        r = self.bm.remove_building("N4")
        self.assertFalse(r.ok)
        self.assertEqual(self.bm.list_buildings(), ["N4"])
        self.assertEqual(self.gm.load_per_node(), {"N4": 1000})
        self.assertTrue(self.gm.verify_consistency())

    def test_no_guests_rate_not_computed(self) -> None:
        """K=0 (4.4 ข้อ 4): จำนวนย้ายเป็น 0, ไม่คำนวณอัตราย้าย (None) และมีข้อความอธิบาย ไม่ error"""
        ring = HashRing(["A", "B", "C"], v_nodes=8, salt=0)
        bm = BuildingManager(ring, GuestManager(ring))
        for r in (bm.add_building("D"), bm.remove_building("A")):
            self.assertTrue(r.ok)
            self.assertEqual(r.moved_count, 0)
            self.assertIsNone(r.moved_rate)
            self.assertIn("K = 0", r.rate_note)

    def test_add_then_remove_restores_original(self) -> None:
        """เพิ่ม N5 แล้วลบ N5 วงแหวนกลับเหมือนเดิม แขกทุกคนต้องกลับไปอาคารเดิม
        และจำนวนที่ย้ายตอนลบ = จำนวนที่ย้ายตอนเพิ่ม"""
        before = {k: g.node_id for k, g in self.gm.guests.items()}
        added = self.bm.add_building("N5")
        removed = self.bm.remove_building("N5")
        self.assertEqual(added.moved_count, removed.moved_count)
        self.assertEqual({k: g.node_id for k, g in self.gm.guests.items()}, before)
        self.assertTrue(self.gm.verify_consistency())

    def test_expected_value_and_hash_ring_beats_modulo(self) -> None:
        """ใช้ชุดแขกเดียวกัน เพิ่มอาคารเหมือนกัน: Consistent Hashing ย้ายน้อยกว่า hash mod N มาก
        (ค่าคาดหวัง K/(N+1) = 200 คน เทียบกับ mod ที่ย้ายราว 4/5 ของ K) และเก็บค่าคาดหวังไว้ในผลลัพธ์"""
        ring_r = self.bm.add_building("N5")
        self.assertAlmostEqual(ring_r.expected_moved, 1000 / 5)

        mod = ModuloNodeSelector(["N1", "N2", "N3", "N4"], salt=0)
        gm_mod = GuestManager(mod)
        gm_mod.populate_initial(5, 200)
        r_mod = BuildingManager(mod, gm_mod, check_rules=False).add_building("N5")
        self.assertTrue(r_mod.ok)
        self.assertTrue(gm_mod.verify_consistency())
        self.assertLess(ring_r.moved_count, r_mod.moved_count)

    def test_timing_fields_present(self) -> None:
        """เก็บเวลาแยกตามขั้นตอน (ปรับวงแหวน / หาแขกที่ย้าย / ย้ายและปรับดัชนี) เป็นค่าไม่ติดลบ"""
        r = self.bm.add_building("N5")
        for t in (r.t_ring_adjust, r.t_find_affected, r.t_update_data):
            self.assertGreaterEqual(t, 0.0)
        self.assertGreater(r.t_find_affected, 0.0)


""" Test Section 4 -- Additional Requirements for Part 5 & Common """
class TestPart5_AdditionalRequirements(unittest.TestCase):
    """ทดสอบส่วนเพิ่มเติมตามเช็กลิสต์ Part 5 และ common.py"""

    def _cleanup_file(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def test_load_statistics(self) -> None:
        """1. load_statistics: K=0 ได้ cv=None, กรณีปกติได้สถิติตามจริง, ลิสต์ว่างต้อง raise ValueError"""
        stats = load_statistics([10, 20, 30])
        self.assertEqual(stats["max"], 30)
        self.assertEqual(stats["min"], 10)
        self.assertAlmostEqual(stats["mean"], 20.0)
        self.assertIsNotNone(stats["cv"])

        stats_zero = load_statistics([0, 0, 0])
        self.assertEqual(stats_zero["max"], 0)
        self.assertEqual(stats_zero["min"], 0)
        self.assertEqual(stats_zero["mean"], 0.0)
        self.assertEqual(stats_zero["sd"], 0.0)
        self.assertIsNone(stats_zero["cv"])

        with self.assertRaises(ValueError):
            load_statistics([])

    def test_sha256_fixed_values(self) -> None:
        """2. ค่า SHA-256 64-bit ที่ fix ไว้เพื่อป้องกันพฤติกรรมแฮชเปลี่ยนข้ามเวอร์ชัน/การรัน"""
        h_guest_0 = compute_sha256_64bit("guest:1:1", salt=0)
        h_guest_1 = compute_sha256_64bit("guest:1:1", salt=1)
        h_node_0 = compute_sha256_64bit("node:NODE01:0", salt=0)

        self.assertIsInstance(h_guest_0, int)
        self.assertGreaterEqual(h_guest_0, 0)
        self.assertLess(h_guest_0, 1 << 64)

        self.assertEqual(h_guest_0, 2075508245625393561)
        self.assertEqual(h_guest_1, 17442632927375598857)
        self.assertEqual(h_node_0, 4495497354209293340)
        self.assertNotEqual(h_guest_0, h_guest_1)
        self.assertNotEqual(h_guest_0, h_node_0)

    def test_csv_export_format(self) -> None:
        """3. การ Export CSV (จำนวนแถวเท่ากับ K, Header ถูกต้อง)"""
        ring = HashRing(["NODE01", "NODE02"], v_nodes=4, salt=0)
        gm = GuestManager(ring)
        gm.populate_initial(2, 5)  # K = 10 คน

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        export_path = RESULTS_DIR / "test_export_guests.csv"
        self.addCleanup(self._cleanup_file, export_path)

        rows = [
            {"channel_id": c, "sequence_id": s, "node_id": node_id, "room_no": room_no}
            for node_id, room_no, c, s in gm.list_rooms()
        ]
        with export_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["channel_id", "sequence_id", "node_id", "room_no"])
            writer.writeheader()
            writer.writerows(rows)

        self.assertTrue(export_path.exists())
        with export_path.open("r", encoding="utf-8") as fh:
            reader = list(csv.DictReader(fh))
            self.assertEqual(len(reader), 10)
            self.assertEqual(reader[0].keys(), {"channel_id", "sequence_id", "node_id", "room_no"})

    def test_menu_input_handling_and_mock(self) -> None:
        """4. เมนูจัดการอินพุตและดักจับข้อผิดพลาดผ่าน unittest.mock.patch"""
        state = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("builtins.input", side_effect=["3", "4", "0", "2", "10"]):
                do_init(state)
            self.assertIn("guests", state)
            self.assertEqual(len(state["guests"]), 20)

            with patch("builtins.input", side_effect=["abc", "1", "1"]):
                do_add_guest(state)
                self.assertEqual(len(state["guests"]), 20)

    def test_menu_export_csv_action(self) -> None:
        """5. ทดสอบว่า do_add_building บันทึก last_change_result และ do_export_csv เขียนไฟล์ทั้งสองได้จริง"""
        guest_csv = RESULTS_DIR / "menu_export_guests.csv"
        moves_csv = RESULTS_DIR / "menu_export_last_moves.csv"
        self.addCleanup(self._cleanup_file, guest_csv)
        self.addCleanup(self._cleanup_file, moves_csv)

        state = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("builtins.input", side_effect=["2", "8", "0", "3", "20"]):
                do_init(state)
            with patch("builtins.input", side_effect=["NODE03"]):
                do_add_building(state)
            self.assertIsNotNone(state["last_change_result"])
            self.assertTrue(state["last_change_result"].ok)
            do_export_csv(state)

            with patch("builtins.input", side_effect=["NODE01"]):
                do_remove_building(state)

        self.assertTrue(guest_csv.exists())
        self.assertTrue(moves_csv.exists())
        self.assertIn("Expected K/N", buf.getvalue())

    def test_menu_compare_and_performance(self) -> None:
        """6. ทดสอบการเปรียบเทียบ Consistent vs Modulo ในเมนู และการวัดประสิทธิภาพ"""
        state = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("builtins.input", side_effect=["3", "8", "0", "2", "50"]):
                do_init(state)
            do_list_rooms(state)
            do_compare_hashing(state)
            do_measure_performance(state)

        output = buf.getvalue()
        self.assertIn("Total occupied rooms: 100", output)
        self.assertNotIn("Consistent Hashing moved: 0 (", output)
        self.assertIn("tracemalloc", output)


""" Test Section 9.2 -- Minimum Checklist """
class TestSection9_2_MinimumChecklist(unittest.TestCase):
    """เช็กลิสต์ขั้นต่ำตามโจทย์หัวข้อ 9.2 และ 4.5 ที่ยังไม่ถูกครอบในคลาสอื่น"""

    def setUp(self) -> None:
        self.ring = HashRing(["NODE01", "NODE02", "NODE03"], v_nodes=16, salt=0)
        self.gm = GuestManager(self.ring)

    def _cleanup_file(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def test_9_2_1_new_guests_never_move_existing_guests(self) -> None:
        """9.2 ข้อ 1: เพิ่มแขกใหม่ทั้งช่องทางเดิมและช่องทางใหม่ (รายคนและเป็นกลุ่ม)
        ที่อยู่ห้องของแขกเดิมต้องไม่เปลี่ยนแม้แต่คนเดียว ทั้ง node_id และ room_no"""
        self.gm.populate_initial(3, 100)  # แขกเดิม 300 คน
        before = {k: (g.node_id, g.room_no) for k, g in self.gm.guests.items()}

        self.assertTrue(self.gm.add_guests_range(1, 101, 30)[0])   # ช่องทางเดิม เป็นกลุ่ม
        self.assertTrue(self.gm.add_guest(3, 101)[0])              # ช่องทางเดิม รายคน
        self.assertTrue(self.gm.add_guests_range(4, 1, 100)[0])    # ช่องทางใหม่ เป็นกลุ่ม
        self.assertTrue(self.gm.add_guests([(5, 1)])[0])           # ช่องทางใหม่ รายคน

        after = {k: (g.node_id, g.room_no) for k, g in self.gm.guests.items()}
        for key, address in before.items():
            self.assertEqual(after[key], address, f"แขกเดิม {key} ถูกย้ายทั้งที่ไม่ควรขยับ")
        self.assertEqual(len(self.gm), 300 + 132)
        self.assertTrue(self.gm.verify_consistency())

    def test_9_2_3_rejected_batch_leaves_data_untouched(self) -> None:
        """9.2 ข้อ 3: กลุ่มที่ซ้ำเพียงบางรายการต้องถูกปฏิเสธ และข้อมูลเดิมต้องเหมือนเดิมทุกค่า"""
        self.gm.populate_initial(2, 20)
        before = {k: (g.node_id, g.room_no) for k, g in self.gm.guests.items()}
        before_rooms = self.gm.list_rooms()

        ok, _ = self.gm.add_guests([(1, 21), (1, 22), (2, 5), (1, 23)])  # (2,5) ซ้ำ
        self.assertFalse(ok)
        ok, _ = self.gm.add_guests_range(1, 19, 5)  # ทับ (1,19) และ (1,20)
        self.assertFalse(ok)

        after = {k: (g.node_id, g.room_no) for k, g in self.gm.guests.items()}
        self.assertEqual(after, before)
        self.assertEqual(self.gm.list_rooms(), before_rooms)
        self.assertEqual(len(self.gm), 40)
        self.assertTrue(self.gm.verify_consistency())

    def test_9_2_6_csv_rows_match_current_guest_count(self) -> None:
        """9.2 ข้อ 6: จำนวนแถวใน CSV ที่เมนูส่งออก = จำนวนแขกปัจจุบัน (หลังเพิ่ม/ลบแขกและเพิ่มอาคาร)"""
        guest_csv = RESULTS_DIR / "menu_export_guests.csv"
        self.addCleanup(self._cleanup_file, guest_csv)
        self.addCleanup(self._cleanup_file, RESULTS_DIR / "menu_export_last_moves.csv")

        state = {}
        buf = io.StringIO()
        with redirect_stdout(buf):
            with patch("builtins.input", side_effect=["3", "8", "0", "4", "25"]):
                do_init(state)  # K = 100
            state["guests"].add_guests_range(5, 1, 10)
            state["guests"].remove_guest(1, 1)
            with patch("builtins.input", side_effect=["NODE04"]):
                do_add_building(state)
            do_export_csv(state)

        expected = len(state["guests"])
        self.assertEqual(expected, 109)
        with guest_csv.open("r", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), expected)
        self.assertTrue(state["guests"].verify_consistency())

    def test_9_2_6_remove_last_building_without_guests(self) -> None:
        """4.5: ลบอาคารสุดท้ายต้องถูกปฏิเสธแม้ไม่มีแขก และวงแหวนยังค้นหาได้"""
        ring = HashRing(["NODE01"], v_nodes=8, salt=0)
        gm = GuestManager(ring)
        buildings = BuildingManager(ring, gm)

        result = buildings.remove_building("NODE01")
        self.assertFalse(result.ok)
        self.assertEqual(result.moved_count, 0)
        self.assertEqual(buildings.list_buildings(), ["NODE01"])
        self.assertEqual(ring.get_node(1, 1), "NODE01")

        self.assertTrue(gm.add_guest(1, 1)[0])
        self.assertEqual(gm.find_by_guest(1, 1), ("NODE01", cantor_room_no(1, 1)))

    def test_init_with_different_guest_count_per_channel(self) -> None:
        """หัวข้อ 5 ข้อ 1: กำหนดจำนวนแขกของแต่ละช่องทางแยกกันได้ ลำดับ s เริ่มที่ 1 ทุกช่องทาง"""
        counts = {1: 5, 2: 12, 3: 1}
        for c, count in counts.items():
            self.assertTrue(self.gm.add_guests_range(c, 1, count)[0])

        self.assertEqual(len(self.gm), sum(counts.values()))
        for c, count in counts.items():
            seqs = sorted(s for (ch, s) in self.gm.guests if ch == c)
            self.assertEqual(seqs, list(range(1, count + 1)))
        self.assertTrue(self.gm.verify_consistency())

    def test_load_report_with_no_guests(self) -> None:
        """หัวข้อ 5 ข้อ 7 / 7.2: K=0 รายงานทุกอาคารเป็น 0 สถิติพื้นฐานเป็น 0 และไม่คำนวณ CV"""
        loads = self.gm.load_per_node()
        self.assertEqual(sorted(loads), ["NODE01", "NODE02", "NODE03"])
        self.assertEqual(set(loads.values()), {0})

        stats = load_statistics(list(loads.values()))
        self.assertEqual(stats["max"], 0)
        self.assertEqual(stats["min"], 0)
        self.assertEqual(stats["mean"], 0.0)
        self.assertEqual(stats["sd"], 0.0)
        self.assertIsNone(stats["cv"])
        self.assertEqual(self.gm.list_rooms(), [])


if __name__ == "__main__":
    unittest.main()
