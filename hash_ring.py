import bisect
import hashlib

def compute_sha256_64bit(raw_key: str, salt: str | int | None = None) -> int:
    """แปลงข้อความเป็นตำแหน่งบน ring ขนาด 64-bit โดยใช้ 8 bytes แรกของ SHA-256"""
    if salt is not None and str(salt) != "":
        full_text = f"salt:{salt}:{raw_key}"
    else:
        full_text = raw_key

    digest = hashlib.sha256(full_text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)

class HashRing:
    """Consistent Hashing ring โดยเก็บ virtual node เป็น list ที่เรียงตาม (position, node_id, j)"""

    def __init__(
        self,
        initial_nodes: list[str] | None = None,
        v_nodes: int = 32,
        salt: str | int | None = None,
    ) -> None:
        if v_nodes < 1:
            raise ValueError("จำนวน virtual node (V) ต้องมีค่าอย่างน้อย 1")

        self.v_nodes: int = int(v_nodes)
        self.salt: str | int | None = salt
        self.ring: list[tuple[int, str, int]] = []
        self.nodes: set[str] = set()

        if initial_nodes:
            self._build_initial_ring(initial_nodes)

    def _validate_node_id(self, node_id: str) -> str:
        if not isinstance(node_id, str) or node_id.strip() == "":
            raise ValueError("รหัสอาคาร (node_id) ต้องเป็นสตริงที่ไม่ใช่ค่าว่าง")
        return node_id.strip()

    def _build_initial_ring(self, initial_nodes: list[str]) -> None:
        cleaned_nodes: list[str] = []
        seen: set[str] = set()
        for raw_id in initial_nodes:
            nid = self._validate_node_id(raw_id)
            if nid in seen:
                raise ValueError(f"พบรหัสอาคารซ้ำในรายการเริ่มต้น: {nid}")
            seen.add(nid)
            cleaned_nodes.append(nid)

        for nid in cleaned_nodes:
            self.nodes.add(nid)
            for j in range(self.v_nodes):
                pos = self.hash_vnode(nid, j)
                self.ring.append((pos, nid, j))

        self.ring.sort()

    def hash_guest(self, c: int, s: int) -> int:
        if c < 1 or s < 1:
            raise ValueError("รหัสช่องทาง (c) และลำดับ (s) ต้องเป็นจำนวนเต็มบวก")
        raw_key = f"guest:{c}:{s}"
        return compute_sha256_64bit(raw_key, self.salt)

    def hash_vnode(self, node_id: str, j: int) -> int:
        raw_key = f"node:{node_id}:{j}"
        return compute_sha256_64bit(raw_key, self.salt)

    def add_node(
        self,
        node_id: str,
        custom_positions: list[int] | None = None,
    ) -> tuple[bool, str]:
        """เพิ่ม node เข้า ring และคืนค่า (สถานะ, ข้อความ)
        custom_positions มีไว้กำหนดตำแหน่งเองตอน test เท่านั้น
        """
        try:
            nid = self._validate_node_id(node_id)
        except ValueError as err:
            return False, str(err)

        if nid in self.nodes:
            return False, f"ปฏิเสธคำสั่ง: อาคาร '{nid}' มีอยู่ในระบบแล้ว"

        if custom_positions is not None:
            if len(custom_positions) != self.v_nodes:
                return (
                    False,
                    f"ปฏิเสธคำสั่ง: จำนวนตำแหน่งจำลองต้องเท่ากับ V={self.v_nodes}",
                )
            positions = [int(p) for p in custom_positions]
        else:
            positions = [self.hash_vnode(nid, j) for j in range(self.v_nodes)]

        self.nodes.add(nid)
        for j, pos in enumerate(positions):
            bisect.insort(self.ring, (pos, nid, j))

        return True, f"เพิ่มอาคาร '{nid}' สำเร็จ"

    def remove_node(self, node_id: str) -> tuple[bool, str]:
        """ลบ node ออกจาก ring โดยต้องเหลือ node อย่างน้อย 1 ตัว"""
        try:
            nid = self._validate_node_id(node_id)
        except ValueError as err:
            return False, str(err)

        if nid not in self.nodes:
            return False, f"ปฏิเสธคำสั่ง: ไม่พบอาคาร '{nid}' ในระบบ"

        if len(self.nodes) <= 1:
            return False, "ปฏิเสธคำสั่ง: ไม่สามารถลบอาคารสุดท้ายได้ (ระบบต้องมีอย่างน้อย 1 อาคาร)"

        self.nodes.remove(nid)

        self.ring = [entry for entry in self.ring if entry[1] != nid]
        return True, f"ลบอาคาร '{nid}' สำเร็จ"

    def get_node_by_position(self, guest_pos: int) -> str:
        """หา node ตัวแรกที่ position >= guest_pos ถ้าเลยจุดสุดท้ายก็วนกลับไปจุดแรก"""
        if not self.ring:
            raise RuntimeError("วงแหวนว่างเปล่า ไม่มีอาคารในระบบ")

        search_key = (guest_pos, "", -1)
        idx = bisect.bisect_left(self.ring, search_key)
        if idx == len(self.ring):
            idx = 0
        return self.ring[idx][1]

    def get_node(self, c: int, s: int) -> str:
        """หาว่า guest (c, s) ต้องไปอยู่ node ไหน"""
        guest_pos = self.hash_guest(c, s)
        return self.get_node_by_position(guest_pos)


