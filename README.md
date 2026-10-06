# Palantir: Novel

โปรแกรมเดสก์ท็อป Windows สำหรับจัดไฟล์และขั้นตอนงานแปลนิยาย ผู้ใช้เลือกขั้นตอนและทำงานแปลเอง โปรแกรมช่วย COPY STEP, แก้เอกสาร, จำ Context และติดตามการส่งงาน ไม่มี AI translation API และไม่มีระบบตัดสินสถานะรายบทอัตโนมัติ

## การใช้งาน

Navigation อยู่ด้านซ้าย: **คลังนิยาย / กำลังทำงาน / สถิติ / กลุ่ม / ตั้งค่า** ย่อเป็นไอคอนและลากปรับความกว้างได้ โปรแกรมจำขนาดและสถานะที่เลือกไว้ แต่ละเรื่องมี Workspace ของตัวเอง

- Novel Header เหนือ Editor แสดง **แปลถึงบท …**, จำนวนบทที่เพิ่มวันนี้, เป้าหมายแปล, verified ที่ส่งวันนี้ และรอบส่งปัจจุบัน
- Workflow หลักเริ่มด้วย **แปล / ตรวจคำแปล** และรองรับขั้นตอน custom เดิม
- **หาศัพท์** เป็นเครื่องมือเตรียมไฟล์แยกจาก Workflow หลัก ใช้ vocabulary_step และ COPY STEP เดิม ไม่มีการเรียก API
- หมวดนิยายคง **กำลังแปล / พักแปล / ชนต้นฉบับแล้ว / กำลังเช็กกับเว็บ** คำสั่งอยู่ใน More ของ Editor หลังเปลี่ยนสถานะมี toast **ย้อนกลับ** คืนสถานะก่อนหน้า
- Settings จัดการโปรไฟล์, ไฟล์ทำงาน, Context, Workflow และรายการ Launcher ส่วน Groups เปิดหลายเรื่องพร้อมกันได้

## Editor และแท็บ

เอกสารอยู่ในแท็บแถวเดียว เลื่อนเมื่อพื้นที่ไม่พอ ลากเรียงไฟล์ได้ ชื่อยาวย่อพร้อม tooltip ชื่อเต็ม และเอกสารที่ยังไม่บันทึกมี **●** โปรแกรมจำลำดับ/แท็บที่เปิด/ตำแหน่งอ่านข้าม restart

**TXT Export** เป็นแท็บถาวรขวาสุด ปิดไม่ได้ ไฟล์ใหม่แทรกก่อนแท็บนี้ แถบเครื่องมือ Editor มี Undo, Redo, ค้นหา และขนาดตัวอักษร คำสั่งรองอยู่ใน **More (...)** และใช้เมนูเมื่อพื้นที่แคบ

Editor ใช้ **Segoe UI** เป็นฟอนต์หลักขนาดเริ่มต้น 11 pt หากไม่มีใช้ฟอนต์ทั่วไปของระบบ Qt ใช้ fallback ภาษาไทย/จีน/ญี่ปุ่นจากฟอนต์ที่ติดตั้งใน Windows ส่วน UI ใช้ Segoe UI พร้อม Leelawadee UI/Tahoma fallback ไม่ฝัง Apple SF font

Light/Dark ใช้พื้นผิวเรียบและ blue accent ที่อ่านง่าย แยกสี hover, selection, current line และ keyboard focus ปกนิยายและขั้นตอนที่เลือกมีทั้งพื้นหลังและตัวบ่งชี้ accent

Status bar ใช้สำหรับเอกสาร: สถานะบันทึก, คำ/อักขระ, Ln/Col และ UTF-8 ข้อความยาวย่อพร้อม tooltip

### Shortcuts

| ปุ่ม | การทำงาน |
| --- | --- |
| Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+A | Copy / Cut / Paste / Select All ในช่องที่ focus |
| Ctrl+Z | Undo |
| Ctrl+Y หรือ Ctrl+Shift+Z | Redo |
| Ctrl+S | Save เอกสารปัจจุบัน |
| Ctrl+H | Find / Replace |
| Ctrl+Tab / Ctrl+Shift+Tab | เอกสารถัดไป / ก่อนหน้า |
| Ctrl+Shift+C | COPY STEP |
| Ctrl+- / Ctrl++ / Ctrl+0 | ลด / เพิ่ม / คืนขนาดตัวอักษร |

