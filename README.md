# Distributed Hilbert's Hotel (Consistent Hashing)

โครงงานรายวิชา Object Oriented Data Structure ภาคการศึกษา 1/2569  
ระบบจัดสรรห้องพักเครือโรงแรมอนันต์แบบกระจายศูนย์ ด้วยเทคนิค **Consistent Hashing** เพื่อลดการโยกย้ายห้องพักเมื่อมีการเพิ่มหรือลดอาคาร (Node)

---

## 🛠️ ความต้องการของระบบ (System Requirements)
* **Python**: Version 3.10 ขึ้นไป (ทดสอบบน `Python 3.13.14`)
* **Standard Libraries**: `bisect`, `hashlib`, `unittest` (ไม่มี Third-party dependency ในโมดูลหลัก)

---

## 📂 โครงสร้างโปรเจกต์ (Project Structure)
```text
OOD_Camel_Hotel/
├── hash_ring.py      # Core Consistent Hashing Ring & ModuloNodeSelector
├── test_all.py       # Unit tests ครอบคลุมกฎและกรณีขอบทั้งหมด
├── .gitignore        # Git ignore rules
└── README.md         # เอกสารแนะนำและคู่มือการรัน
```

---

## 🚀 วิธีการทดสอบ (Running Tests)
รัน Unit test ทั้งหมดด้วยคำสั่ง:
```bash
python -m unittest test_all.py -v
```

---

## 📌 สรุปคุณสมบัติในส่วน Part 1: Hash Ring Core
* **64-bit SHA-256**: แมปรหัสแขกและ node เป็นตำแหน่งบน ring ขนาด $0$ ถึง $2^{64}-1$ คงที่ข้ามการรัน
* **Consistent Hash Ring**:
  * รองรับ Virtual Node ($V \ge 1$) ต่อ Node เพื่อกระจายโหลด
  * รองรับ Tie-breaking เรียงตาม `(position, node_id, j)` เมื่อตำแหน่งแฮชตรงกัน
  * ค้นหาแบบ Clockwise Wrap-around ด้วย Binary Search (`bisect.bisect_left`)
* **Edge Cases & Graceful Rejection**: ป้องกันการเพิ่ม node ซ้ำ, ลบ node ที่ไม่มีอยู่, และลบ node สุดท้าย
* **Modulo Baseline (`ModuloNodeSelector`)**: ตัวเปรียบเทียบแบบ $\text{hash(guest)} \bmod N$