class ModuloNodeSelector:
    """ไว้เปรียบเทียบกับวิธี hash(guest) mod N โดยใช้ hash แบบเดียวกับ HashRing"""

    def __init__(
        self,
        initial_nodes: list[str] | None = None,
        salt: str | int | None = None,
    ) -> None:
        self.salt: str | int | None = salt
        self.nodes: list[str] = []
        self._node_set: set[str] = set()

        if initial_nodes:
            for raw_id in initial_nodes:
                ok, msg = self.add_node(raw_id)
                if not ok:
                    raise ValueError(msg)

    def hash_guest(self, c: int, s: int) -> int:
        if c < 1 or s < 1:
            raise ValueError("รหัสช่องทาง (c) และลำดับ (s) ต้องเป็นจำนวนเต็มบวก")
        raw_key = f"guest:{c}:{s}"
        return compute_sha256_64bit(raw_key, self.salt)

    def add_node(self, node_id: str) -> tuple[bool, str]:
        if not isinstance(node_id, str) or node_id.strip() == "":
            return False, "รหัสอาคาร (node_id) ต้องเป็นสตริงที่ไม่ใช่ค่าว่าง"
        nid = node_id.strip()
        if nid in self._node_set:
            return False, f"ปฏิเสธคำสั่ง: อาคาร '{nid}' มีอยู่ในระบบแล้ว"

        self.nodes.append(nid)
        self._node_set.add(nid)
        return True, f"เพิ่มอาคาร '{nid}' สำเร็จ"

    def remove_node(self, node_id: str) -> tuple[bool, str]:
        if not isinstance(node_id, str) or node_id.strip() == "":
            return False, "รหัสอาคาร (node_id) ต้องเป็นสตริงที่ไม่ใช่ค่าว่าง"
        nid = node_id.strip()
        if nid not in self._node_set:
            return False, f"ปฏิเสธคำสั่ง: ไม่พบอาคาร '{nid}' ในระบบ"
        if len(self.nodes) <= 1:
            return False, "ปฏิเสธคำสั่ง: ไม่สามารถลบอาคารสุดท้ายได้ (ระบบต้องมีอย่างน้อย 1 อาคาร)"

        self.nodes.remove(nid)
        self._node_set.remove(nid)
        return True, f"ลบอาคาร '{nid}' สำเร็จ"

    def get_node(self, c: int, s: int) -> str:
        if not self.nodes:
            raise RuntimeError("ไม่มีอาคารในระบบ")
        guest_pos = self.hash_guest(c, s)
        idx = guest_pos % len(self.nodes)
        return self.nodes[idx]