Undo/Redo toolbar ตาม history ของ editor ปัจจุบัน รวม TXT Export การบันทึกอัตโนมัติไม่ล้าง undo stack

## Context และความคืบหน้า

อ่านเฉพาะ recognized heading เช่น `บทที่ 123`, `บทที่ 123-125`, `第123章`, `Chapter 123`, `Chapter 123-125` และ Markdown heading โปรแกรมเลือก chapter end สูงสุดจาก heading ที่ valid ไม่ใช้ตัวเลขธรรมดาในเนื้อเรื่องหรือช่วงที่ย้อนกลับ

Context watcher และการตรวจซ้ำทุก 10 วินาทีรองรับการแก้จากภายนอก การบันทึกจาก Editor/Submit refresh ความคืบหน้าทันที เมื่อ Context ลดเลขจะตั้ง checkpoint ใหม่และไม่สร้างกิจกรรมติดลบ

กิจกรรมรายวันอิงเวลาท้องถิ่นและเวลาที่ Context ถูกแก้ไฟล์ครั้งล่าสุด ไม่สามารถย้อนแยกวันทำงานหลายวันจากไฟล์ที่แก้ระหว่างปิดโปรแกรมได้ การตรวจครั้งแรกตั้งฐาน ไม่ได้นับทั้งนิยายเป็นผลงานวันนี้ เป้าหมาย **บทแปล** เดิมยังคงพฤติกรรมรอบอัตโนมัติ ส่วนเป้าหมาย **verified** ด้านล่าง reset ด้วยมือเท่านั้น

## TXT Export และ verified

Basic แสดง prefix, เลขถัดไป, วันนี้ส่งกี่ไฟล์, รอบส่งปัจจุบัน, Editor และ **Submit** ตั้งโฟลเดอร์ปลายทาง, เป้าหมาย และช่วงเลขได้ใน **Advanced** ค่าทั้งหมดแยกแต่ละโปรไฟล์ Draft ใน TXT Export ถูกเก็บเมื่อสลับ/ปิด Workspace หรืออัปเดต

**Submit** เขียน TXT และแทนที่ Context ด้วยข้อความเดียวกันใน UTF-8 เตรียมไฟล์ข้างปลายทาง, flush/fsync และ atomic replace ก่อนบันทึก export event หาก TXT, Context หรือการบันทึก event ล้มเหลว จะ rollback ไฟล์ที่เปลี่ยนแล้ว ไม่เพิ่ม count และไม่เลื่อนเลขชื่อไฟล์

การส่งออกผ่าน **คัดลอก + ส่งออก** ใน More นับเมื่อเขียน TXT สำเร็จ การคัดลอกอย่างเดียวไม่นับ

มีตัวนับสองชุดที่แยกกัน:

1. **Daily history** เก็บ profile, timestamp, filename/prefix, sequence และ success ของทุก export ที่สำเร็จ เก็บวันก่อนเพื่อใช้สถิติ
2. **Goal cycle** เช่น target 5 แสดง `1/5`, `5/5 ✓`, `12/5 ✓ · +7 เกินเป้า` เพิ่มได้ไม่จำกัด ไม่ reset เมื่อครบเป้า กด **Reset รอบส่ง** ใน More/Advanced เองเพื่อเริ่ม `0/5` รอบก่อนถูก archive และ daily history ไม่ถูกลบ การเปลี่ยน target ไม่ล้าง history หากไม่มี target แสดงจำนวนไฟล์อย่างเดียว

เลขชื่อไฟล์แยกจาก goal count ค่าเริ่มต้นคือ 1 Basic ที่ตั้ง goal 5 ใช้ `prefix1.txt` ถึง `prefix5.txt` แล้ววนกลับ 1 แม้ goal จะเป็น `6/5 ✓` โปรไฟล์เก่าที่ตั้ง start/end/current ไว้จะคงค่าเดิมและเลือกช่วง Advanced ให้ ใช้ช่วงเลข Advanced เพื่อกำหนดเอง หรือปิด override เพื่อใช้ 1..goal

## Auto Save และ Recovery

