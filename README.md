# Palantir: Novel

## Translation Planner / Today Dashboard

หน้า **วันนี้** ใช้วางแผนแบบเลือกเอง มีโหมดโฟกัสวันนี้, เป้าหมายรายวัน, แปลจนจบเรื่อง และวันพัก เลือกวันและนิยายได้ล่วงหน้าโดยไม่เปิดนิยายหรือคัดลอกอัตโนมัติ แผนเก็บใน `%LOCALAPPDATA%\NovelWorkflow\translation_planner.json` แยกจาก Profile และเก็บประวัติการแก้แผนเดิม

จำนวนบทของแผนมาจาก Translator Export ที่ Commit สำเร็จเท่านั้น ไม่รวม Clipboard, Save Editor, Context หรือ Verified TXT Export; Export บทเดิมไม่เพิ่มยอดซ้ำ แผนแปลจนจบใช้ชุดบทที่มีอยู่จริงเพื่อค้นหาบทขาด ไม่ถือว่าเลขสูงสุดแปลครบทุกบท และยืนยันจบเรื่องหรือยกเลิกการยืนยันเองได้ เป้าหมายที่ไม่รู้เลขบทสุดท้ายไม่สร้าง Progress Bar ปลอม

Library กรองตามกลุ่มเดิมได้ และ Cache ปกตามลายเซ็นไฟล์โดยไม่เปลี่ยนลำดับนิยายที่จัดไว้


## Version 4.0.0 — Translation workflow only

The website/Novel Downloader feature has been removed completely, including the
older per-profile downloader, TomatoMTL, Playwright browser control and login.
Original source files in `source/`, the `CURRENT_SOURCE_CHAPTER` dynamic reference,
chapter numbering, Translator, Context, TXT Export, ZIP copy, Polish History and the
GitHub application updater remain available.

**Existing user data is never erased by an application update.** If you previously
used Novel Downloader, quit Palantir: Novel and back up anything you need from
`%LOCALAPPDATA%\\NovelWorkflow\\downloader\\`, then remove that one obsolete
directory manually if you want its browser login session, cache and private book
library erased. Do not delete `profiles/`, `source/`, your chosen TXT output
directories, or the rest of `NovelWorkflow/`. Profile documents that contain
an old website binding are backed up once as `profile.json.pre-v4-upgrade.bak`
before the obsolete binding is removed on first profile load. Historic GitHub
tags/releases remain available for audit; v4 does not ship website downloading.

## Translator-based chapter start (v3.15.1)

เมื่อเปิดไฟล์ต้นฉบับจีนและกด **ตรวจเลขบท** โปรแกรมจะอ่านหัวบทล่าสุดจากไฟล์ Translator ที่ผูกกับนิยายเรื่องเดียวกัน แล้วเสนอเลขเริ่มต้นเป็น `บทล่าสุด + 1` ให้โดยอัตโนมัติ แสดงชื่อไฟล์อ้างอิงและเลขล่าสุดอย่างชัดเจน รองรับข้อความ Translator ที่แก้แล้วแต่ยังไม่บันทึก ถ้าไฟล์กำกวมหรือไม่พบข้อมูล ระบบจะไม่เดาและเปิดให้ใส่เลขเอง ทุกการแก้ต้นฉบับต้องยืนยันเช่นเดิม ไม่แก้ Translator/Context/Export

## Smart Chapter Numbering (v3.15.0)

เปิดไฟล์ต้นฉบับภาษาจีน เช่น `FATE.txt` (ชื่อไฟล์ของแต่ละเรื่องไม่จำกัด) ใน Editor แล้วกด **ตรวจเลขบท** บนแถบเครื่องมือ ระบบตรวจเฉพาะไฟล์ที่เปิดอยู่ ไม่อ่าน/แก้ Translator, Context หรือ TXT Export