ไฟล์ Editor บันทึกอัตโนมัติหลังหยุดพิมพ์ 1 วินาที เขียน UTF-8 ผ่านไฟล์ชั่วคราวและ atomic replace หาก Windows lock ไฟล์จะรักษา dirty marker และลองใหม่

ก่อนแทนที่ Context หรือไฟล์ TXT ที่มีอยู่ โปรแกรมเก็บสำรองข้างเอกสารใน `.palantir-recovery` จำกัด **10 สำเนาต่อไฟล์** เปิดเอกสารนั้นแล้วเลือก **More → History / กู้ไฟล์** เพื่อคืนสำเนาเก่า การกู้จะสำรองเอกสารปัจจุบันก่อน ชื่อสำรองใช้ digest ของชื่อไฟล์เพื่อรองรับชื่อยาว

Rollback ครอบคลุมข้อผิดพลาดที่ตรวจพบระหว่าง Submit สำเนาสำรองยังใช้กู้หลังโปรแกรมหรือเครื่องหยุดกลางทางได้ ระบบนี้ไม่ได้เป็น distributed transaction ที่รับประกัน atomicity ข้ามหลายไฟล์เมื่อไฟดับ

## สถิติ

แสดงวันนี้/สัปดาห์นี้ของการแปล และ verified วันนี้ รายเรื่องแสดงเป้าหมายแปล, รอบส่ง verified และจำนวนเกินเป้า เปิดรายละเอียดรอบส่งก่อนหน้าได้ ประวัติ 7 วันและการตั้งเป้าหมายแปลรวมอยู่ในส่วนขยาย

## Update แบบ in-place

ในรุ่นที่ติดตั้งแล้ว: **โปรแกรม → ตรวจสอบอัปเดต → อัปเดตเลย** ดาวน์โหลดใน Palantir ตรวจ Release origin, size และ SHA-256 แล้วบันทึกเอกสาร, TXT Export draft, session และ settings ก่อนปิดโปรแกรม

Detached helper ตรวจ checksum ซ้ำ รอ Palantir ปิด และรัน Inno Setup ด้วย `/VERYSILENT /SP- /NORESTART /CLOSEAPPLICATIONS` พร้อม update marker และ install directory เดิม รอ exit code ก่อนเปิดโปรแกรมกลับ รุ่นใหม่แสดง **อัปเดตเป็น vX.Y.Z สำเร็จ ✓** หากผิดพลาดเปิดกลับพร้อม error และ path ของ `updates/installer.log` ภายใต้ data directory การติดตั้งแบบ silent ด้วยมือไม่เปิดโปรแกรมเอง

คง AppId **B93AE24C-43D9-4D38-A880-93A607EA8D41** และ UsePreviousAppDir/Tasks/Group ไม่เปลี่ยน `%LOCALAPPDATA%/NovelWorkflow` รุ่นก่อน 3.4.0 ยังใช้ updater เก่าในการอัปเกรดครั้งแรก จากนั้นการอัปเดตในโปรแกรมใช้ helper ใหม่นี้

## ดาวน์โหลด / Development / Release

ดาวน์โหลด `NovelWorkflow-Setup-<version>.exe` จาก [GitHub Releases](https://github.com/nastasiamql-arch/novel-translation-workflow-manager/releases) โปรแกรมรักษาข้อมูลเดิมที่ `%LOCALAPPDATA%/NovelWorkflow` migration schema 7 เป็น additive และเก็บ unknown legacy fields, Workflow, Context, session และช่วงเลข export เดิม

```powershell
py -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"
.venv/Scripts/python.exe -m novel_workflow.main
python -m pytest -q
python tests/ui_smoke.py
python tests/ui_geometry.py
.\build_windows.ps1
```

Build ใช้ Python 3.11+ และ Inno Setup 6 เวอร์ชันอ้างอิง `pyproject.toml` CI รัน unit/behavior tests, desktop smoke และ geometry ที่ DPI 1.0/1.25/1.5/2.0 ก่อน Windows build บน main commit ที่มี `[release]` จะสร้าง tag และ GitHub Release พร้อม installer เมื่อทุกขั้นผ่าน

โลโก้ N Monogram และไอคอนใช้ assets ใน `assets/brand/` และ `assets/palantir_novel.ico`