หน้าต่างตรวจเลขบทแสดงเลขจากหัวบททุกบทและเตือนเลขกระโดด ซ้ำ หรือย้อนกลับ; **เรียงเลขต่อเนื่อง (เสนอ)** ใส่เลขเริ่มต้นเพื่อจัดลำดับเป็นชุด หรือแก้เลขทีละรายการได้ เมื่อกด **แก้ที่เลือก**/**แก้ทั้งหมด** ต้องยืนยัน Preview ก่อนเขียน โปรแกรมแก้เฉพาะอักขระที่เป็นหมายเลขหัวบท ไม่เปลี่ยนข้อความจีนของเนื้อเรื่อง โปรดตรวจว่าบทขาดจริงหรือเว็บพิมพ์เลขผิดก่อนกดยืนยัน เพราะข้อมูลภายในไฟล์เพียงอย่างเดียวไม่สามารถพิสูจน์ได้

ทุกการแก้เก็บ snapshot ข้อความก่อนแก้ไว้ในข้อมูลโปรไฟล์ และใช้ระบบ Save/External Conflict/Undo ปัจจุบัน ปุ่ม **ย้อนคืนการแก้ล่าสุด** ใช้ได้เมื่อไฟล์ยังตรงกับเวอร์ชันที่โปรแกรมแก้แล้ว ดู [รายละเอียด](docs/chapter-numbering.md)


## บทแปลเสร็จจาก Translator Export (v3.13.0)

**แปลเสร็จ = Export ในแท็บ Translator สำเร็จครบทุกขั้นตอนเท่านั้น** โปรแกรมตรวจ Snapshot ก่อน Export, TXT, Context, สถานะ Export และสถิติร่วมกัน แล้วนับหมายเลขบทที่ยืนยันได้จริงแบบไม่ซ้ำตลอดประวัติของนิยาย

บท 6–10 เพิ่ม 5 บท, บท 11–15 เพิ่มอีก 5 บท, Export บทเดิมซ้ำหรือแก้คำผิดไม่เพิ่มยอด บทเว้นช่วงนับเฉพาะหัวบทที่มีจริง ไม่เติมเลขที่หายไป รายวันใช้วันที่ท้องถิ่นเมื่อ Export สำเร็จ ส่วนรายสัปดาห์และเป้าหมายใช้ประวัติเดียวกัน เป้าหมายแสดงเกินเป้าได้ เช่น 7/5 และรีเซ็ตเฉพาะเมื่อกด Reset

Header แสดงยอดแบบ Compact โดยไม่มีบรรทัดส่งไฟล์ verified หากบทตั้งแต่ 1 ยังไม่ครบ จะแสดง **Export ล่าสุด: บท …** เพื่อไม่อ้างว่าทุกบทก่อนหน้าสำเร็จแล้ว เมื่อยังไม่มีประวัติยืนยันจะแสดง **ยังไม่มี Export ที่ยืนยัน · วันนี้ 0 บท**

ข้อมูลรายวันจาก Context รุ่นเก่ายังคงอยู่ และดูแยกได้ในหน้าสถิติ แต่ไม่รวมเป็นยอด Export ที่ยืนยันใหม่ ไม่มีการเดาหรือสร้าง Event ย้อนหลัง ระบบ TXT Export/Submit, Verified Counter/Goal/History และ Polish History ยังคงแยกตามเดิม

หากไม่มีหัวบทที่ตรวจสอบได้ การกรอกช่วงบทเพื่อจัดชื่อ Snapshot ไม่เพิ่มยอดสถิติ โปรแกรมแจ้งเหตุผลหลัง Export ดูรายละเอียดการเก็บประวัติและการกู้คืนได้ที่ [Translator completion](docs/translator-completion.md)

## Polish History & Recovery (v3.11.1)

ตั้งค่า **Novel → โฟลเดอร์หลัก** และ **Workflow → ประวัติไฟล์ขั้นตอนเกลา**
โดยเลือกขั้นตอนที่ต้องการจากรายการ โปรแกรมผูกการตั้งค่ากับ Step ID จึงเปลี่ยนชื่อ
หรือย้ายลำดับขั้นตอนได้ ขั้นตอนอื่นยังคัดลอกตามพฤติกรรมเดิม

คลิก **ปุ่มชื่อขั้นตอน** ตามปกติ: โปรแกรมบันทึกเอกสารที่แก้ไขอยู่ แล้วสำรองเฉพาะ
ไฟล์ที่ผูกกับขั้นตอนนั้น รวม Disabled, Dynamic Reference, External File และไฟล์ในโฟลเดอร์แนบ
Context จะถูกเก็บเมื่อผู้ใช้ผูก Context กับขั้นตอนนั้นเอง ก่อนคัดลอกสำเนาที่ตรวจสอบแล้วไปยัง Windows Clipboard
ไม่มีการรวมข้อความหรือเปลี่ยน encoding/BOM/ช่องว่างของไฟล์สำรอง

ช่วงบทอ่านเฉพาะหัวบทในไฟล์เนื้อหาที่ระบุได้ชัดเจน (ไทย/อังกฤษ/จีนตามตัวอ่านเดิม)
ไม่อ่านเลขบทล่าสุดจาก Context ถ้ายืนยันไม่ได้ ให้กรอกช่อง **ช่วงบท เช่น 6-10**
แล้วคลิกขั้นตอนอีกครั้ง ช่องนี้ใช้สำหรับประวัติใหม่และล้างหลังบันทึกสำเร็จ
ไม่มีจำนวนบทต่อรอบหรือจำนวนบทสูงสุดที่กำหนดตายตัว

กด **บันทึกไว้รอตรวจ** เพื่อเก็บ Snapshot ของขั้นตอนตรวจคำแปลโดยไม่เริ่ม Workflow
หรือรอให้ TXT Export สำเร็จเพื่อบันทึกอัตโนมัติ ทั้งสองแบบไม่คัดลอกไฟล์และไม่เพิ่ม Export ซ้ำ
ประวัติเริ่มด้วยสถานะ **รอตรวจ** และเปลี่ยนเป็น **ตรวจแล้ว** ได้จากเมนูรายการ
กด **ประวัติ** ใน Workspace เพื่อเปิดหน้าเต็ม เลือกช่วงบทแล้วกด **คัดลอก** ได้ทันที
ใช้ Snapshot เดิมเสมอ โดยไม่เขียนทับ Context จริง ไม่เลื่อนขั้นตอน
หรือยอด Export กลับด้วย **← กลับไปทำงาน** เพื่อใช้แท็บเดิมต่อได้
เปิด ZIP setting เดิมเพื่อคัดลอก ZIP 1 ไฟล์ หรือปิดเพื่อคัดลอกหลายไฟล์
จำนวนที่แสดงคือไฟล์ Payload จริง ไม่รวม manifest หรือ ZIP

ตั้งแต่ v3.11.0 ประวัติอยู่ใน `<Main Folder>/Polish History/<ชื่อขั้นตอน> บท <ช่วงบท>/`
เช่น `Polish History/ตรวจคำแปล บท 6-10/` ไม่มีโฟลเดอร์รหัสซ้อนหรือ UUID ในชื่อประวัติ
หากช่วงเดิมมีเนื้อหาใหม่ จะต่อวันเวลาและลำดับเมื่อชื่อชนกัน ส่วนโปรไฟล์ที่ใช้โฟลเดอร์ร่วมกัน
ใช้ชื่อโปรไฟล์ต่อท้ายเมื่อจำเป็น โดย Step ID และ Profile ID ยังคงอยู่ใน Manifest
ประวัติจาก v3.10.0 และ v3.10.1 ยังใช้ได้ และจะย้ายหลังตรวจไฟล์/Hash เมื่อเปิด History หรือ Refresh
ถ้า Clipboard ยังอ้าง Path เก่า โปรแกรมจะคงตำแหน่งเดิมพร้อมแจ้งสถานะก่อน
พร้อมไฟล์ Payload และ `manifest.json`
ไฟล์ชื่อซ้ำแยกตามไฟล์แนบโดยรักษาชื่อเดิมใน Metadata โปรแกรมไม่ลบประวัติเก่าอัตโนมัติ
ประวัติที่ไม่ครบหรือ hash ผิดจะแสดงข้อผิดพลาดและไม่อนุญาตคัดลอกทั้งชุด
เมนู **⋯** ใช้แก้ช่วงบท เปิดโฟลเดอร์ ตรวจไฟล์ หรือลบพร้อมยืนยัน
หาก Clipboard ยังอ้างไฟล์ชุดนั้น ให้คัดลอกชุดอื่นก่อนลบ ย้าย หรือแก้ชื่อช่วงบท

ดู [รายละเอียดการจัดเก็บและตรวจสอบ](docs/polish-history.md)

เมื่อกด **Export** จากแท็บ Translator โปรแกรมจะยืนยันรายการก่อน จากนั้นสำรองไฟล์
ที่ผูกอยู่กับขั้นตอนตรวจคำแปลและตรวจ Hash ให้ครบก่อนสร้าง TXT หรือเขียนทับ Context
ไฟล์ Context จะอยู่ใน Snapshot เฉพาะเมื่อผู้ใช้แนบ Context ไว้กับขั้นตอนนี้เอง
ช่วงบทมาจากหัวบทใน Translator; หากอ่านไม่ได้ โปรแกรมขอให้ยืนยันช่วงบทก่อนดำเนินการ
การยกเลิกหรือสำรองไม่สำเร็จจะไม่สร้าง TXT และไม่เปลี่ยน Context

### ข้อกำหนด Editor (v3.6.9)

เนื้อหานิยายทุกหน้าใช้กฎเดียวกัน: ลบเฉพาะบรรทัด `""` โดยเก็บ Space,
Tab, NBSP และอักขระทั้งหมด ไม่รวมสองบรรทัด คำศัพท์ TSV รวมถึงไฟล์ TXT
ต้องรักษา Tab และคอลัมน์ว่างครบ หากคอลัมน์ไม่ครบจะแจ้งในแถบสถานะโดยไม่แก้ข้อมูล
ทุกไฟล์ TXT/MD ที่เปิดใน Editor จัดบรรทัดทันทีตอนเปิดและ Paste ไม่จำกัดชื่อหรือโฟลเดอร์ เช่น FDR.txt และ FDRContext.md ไม่แตะไฟล์ที่ไม่ได้เปิด และเปิดอย่างเดียวไม่เขียนทับ Disk;
Save/AutoSave บันทึกข้อความตรงกับ Editor และรักษา Undo, Recovery และ External Conflict
ห้ามเปลี่ยน Text Normalization/Clipboard/Paste/Save/TSV โดยไม่มีคำสั่งโดยตรง
และต้องผ่าน Regression Tests ก่อน Release ดู [Editor contract](docs/editor-contract.md)

โปรแกรมเดสก์ท็อป Windows สำหรับจัดไฟล์และขั้นตอนงานแปลนิยาย ผู้ใช้เลือกขั้นตอนและทำงานแปลเอง โปรแกรมช่วย COPY STEP, แก้เอกสาร, จำ Context และติดตามการส่งงาน ไม่มี AI translation API และไม่มีระบบตัดสินสถานะรายบทอัตโนมัติ

## การใช้งาน

Editor ของไฟล์ TXT/MD ที่เปิดอยู่, Clipboard, Draft และ TXT Export ลบเฉพาะบรรทัดที่ไม่มีอักขระเลย เก็บช่องว่าง Tab และ NBSP ครบ ไฟล์ UTF-8 อ่านแบบ Strict เพื่อไม่แทนอักขระที่อ่านไม่ได้ AutoSave และ Ctrl+S ตรวจเนื้อหา Disk ก่อนเขียนทับ ถ้าพบ Conflict จะเก็บข้อความที่ยังไม่บันทึกใน Recovery และแจ้งสถานะ คลิกขวาที่แท็บเพื่ออ่าน Disk ใหม่หรือกู้คืนข้อความ โดยไฟล์ที่เปิดและไม่ได้แก้ไขจะไม่ถูกเขียนใหม่

Navigation อยู่ด้านซ้าย: **คลังนิยาย / กำลังทำงาน / สถิติ / กลุ่ม / ตั้งค่า** แสดงไอคอนเสมอ พร้อม tooltip ชื่อเมนูและรองรับแป้นพิมพ์ โปรแกรมจำหน้าที่เลือกไว้ แต่ละเรื่องมี Workspace ของตัวเอง สลับนิยายผ่านคลังนิยาย โดยไม่แสดงแถบปกนิยายซ้ำใน Workspace

- Novel Header เหนือ Editor แสดง **แปลถึงบท …**, จำนวนบทที่เพิ่มวันนี้ และแถบเป้าหมายการแปลแยกตามเรื่อง (`6/10 บท · 60%`, ครบแล้วหรือเกินเป้า) พร้อมปุ่ม **แก้เป้า / ตั้งเป้า** และ **รีเซ็ต** โดยตรง ค่าจะอัปเดตหลัง Translator Export ที่สำเร็จ และไม่ปนกับ Verified goal
- Workflow หลักเริ่มด้วย **แปล / ตรวจคำแปล** และรองรับขั้นตอน custom เดิม
- **หาศัพท์** เป็นเครื่องมือเตรียมไฟล์แยกจาก Workflow หลัก ใช้ vocabulary_step และ COPY STEP เดิม ไม่มีการเรียก API
- หมวดนิยายคง **กำลังแปล / พักแปล / ชนต้นฉบับแล้ว / กำลังเช็กกับเว็บ** คำสั่งอยู่ใน More ของ Editor หลังเปลี่ยนสถานะมี toast **ย้อนกลับ** คืนสถานะก่อนหน้า
- Settings จัดการโปรไฟล์, ไฟล์ทำงาน, Context, Workflow และรายการ Launcher ส่วน Groups ใช้จัดกลุ่มนิยาย โดย Workspace ทำงานทีละเรื่อง

## Editor และแท็บ

เอกสารอยู่ในแท็บแถวเดียว เลื่อนเมื่อพื้นที่ไม่พอ ลากเรียงไฟล์ได้ ชื่อยาวย่อพร้อม tooltip ชื่อเต็ม และเอกสารที่ยังไม่บันทึกมี **●** โปรแกรมบันทึกโปรไฟล์ แท็บที่เปิด แท็บที่เลือก ลำดับ และตำแหน่งอ่านทันทีหลังเปลี่ยนแปลงเล็กน้อย แล้วคืนหน้าทำงานล่าสุดเมื่อเปิดโปรแกรมใหม่

**TXT Export** เป็นแท็บถาวรขวาสุด ปิดไม่ได้ ไฟล์ใหม่แทรกก่อนแท็บนี้ แถบเครื่องมือ Editor มี Undo, Redo, ค้นหา และขนาดตัวอักษร คำสั่งรองอยู่ใน **More (...)** และใช้เมนูเมื่อพื้นที่แคบ

Editor ใช้ **Segoe UI** เป็นฟอนต์หลักขนาดเริ่มต้น 11 pt หากไม่มีใช้ฟอนต์ทั่วไปของระบบ Qt ใช้ fallback ภาษาไทย/จีน/ญี่ปุ่นจากฟอนต์ที่ติดตั้งใน Windows ส่วน UI ใช้ Segoe UI พร้อม Leelawadee UI/Tahoma fallback ไม่ฝัง Apple SF font

Light ใช้พื้นขาว–เทาอ่อนแบบเรียบ พร้อม Dark โทนเทาที่สอดคล้องกัน ไอคอน navigation เป็นเส้นชุดเดียวกัน ปุ่มหลักใช้สีเข้ม/อ่อนที่ตัดกับพื้นหลัง แยก hover และรายการที่เลือกสีเทาจาก text selection สีฟ้าและ current line ไม่แสดงกรอบเมื่อคลิกเมาส์ แต่คงตัวบ่งชี้ keyboard focus สีเทาเมื่อใช้แป้นพิมพ์ การตั้งค่าใหม่เริ่ม Light ส่วนโปรไฟล์เดิมรักษาธีมที่เคยเลือกไว้

จัดอันดับนิยายได้ทั้ง **คลังนิยาย** และ **ตั้งค่า → นิยายของฉัน** โดยกดที่ชื่อหรือปกแล้วลากได้ทันทีแบบ Desktop มีภาพรายการตามเมาส์และตำแหน่งวาง คลิกแล้วปล่อยเพื่อเปิดรายละเอียด ใช้แป้นพิมพ์เลือกหรือปุ่มเลื่อนขึ้น/ลงได้ โปรแกรมบันทึกลำดับหลังวางและคงลำดับนั้นเมื่อบันทึกนิยายต่อ

หน้าตั้งค่าแสดงรายการขั้นตอน/ไฟล์แนบสูงตามขนาดข้อความ ไม่ตัดไฟล์ 6 แถวด้วยความสูงคงที่ แสดงได้ถึง 8 แถวเต็มก่อนใช้แถบเลื่อน และเว้นระยะจากแถวปุ่ม

แถบเลื่อนใช้รางสีเรียบ ไม่มีลายจุด และตัวลากที่ตัดกับรางชัดเจนทั้ง Light/Dark พร้อม hover/pressed state

Status bar ใช้สำหรับเอกสาร: สถานะบันทึก, คำ/อักขระ, Ln/Col และ UTF-8 ข้อความยาวย่อพร้อม tooltip

รายการไฟล์ใน Workspace, ไฟล์แนบ, ไฟล์ทำงาน, รายการเปิดพร้อมเรื่อง, จัดการไฟล์ และต้นไม้ไฟล์รองรับ **Ctrl+คลิก / Shift+คลิก / Ctrl+A** เลือกหลายรายการ ปุ่มเอาออก/เลื่อนลำดับใช้กับไฟล์แนบทั้งกลุ่ม ปุ่มเปิด/เอาออกใช้กับไฟล์ทำงานทั้งกลุ่ม ส่วนจัดการไฟล์เปิด/แนบ/ลบหลายไฟล์ได้ โดยลบจริงยังยืนยันก่อน เปลี่ยนชื่อใช้ทีละไฟล์

การลากปกแสดงเส้นตำแหน่งวาง เลือกช่องที่ใกล้ที่สุดเมื่ออยู่ระหว่างปก และเลื่อนรายการต่อเนื่องเมื่อเมาส์ชิดขอบ เมื่อยกเลิกลำดับเดิมยังอยู่ โดยไม่แสดง tooltip ลอยเมื่อชี้เมาส์ งานอ่าน progress จะรอจนลากเสร็จเพื่อรักษาการตอบสนอง

หลังอัปเดตในโปรแกรม ตัวช่วยจะเปิด Palantir กลับมาในหน้าต่างปกติอัตโนมัติ

ซ่อนแถบชื่อโปรแกรมที่ซ้ำบนทุกหน้า ใช้แถบชื่อหน้าต่าง Windows และเมนูโปรแกรมสำหรับตรวจสอบอัปเดต ช่องเขียน TXT Export ขยายชิดขอบพื้นที่ทำงาน ปุ่มและข้อมูลยังมีระยะเผื่ออ่านง่าย

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

กิจกรรมรายวันอิงวันที่ท้องถิ่นของ Translator Export ที่สำเร็จ การแก้ Context, Save, AutoSave และ TXT Submit ไม่เพิ่มยอดนี้ ข้อมูล Context รุ่นเก่าคงไว้แยกต่างหาก เป้าหมาย **บทแปล** และ **verified** ต่างรีเซ็ตด้วยมือ โดยใช้ประวัติคนละระบบ

## TXT Export และ verified

Basic แสดง prefix, เลขถัดไป, วันนี้ส่งกี่ไฟล์, รอบส่งปัจจุบัน, Editor และ **Submit** ตั้งโฟลเดอร์ปลายทาง, เป้าหมาย และช่วงเลขได้ใน **Advanced** ค่าทั้งหมดแยกแต่ละโปรไฟล์ Draft ใน TXT Export ถูกเก็บเมื่อสลับ/ปิด Workspace หรืออัปเดต

**Submit** เขียน TXT และแทนที่ Context ด้วยข้อความเดียวกันใน UTF-8 เตรียมไฟล์ข้างปลายทาง, flush/fsync และ atomic replace ก่อนบันทึก export event หาก TXT, Context หรือการบันทึก event ล้มเหลว จะ rollback ไฟล์ที่เปลี่ยนแล้ว ไม่เพิ่ม count และไม่เลื่อนเลขชื่อไฟล์

การส่งออกผ่าน **คัดลอก + ส่งออก** ใน More นับเมื่อเขียน TXT สำเร็จ การคัดลอกอย่างเดียวไม่นับ

มีตัวนับสองชุดที่แยกกัน:

1. **Daily history** เก็บ profile, timestamp, filename/prefix, sequence และ success ของทุก export ที่สำเร็จ เก็บวันก่อนเพื่อใช้สถิติ
2. **Goal cycle** เช่น target 5 แสดง `1/5`, `5/5 ✓`, `12/5 ✓ · +7 เกินเป้า` เพิ่มได้ไม่จำกัด ไม่ reset เมื่อครบเป้า กด **Reset รอบส่ง** ใน More/Advanced เองเพื่อเริ่ม `0/5` รอบก่อนถูก archive และ daily history ไม่ถูกลบ การเปลี่ยน target ไม่ล้าง history หากไม่มี target แสดงจำนวนไฟล์อย่างเดียว

เลขชื่อไฟล์แยกจาก goal count ค่าเริ่มต้นคือ 1 Basic ที่ตั้ง goal 5 ใช้ `prefix1.txt` ถึง `prefix5.txt` แล้ววนกลับ 1 แม้ goal จะเป็น `6/5 ✓` โปรไฟล์เก่าที่ตั้ง start/end/current ไว้จะคงค่าเดิมและเลือกช่วง Advanced ให้ ใช้ช่วงเลข Advanced เพื่อกำหนดเอง หรือปิด override เพื่อใช้ 1..goal

## Auto Save และ Recovery

ไฟล์ Editor บันทึกอัตโนมัติหลังหยุดพิมพ์ 1 วินาที เขียน UTF-8 ผ่านไฟล์ staging ในโฟลเดอร์ซ่อนเฉพาะกิจข้างไฟล์ แล้ว atomic replace จึงไม่ทิ้งไฟล์ `.part` ให้เห็นบน Desktop/โฟลเดอร์งานตามปกติ หาก Windows lock ไฟล์จะรักษา dirty marker และลองใหม่

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

รุ่น 3.4.2 ฝัง version จาก pyproject.toml มากับ executable และลบเฉพาะ metadata ของ NovelWorkflow รุ่นเก่าที่ค้างใน installation เพื่อป้องกันการแจ้ง version mismatch หลังอัปเดตสำเร็จ Updater ตรวจรุ่นและ runtime ของ executable หลัง Setup จบก่อนรายงานสำเร็จ CI ทดสอบ silent installation ซ้ำใน directory เดิมพร้อม stale metadata และข้อมูลผู้ใช้จำลอง

Context ที่ไม่เปลี่ยนใช้ผลบทล่าสุดที่จำไว้ในหน่วยความจำ ตรวจขนาด เวลาแก้ไข และตัวไฟล์ก่อนใช้ผลเดิม ไม่เก็บเนื้อหาเอกสารทั้งไฟล์ใน cache และยังตรวจการแก้จากภายนอกตามเดิม

## 3.6.0 — White Minimal, ZIP และต้นฉบับเว็บ

ตั้งค่าแยก 7 หมวด: General, Novel, Workflow, Workflow Files, Working Tabs, TXT Export และ Program Updates ใช้ชุดสี White Minimal / น้ำเงินอ่อน พร้อมลูกศร SpinBox ที่เห็นและกดได้ชัดเจนทั้ง Light และ Dark

General → **คัดลอกไฟล์เป็น ZIP** เริ่มต้นปิด เมื่อเปิด COPY STEP และการคลิกขั้นตอนจะสร้าง ZIP เดียว รวมไฟล์ Enabled/Disabled โดยรักษา Binary, Unicode และโฟลเดอร์ย่อย คลิกขวาที่ขั้นตอนเพื่อเลือกหลายขั้นตอนใน ZIP เดียว ไม่มีปุ่ม ZIP เพิ่มบน Workspace โหมดปิดยังคัดลอกไฟล์ Enabled ตามเดิม TXT Export คัดลอกข้อความเสมอ

ZIP ที่เผยแพร่เข้า Clipboard เก็บใน `%LOCALAPPDATA%/NovelWorkflow/cache/clipboard` และไม่ลบอัตโนมัติ เพื่อให้ Paste ได้หลังปิดโปรแกรม ผู้ใช้ลบแคชด้วยตัวเองเมื่อเลิกใช้อ้างอิงเหล่านั้น ZIP ที่สร้างไม่สำเร็จถูกลบทิ้ง และ Missing Files, Collision, Symbolic Link/Junction หรือไฟล์ที่เปลี่ยนระหว่างสร้างจะเป็นข้อผิดพลาด

Context ใช้ Chapter Progress/ความคืบหน้าส่วนท้ายเมื่อมีหมวดชัดเจน และหยุดที่หมวดถัดไป ในเอกสารเก่าใช้หัวข้อบทที่ถูกต้องรายการสุดท้ายแทนเลขสูงสุดจากตัวอย่าง รองรับไทย/อังกฤษ/จีนและช่วงบท ยอด Verified เกินเป้าหมายและประวัติรอบส่งยังคงใช้ระบบเดิม

CI ทดสอบ Windows CF_HDROP ซึ่ง Windows Explorer ใช้รับไฟล์ Clipboard และติดตั้ง Installer v3.6.8 ที่เผยแพร่จริงก่อนอัปเกรดเป็นรุ่นใหม่โดยไม่ระบุ /DIR รอบที่สอง ตรวจ SHA-256, executable, shortcut, metadata และข้อมูลที่เก็บไว้

เปิดทำงานทีละเรื่องจากคลังนิยาย เลือกเรื่องใหม่แล้วบันทึกและปิด Workspace เดิม หากบันทึกไม่สำเร็จจะยังไม่สลับเรื่อง ทุกเรื่องยังอยู่ในคลัง และจำแท็บไฟล์ Cursor/Scroll, ขั้นตอนแปลหรือหาศัพท์ และ Draft แยกกัน เปิดโปรแกรมใหม่คืนเฉพาะเรื่องล่าสุด หัว Editor แสดงปกขนาดเล็กข้างชื่อเรื่องและความคืบหน้า โดยแท็บไฟล์ในเรื่องยังเปิดได้หลายไฟล์


### แปลหลายบท (Translation Batch Workflow)

ใน Novel Workspace กด **แปลหลายบท** โดยไม่ต้องเปลี่ยนขั้นตอนแปล เลือกวิธีนำเข้าต้นฉบับ: วางเนื้อหาเอง, ไฟล์ TXT รวม, โฟลเดอร์ TXT รายบท หรือไฟล์ที่เปิดใช้งานในขั้นตอนแปลเดิม แล้วกด **ตรวจต้นฉบับ / รีเฟรช** ระบบจัดกลุ่มด้วยเลขบทจริง ขนาดชุด 1–100 บท และค้นหาช่วงเช่น `6-10` ได้ คลิก **คัดลอก** ของชุดใดก็ได้ซ้ำกี่ครั้งก็ได้ การคัดลอกสร้างไฟล์ใน cache สำหรับ Windows Clipboard โดยไม่แก้ต้นฉบับ, Translator, Context หรือประวัติตรวจคำแปล โหมด ZIP กับไฟล์ปกติเป็นการตั้งค่าเฉพาะนิยาย แยกจากระบบหาศัพท์และ COPY STEP เดิม เมื่อไฟล์เปลี่ยนจาก Preview ให้รีเฟรชก่อนคัดลอกอีกครั้ง


## Novel File Inspector (ตรวจสอบไฟล์นิยาย)

The standalone **ตรวจสอบไฟล์นิยาย** item in the main navigation scans TXT chapter folders, ZIP archives and a chosen source folder for an existing novel. Review missing or duplicate chapter numbers, short chapters (default 1,500 non-whitespace characters), suspicious file sizes and duplicate content. Read full chapters in a read-only pane and choose keep, exclude or undecided per chapter. Preview numeric renumbering before writing files; creating separate output is the default. In-place changes require an explicit confirmation and write immutable backups with a separate restore option. Translator stages, copy workflows and export histories are unchanged.

## Context-based retranslation (v5.8.0)

เปิดนิยายและบันทึกไฟล์ Context ก่อน จากนั้นใช้เมนู `...` → **ตรวจ Context และเริ่มแปลใหม่** โปรแกรมจะอ่านหัวบทในส่วนเนื้อหานิยายของ Context (ไม่ใช้หัวบทตัวอย่างใน Glossary) และเสนอเริ่มแปลที่บทถัดไป หากเลขบทกำกวมต้องระบุด้วยตนเอง ก่อนยืนยันจะแสดงจำนวนบทที่ยังนับว่า Export เสร็จและจะถูกคืนเป็นรอแปลใหม่

การยืนยันเปลี่ยนเฉพาะ **การนับความคืบหน้า** ไม่แก้ต้นฉบับ Translator, Context, Export TXT หรือ Backup เดิม ประวัติ Export ถูกเก็บครบพร้อมบันทึกเหตุการณ์ย้อนแปลครั้งนั้น หลังแปลและ Export ใหม่ โปรแกรมจะนับเฉพาะบทที่เสร็จใหม่ สามารถคืนสถานะผ่าน `...` → **คืนสถานะย้อนแปล** โดยต้องยืนยันอีกครั้ง

การคัดลอกไฟล์ Glossary/Style/Prompt/Context ไม่จำเป็นต้องมี Translator ที่จับคู่เพื่อเข้าสู่ระบบตรวจเลขบทจีน การเลือกไฟล์และจำนวนไฟล์ของแต่ละขั้นตอนยังคงเป็นไปตามการตั้งค่าเดิม
