from pathlib import Path
from dataclasses import asdict as asdict_target
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, QMimeData
from PySide6.QtGui import QAction, QKeySequence, QIcon, QPixmap
from PySide6.QtWidgets import *
from .models import AppSettings, LaunchTarget, NovelGroup, StepFile, Workflow, migrate_legacy_basic_workflow
from .services import ProfileService, WorkflowService, AssemblyService
from .launcher import LauncherService
from .storage import ProjectRepository
from .translation_progress import latest_context_chapter, sync_profile_context, daily_chapter_count, goal_progress
from .progress_dialog import TranslationDashboardDialog
from .chapter_renamer import ChapterRenameDialog
from .theme import application_stylesheet

class Editor(QDialog):
    def __init__(self,parent,title,text=""):
        super().__init__(parent);self.setWindowTitle(title);self.resize(760,560);lay=QVBoxLayout(self)
        self.edit=QTextEdit();self.edit.setPlainText(text);lay.addWidget(self.edit)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);lay.addWidget(buttons)
        self.edit.addAction(QAction(self.edit,shortcut=QKeySequence.Save,triggered=self.accept))
    def text(self):return self.edit.toPlainText()

class MainWindow(QMainWindow):
    def __init__(self,repo=None):
        super().__init__()
        self.repo=repo or ProjectRepository()
        self.ps=ProfileService(self.repo)
        self.assembler=AssemblyService(self.repo)
        self.launcher=LauncherService()
        self.settings=self.repo.load_settings()
        self.profile=None
        self.si=-1
        self.dashboard_dialog=None
        self.setWindowTitle("NovelWorkflow")
        self.setMinimumSize(900,600)
        self.resize(1260,780)
        logo=Path(__file__).resolve().parent/"resources"/"novelworkflow.png"
        if logo.is_file(): self.setWindowIcon(QIcon(str(logo)))
        self.apply_theme()
        self.build()
        self.refresh_profiles()

    @staticmethod
    def theme_stylesheet(appearance="Dark"):
        return application_stylesheet(appearance)
    def apply_theme(self):
        app=QApplication.instance()
        if app:
            app.setStyleSheet(application_stylesheet(self.settings.appearance))

    def build(self):
        bar=self.addToolBar("Main")
        bar.setObjectName("mainToolbar")
        bar.setMovable(False)
        bar.setIconSize(QSize(30,30))
        logo=Path(__file__).resolve().parent/"resources"/"novelworkflow.png"
        mark=QLabel()
        if logo.is_file(): mark.setPixmap(QPixmap(str(logo)).scaled(30,30,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        bar.addWidget(mark)
        brand=QLabel("<b>NovelWorkflow</b>")
        brand.setObjectName("brandTitle")
        bar.addWidget(brand)
        spacer=QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        bar.addWidget(spacer)
        for label,fn in (("เปิดนิยาย",self.launch_profile),("กลุ่มนิยาย",self.groups_dialog),("นำเข้าข้อมูลเดิม",self.import_launcher_config),("ความคืบหน้า",self.translation_dashboard),("ตั้งค่า",self.settings_dialog)):
            a=QAction(label,self);a.triggered.connect(fn);bar.addAction(a)

        root=QWidget()
        root_layout=QVBoxLayout(root)
        root_layout.setContentsMargins(8,8,8,8)
        root_layout.setSpacing(8)
        self.novel=QLabel("ยังไม่ได้เลือกนิยาย")
        self.novel.setObjectName("currentNovel")
        self.novel.setWordWrap(True)
        self.novel.setMinimumHeight(62)
        self.novel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum)
        root_layout.addWidget(self.novel)
        splitter=QSplitter()
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter,1)
        self.setCentralWidget(root)
        self.profiles=QListWidget()
        self.profiles.setSpacing(1)
        self.profiles.setCursor(Qt.PointingHandCursor)
        self.profiles.setAccessibleName("รายการนิยาย")
        self.profiles.currentRowChanged.connect(self.select_profile)
        splitter.addWidget(self.column("นิยายของฉัน",self.profiles,[]))
        self.steps=QListWidget()
        self.steps.setSpacing(1)
        self.steps.setMinimumHeight(164)
        self.steps.setCursor(Qt.PointingHandCursor)
        self.steps.setAccessibleName("ขั้นตอนงาน")
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.currentRowChanged.connect(self.select_step)
        self.goal_panel=QFrame()
        self.goal_panel.setObjectName("goalPanel")
        goal_layout=QVBoxLayout(self.goal_panel)
        goal_layout.setContentsMargins(10,7,10,7)
        goal_layout.setSpacing(4)
        self.goal_label=QLabel("เป้าหมายวันนี้")
        self.goal_bar=QProgressBar()
        self.goal_bar.setFixedHeight(15)
        self.latest_chapter_label=QLabel("บทล่าสุดจากไฟล์ Context")
        self.latest_chapter_label.setObjectName("mutedLabel")
        goal_layout.addWidget(self.goal_label)
        goal_layout.addWidget(self.goal_bar)
        goal_layout.addWidget(self.latest_chapter_label)
        splitter.addWidget(self.column("ขั้นตอนงาน",self.steps,[],below=self.goal_panel))
        self.files=QListWidget()
        self.files.setSpacing(1)
        self.files.setCursor(Qt.PointingHandCursor)
        self.files.setAccessibleName("ไฟล์ของขั้นตอน")
        self.files.itemChanged.connect(self.toggle_file)
        splitter.addWidget(self.column("ไฟล์ของขั้นตอน",self.files,[("จัดเลขบท 4 หลัก",self.rename_chapter_files),("COPY STEP",self.copy_step)]))
        splitter.setSizes([260,340,650])
        self.statusBar().showMessage("เลือกนิยายและขั้นตอนเพื่อเริ่มทำงาน")
        self.shortcut("Ctrl+Shift+C",self.copy_step)
        self.shortcut("Ctrl+P",self.preview)
        self.shortcut("Ctrl+R",self.refresh)
        self.shortcut("Ctrl+S",self.save)
        self.progress_timer=QTimer(self)
        self.progress_timer.setInterval(10000)
        self.progress_timer.timeout.connect(self.refresh_translation_progress)
        self.progress_timer.start()

    def column(self,title,widget,buttons,below=None):
        panel=QFrame()
        panel.setObjectName("columnPanel")
        layout=QVBoxLayout(panel)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)
        heading=QLabel(title.upper())
        heading.setObjectName("sectionHeading")
        layout.addWidget(heading)
        layout.addWidget(widget,1)
        if below is not None:
            layout.addWidget(below)
        actions=QGridLayout()
        actions.setHorizontalSpacing(7)
        actions.setVerticalSpacing(7)
        regular=[entry for entry in buttons if entry[0] not in ("COPY FILES","COPY STEP")]
        for index,(label,fn) in enumerate(regular):
            button=QPushButton(label)
            button.setMinimumHeight(32)
            button.clicked.connect(fn)
            actions.addWidget(button,index//2,index%2)
        for label,fn in buttons:
            if label in ("COPY FILES","COPY STEP"):
                button=QPushButton(label)
                button.setObjectName("primaryButton")
                button.setMinimumHeight(40)
                button.clicked.connect(fn)
                actions.addWidget(button,(len(regular)+1)//2,0,1,2)
        layout.addLayout(actions)
        return panel

    def shortcut(self,key,fn):a=QAction(self);a.setShortcut(QKeySequence(key));a.triggered.connect(fn);self.addAction(a)
    def refresh(self):self.refresh_profiles(self.profile.id if self.profile else None)
    def refresh_profiles(self,pid=None):
        self.ps_list=self.repo.list_profiles()
        for profile in self.ps_list:
            changed=migrate_legacy_basic_workflow(profile.workflow)
            if sync_profile_context(profile):changed=True
            if changed:self.repo.save_profile(profile)
        self.profiles.blockSignals(True)
        self.profiles.clear()
        self.profiles.setIconSize(QSize(52,68))
        placeholder=Path(__file__).resolve().parent/"resources"/"novelworkflow.png"
        for profile in self.ps_list:
            item=QListWidgetItem(profile.name)
            item.setToolTip(profile.name)
            item.setSizeHint(QSize(0,70))
            cover=placeholder
            if profile.cover_image_path:
                try:
                    candidate=self.repo.resolve_project_path(profile.id,profile.cover_image_path)
                    if candidate.is_file():cover=candidate
                except ValueError:
                    pass
            if cover.is_file():item.setIcon(QIcon(str(cover)))
            item.setSizeHint(QSize(220,76))
            self.profiles.addItem(item)
        if not self.ps_list:
            empty=QListWidgetItem("ยังไม่มีนิยาย\nเพิ่มนิยายได้ที่ ตั้งค่า → นิยาย")
            empty.setFlags(Qt.NoItemFlags)
            empty.setTextAlignment(Qt.AlignCenter)
            self.profiles.addItem(empty)
        idx=next((i for i,p in enumerate(self.ps_list) if p.id==(pid or (self.settings.last_profile_id if self.settings.open_last_profile else None))),0 if self.ps_list else -1)
        self.profiles.setCurrentRow(idx)
        self.profiles.blockSignals(False)
        if idx>=0:self.select_profile(idx)
        else:self.profile=None;self.novel.setText("ยังไม่ได้เลือกนิยาย");self.refresh_steps()
    def refresh_translation_progress(self):
        profiles=getattr(self,"ps_list",[])
        for profile in profiles:
            if sync_profile_context(profile):self.repo.save_profile(profile)
        if self.profile:
            self.profile=next((profile for profile in profiles if profile.id==self.profile.id),self.profile)
        dashboard=getattr(self,"dashboard_dialog",None)
        if dashboard is not None and dashboard.isVisible():dashboard.set_profiles(profiles)
        self.refresh_goal_indicator()
        return profiles
    def refresh_goal_indicator(self):
        if not hasattr(self,"goal_label"):
            return
        if not self.profile:
            self.goal_label.setText("ยังไม่ได้เลือกนิยาย")
            self.goal_bar.setRange(0,100)
            self.goal_bar.setValue(0)
            self.latest_chapter_label.setText("เลือกนิยายเพื่อดูบทล่าสุดจาก Context")
            return
        today=daily_chapter_count(self.profile)
        latest=None
        if self.profile.context_path:
            try:
                context=Path(self.profile.context_path).expanduser()
                if context.is_file():
                    latest=latest_context_chapter(context.read_text(encoding="utf-8-sig",errors="replace"))
            except OSError:
                latest=None
        self.latest_chapter_label.setText(
            f"นิยายนี้แปลถึงบท {latest} แล้ว · จากไฟล์ Context" if latest is not None
            else "ยังอ่านบทล่าสุดจากไฟล์ Context ไม่ได้"
        )
        goal=goal_progress(self.profile)
        if goal:
            completed,target,percentage=goal
            self.goal_label.setText(f"เป้าหมาย {completed}/{target} บท · วันนี้ +{today} บท")
            self.goal_bar.setRange(0,100)
            self.goal_bar.setValue(percentage)
            self.goal_bar.setFormat(f"{percentage}%")
        else:
            self.goal_label.setText(f"วันนี้แปลเพิ่ม {today} บท · ยังไม่ได้ตั้งเป้าหมาย")
            self.goal_bar.setRange(0,1)
            self.goal_bar.setValue(0)
            self.goal_bar.setFormat("")
    def translation_dashboard(self):
        profiles=self.refresh_translation_progress()
        self.dashboard_dialog=TranslationDashboardDialog(self,profiles,self.repo,self.refresh_translation_progress)
        self.dashboard_dialog.exec()
        self.dashboard_dialog=None
    def select_profile(self,i):
        if i<0 or i>=len(getattr(self,"ps_list",[])):return
        self.profile=self.ps_list[i];self.settings.last_profile_id=self.profile.id
        self.novel.setToolTip(self.profile.name)
        self.novel.setText(self.profile.name)
        self.refresh_steps()
        self.refresh_goal_indicator()
    def refresh_steps(self):
        self.steps.blockSignals(True);self.steps.clear()
        if self.profile:
            for i,s in enumerate(self.profile.workflow.steps):self.steps.addItem(f"{i+1}. {s.name}")
            if not self.profile.workflow.steps:
                empty=QListWidgetItem("ยังไม่มีขั้นตอน\nเพิ่มได้ที่ ตั้งค่า → ขั้นตอน")
                empty.setFlags(Qt.NoItemFlags);empty.setTextAlignment(Qt.AlignCenter);self.steps.addItem(empty)
        else:
            empty=QListWidgetItem("เลือกนิยายเพื่อดูขั้นตอน")
            empty.setFlags(Qt.NoItemFlags);empty.setTextAlignment(Qt.AlignCenter);empty;self.steps.addItem(empty)
        self.steps.blockSignals(False)
        self.si=0 if self.profile and self.profile.workflow.steps else -1
        self.steps.setCurrentRow(self.si)
        self.update_step_indicator()
        self.refresh_files()
    def select_step(self,i):
        self.si=i
        self.update_step_indicator()
        self.refresh_files()
    def update_step_indicator(self):
        if not self.profile:
            return
        for index,step in enumerate(self.profile.workflow.steps):
            item=self.steps.item(index)
            if item:
                item.setText(f"{index+1}. {step.name}")
                item.setToolTip(step.name)
    def step(self):return self.profile.workflow.steps[self.si] if self.profile and 0<=self.si<len(self.profile.workflow.steps) else None
    def refresh_files(self):
        self.files.blockSignals(True);self.files.clear();s=self.step()
        if s:
            for f in sorted(s.files,key=lambda x:x.order):
                row=QListWidgetItem(f.label or f.path or f.dynamic_reference);row.setFlags(row.flags()|Qt.ItemIsUserCheckable);row.setCheckState(Qt.Checked if f.enabled else Qt.Unchecked);row.setData(Qt.UserRole,f.id);row.setToolTip(f.label or f.path or f.dynamic_reference);self.files.addItem(row)
            if not s.files:
                empty=QListWidgetItem("ขั้นตอนนี้ยังไม่มีไฟล์\nเพิ่มได้ที่ ตั้งค่า → ไฟล์ของขั้นตอน")
                empty.setFlags(Qt.NoItemFlags);empty.setTextAlignment(Qt.AlignCenter);empty;self.files.addItem(empty)
        else:
            empty=QListWidgetItem("เลือกนิยายและขั้นตอนเพื่อดูไฟล์")
            empty.setFlags(Qt.NoItemFlags);empty.setTextAlignment(Qt.AlignCenter);empty;self.files.addItem(empty)
        self.files.blockSignals(False)
    def save(self):
        if self.profile:self.repo.save_profile(self.profile)
        self.repo.save_settings(self.settings);self.statusBar().showMessage("Saved",2000)
    def launch_profile(self):
        if not self.profile:return
        results=self.launcher.launch_profile(self.profile)
        failures=[message for success,message in results if not success]
        succeeded=sum(1 for success,_ in results if success)
        if failures:QMessageBox.warning(self,"NovelWorkflow",f"เปิดสำเร็จ {succeeded} รายการ\n\n"+"\n".join(failures))
        else:self.statusBar().showMessage(f"เปิด {self.profile.name} แล้ว ({succeeded} รายการ)",4000)

    def launcher_dialog(self):
        if not self.profile:return
        dialog=QDialog(self);dialog.setWindowTitle("Launcher Items — "+self.profile.name);dialog.resize(760,560)
        layout=QVBoxLayout(dialog);folder=QLineEdit(self.profile.main_folder);folder.setPlaceholderText("โฟลเดอร์หลักของนิยาย")
        browse=QPushButton("Browse…");browse.clicked.connect(lambda:folder.setText(QFileDialog.getExistingDirectory(dialog,"เลือกโฟลเดอร์นิยาย",folder.text()) or folder.text()))
        folder_row=QHBoxLayout();folder_row.addWidget(folder,1);folder_row.addWidget(browse)
        layout.addWidget(QLabel("Main folder"));layout.addLayout(folder_row)
        listing=QListWidget();layout.addWidget(listing,1)
        targets=[LaunchTarget.from_dict(asdict_target(item)) for item in self.profile.launch_targets]
        def refresh():
            listing.clear()
            for target in sorted(targets,key=lambda item:item.order):
                row=QListWidgetItem(f"[{target.kind}] {target.label} — {target.target}")
                row.setFlags(row.flags()|Qt.ItemIsUserCheckable);row.setCheckState(Qt.Checked if target.enabled else Qt.Unchecked);row.setData(Qt.UserRole,target.id);listing.addItem(row)
        def add_target(kind):
            if kind=="application":
                path,_=QFileDialog.getOpenFileName(dialog,"เลือกโปรแกรม","","Applications (*.exe);;All files (*)")
            elif kind=="folder":
                path=QFileDialog.getExistingDirectory(dialog,"เลือกโฟลเดอร์")
            elif kind=="website":
                path,ok=QInputDialog.getText(dialog,"Add Website","URL (http/https):")
                if not ok:return
            else:
                path,_=QFileDialog.getOpenFileName(dialog,"เลือกไฟล์","","All files (*)")
            if not path:return
            label=Path(path).stem if kind!="website" else path
            if kind=="website":
                label,ok=QInputDialog.getText(dialog,"Website Name","ชื่อเว็บไซต์:",text=path)
                if not ok:return
            targets.append(LaunchTarget(label=label,kind=kind,target=path,order=len(targets)));refresh()
        actions=QHBoxLayout()
        for label,kind in (("Add App","application"),("Add File","file"),("Add Folder","folder"),("Add Website","website")):
            button=QPushButton(label);button.clicked.connect(lambda checked=False,k=kind:add_target(k));actions.addWidget(button)
        remove=QPushButton("Remove");remove.clicked.connect(lambda:targets.__setitem__(slice(None),[target for target in targets if target.id!=listing.currentItem().data(Qt.UserRole)]) if listing.currentItem() else None);remove.clicked.connect(refresh)
        actions.addWidget(remove);layout.addLayout(actions)
        refresh()
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()==QDialog.Accepted:
            for i in range(listing.count()):
                row=listing.item(i)
                target=next((entry for entry in targets if entry.id==row.data(Qt.UserRole)),None)
                if target:target.enabled=row.checkState()==Qt.Checked;target.order=i
            self.profile.main_folder=folder.text().strip();self.profile.launch_targets=targets;self.save()
            self.statusBar().showMessage("บันทึก Launcher Items แล้ว",2500)

    def groups_dialog(self):
        groups=self.repo.load_groups();profiles=self.repo.list_profiles()
        dialog=QDialog(self);dialog.setWindowTitle("Novel Groups");dialog.resize(560,560);layout=QVBoxLayout(dialog)
        selector=QComboBox()
        for group in groups:selector.addItem(group.name,group.id)
        name=QLineEdit();members=QListWidget();layout.addWidget(QLabel("Group"));layout.addWidget(selector);layout.addWidget(name);layout.addWidget(QLabel("นิยายในกลุ่ม"));layout.addWidget(members,1)
        def show_group(index):
            members.clear()
            current=next((group for group in groups if group.id==selector.itemData(index)),None)
            name.setText(current.name if current else "")
            for profile in profiles:
                row=QListWidgetItem(profile.name);row.setData(Qt.UserRole,profile.id);row.setFlags(row.flags()|Qt.ItemIsUserCheckable)
                row.setCheckState(Qt.Checked if current and profile.id in current.profile_ids else Qt.Unchecked);members.addItem(row)
        def store_group():
            current=next((group for group in groups if group.id==selector.currentData()),None)
            if not current:return None
            current.name=name.text().strip() or current.name
            current.profile_ids=[members.item(i).data(Qt.UserRole) for i in range(members.count()) if members.item(i).checkState()==Qt.Checked]
            self.repo.save_groups(groups);return current
        def create_group():
            group_name,ok=QInputDialog.getText(dialog,"New Group","ชื่อกลุ่ม:")
            if not ok or not group_name.strip():return
            group=NovelGroup(name=group_name.strip(),order=len(groups));groups.append(group);selector.addItem(group.name,group.id);selector.setCurrentIndex(selector.count()-1)
        def delete_group():
            current=next((group for group in groups if group.id==selector.currentData()),None)
            if not current:return
            if QMessageBox.question(dialog,"Delete Group",f"ลบกลุ่ม {current.name}?")!=QMessageBox.Yes:return
            groups.remove(current);selector.removeItem(selector.currentIndex());show_group(selector.currentIndex())
            self.repo.save_groups(groups)
        def open_group():
            current=store_group()
            if not current:return
            results=self.launcher.launch_group(current,profiles);failures=[message for success,message in results if not success]
            succeeded=sum(1 for success,_ in results if success)
            if failures:QMessageBox.warning(dialog,"Open Group",f"เปิดสำเร็จ {succeeded} รายการ\n\n"+"\n".join(failures))
            else:self.statusBar().showMessage(f"เปิดกลุ่ม {current.name} แล้ว",4000)
        selector.currentIndexChanged.connect(show_group)
        if groups:show_group(0)
        row=QHBoxLayout()
        for label,fn in (("New Group",create_group),("Delete Group",delete_group),("Save",store_group),("Open Group",open_group)):
            button=QPushButton(label);button.clicked.connect(fn);row.addWidget(button)
        layout.addLayout(row)
        close=QDialogButtonBox(QDialogButtonBox.Close);close.rejected.connect(dialog.reject);close.accepted.connect(dialog.accept);layout.addWidget(close)
        dialog.exec()

    def import_launcher_config(self):
        default=Path.home()/"AppData"/"Roaming"/"com.novellauncher.desktop"/"config.json"
        path,_=QFileDialog.getOpenFileName(self,"Import Novel Launcher Data",str(default),"JSON files (*.json)")
        if not path:return
        try:
            result=self.repo.import_launcher_config(path)
            self.refresh_profiles(self.profile.id if self.profile else None)
            QMessageBox.information(self,"Import Complete",f"นำเข้าข้อมูล Launcher แล้ว\nโปรไฟล์ใหม่: {result['profiles']}\nกลุ่มใหม่: {result['groups']}\nรายการเปิดโปรแกรม/ไฟล์/เว็บไซต์: {result['launch_targets']}\n\nไฟล์ต้นฉบับไม่ได้ถูกแก้ไข")
        except Exception as error:QMessageBox.warning(self,"Import Failed",str(error))

    def set_context_file(self):
        if not self.profile:return
        path,_=QFileDialog.getOpenFileName(self,"เลือกไฟล์ Context ของนิยาย",str(Path(self.profile.main_folder or Path.home()).expanduser()),"Context files (*.md *.txt *.json);;All files (*)")
        if not path:return
        context=Path(path).expanduser()
        try:
            chapter=latest_context_chapter(context.read_text(encoding="utf-8-sig",errors="replace"))
        except OSError as exc:
            QMessageBox.warning(self,"อ่าน Context ไม่ได้",str(exc))
            return
        if chapter is None:
            QMessageBox.warning(self,"ไม่พบเลขบท","ไฟล์นี้ไม่พบหัวข้อที่ขึ้นต้นด้วย “บทที่ <เลขบท>”")
            return
        self.profile.context_path=str(context.resolve())
        self.profile.translation_checkpoint_path=str(context.resolve())
        self.profile.chapter_state.current_chapter=chapter
        self.repo.save_profile(self.profile)
        self.statusBar().showMessage(f"เชื่อม Context แล้ว · บทล่าสุด {chapter}",3500)
        self.refresh_translation_progress()

    def set_cover(self):
        if not self.profile:return
        path,_=QFileDialog.getOpenFileName(self,"เลือกรูปปกนิยาย",str(Path.home()),"รูปภาพ (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:return
        source=Path(path).expanduser()
        if QPixmap(str(source)).isNull():
            QMessageBox.warning(self,"เปิดรูปไม่ได้","กรุณาเลือกรูป PNG, JPG, WEBP หรือ BMP ที่ถูกต้อง")
            return
        suffix=source.suffix.lower()
        root=self.repo.profile_dir(self.profile.id)
        target=root/"covers"/("cover"+suffix)
        target.parent.mkdir(parents=True,exist_ok=True)
        import shutil
        shutil.copy2(source,target)
        self.profile.cover_image_path=target.relative_to(root).as_posix()
        self.repo.save_profile(self.profile)
        self.refresh_profiles(self.profile.id)
        self.statusBar().showMessage("ตั้งรูปปกนิยายแล้ว",2500)

    def remove_cover(self):
        if not self.profile or not self.profile.cover_image_path:return
        try:
            target=self.repo.resolve_project_path(self.profile.id,self.profile.cover_image_path)
            if target.is_file():target.unlink()
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,"เอารูปปกออกไม่ได้",str(exc))
            return
        self.profile.cover_image_path=None
        self.repo.save_profile(self.profile)
        self.refresh_profiles(self.profile.id)
        self.statusBar().showMessage("เอารูปปกออกแล้ว",2500)

    def new_profile(self):
        name,ok=QInputDialog.getText(self,"New Profile","Novel name:")
        if not ok:return
        ts=self.repo.load_templates();choice,ok=QInputDialog.getItem(self,"Workflow Template","Template:",[x.name for x in ts],0,False)
        t=next((x.workflow for x in ts if x.name==choice),Workflow.defaults()) if ok else Workflow.defaults();self.refresh_profiles(self.ps.create(name,t).id)
    def duplicate_profile(self):
        if not self.profile:return
        name,ok=QInputDialog.getText(self,"Duplicate","New profile name:",text=self.profile.name+" Copy")
        if not ok:return
        g=QMessageBox.question(self,"Optional files","Copy glossary and character files too?")==QMessageBox.Yes
        self.refresh_profiles(self.ps.duplicate(self.profile,name,g,g).id)
    def rename_profile(self):
        if not self.profile:return
        n,ok=QInputDialog.getText(self,"Rename","Name:",text=self.profile.name)
        if ok:self.profile.name=n.strip() or self.profile.name;self.save();self.refresh_profiles(self.profile.id)
    def delete_profile(self):
        if self.profile and QMessageBox.question(self,"Delete","Delete this profile and all its files?")==QMessageBox.Yes:
            self.repo.delete_profile(self.profile.id);self.profile=None;self.refresh_profiles()
    def save_template(self):
        if not self.profile:return
        name,ok=QInputDialog.getText(self,"Save Workflow Template","Template name:",text=self.profile.name+" workflow")
        if not ok or not name.strip():return
        from copy import deepcopy
        templates=self.repo.load_templates();templates.append(__import__("novel_workflow.models",fromlist=["WorkflowTemplate"]).WorkflowTemplate(name.strip(),deepcopy(self.profile.workflow)))
        self.repo.save_templates(templates);self.statusBar().showMessage("Workflow template saved",2500)
    def add_step(self):
        if not self.profile:return
        n,ok=QInputDialog.getText(self,"Add Step","Name:")
        if ok:WorkflowService.add_step(self.profile.workflow,n or "New step");self.save();self.refresh_steps();self.steps.setCurrentRow(len(self.profile.workflow.steps)-1)
    def rename_step(self):
        s=self.step()
        if s:
            n,ok=QInputDialog.getText(self,"Rename Step","Name:",text=s.name)
            if ok:s.name=n or s.name;self.save();self.refresh_steps()
    def duplicate_step(self):
        if self.step():WorkflowService.duplicate_step(self.profile.workflow,self.si);self.save();self.refresh_steps();self.steps.setCurrentRow(self.si+1)
    def delete_step(self):
        if self.step() and QMessageBox.question(self,"Delete Step","Remove this workflow step?")==QMessageBox.Yes:self.profile.workflow.steps.pop(self.si);self.save();self.refresh_steps()
    def move_step(self,d):
        if self.step():self.si=WorkflowService.move(self.profile.workflow.steps,self.si,d);self.save();self.refresh_steps();self.steps.setCurrentRow(self.si)
    def file(self):
        row=self.files.currentItem();return next((f for f in self.step().files if f.id==row.data(Qt.UserRole)),None) if row and self.step() else None
    def add_file(self):
        if not self.profile or not self.step():return
        root=self.repo.profile_dir(self.profile.id).resolve()
        sources,_=QFileDialog.getOpenFileNames(self,"Link original files",str(root),"Text files (*.txt *.md *.json)")
        if not sources:return
        added=0;updated=0;skipped=0
        for src in sources:
            source=Path(src).resolve()
            if source.suffix.lower() not in (".txt",".md",".json"):
                skipped+=1
                continue
            try:
                relative=source.relative_to(root).as_posix()
                reference_type="repository_file";stored_path=relative
            except ValueError:
                reference_type="external_file";stored_path=str(source)
            old_copy="reference/"+source.name
            for workflow_step in self.profile.workflow.steps:
                for item in workflow_step.files:
                    if item.reference_type=="repository_file" and item.path==old_copy:
                        item.reference_type=reference_type;item.path=stored_path;updated+=1
            already=any(item.reference_type==reference_type and item.path==stored_path for item in self.step().files)
            if not already:
                self.step().files.append(StepFile(label=source.stem,reference_type=reference_type,path=stored_path,file_type=source.parent.name,order=len(self.step().files)))
                added+=1
        self.save();self.refresh_files()
        message=f"Linked {added} file(s); updated {updated} old reference(s)"
        if skipped:message+=f"; skipped {skipped} unsupported file(s)"
        self.statusBar().showMessage(message,6000)
    def rename_chapter_files(self):
        if not self.profile:
            QMessageBox.information(self, "จัดเลขบท", "เลือกนิยายก่อนครับ")
            return
        start = self.profile.main_folder or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ที่มีไฟล์บท", start)
        if not folder:
            return
        try:
            dialog = ChapterRenameDialog(folder, self)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "จัดเลขบท", str(exc))
            return
        if not dialog.exec() or not dialog.renamed:
            return

        profile_root = self.repo.profile_dir(self.profile.id).resolve()
        updated = 0
        for step in self.profile.workflow.steps:
            for item in step.files:
                try:
                    if item.reference_type == "repository_file" and item.path:
                        old_path = self.repo.resolve_project_path(self.profile.id, item.path).resolve()
                    elif item.reference_type == "external_file" and item.path:
                        old_path = Path(item.path).expanduser().resolve()
                    else:
                        continue
                    new_path = dialog.renamed.get(old_path)
                    if new_path is None:
                        continue
                    if item.reference_type == "repository_file":
                        item.path = new_path.relative_to(profile_root).as_posix()
                    else:
                        item.path = str(new_path)
                    updated += 1
                except (OSError, ValueError):
                    continue

        for target in self.profile.launch_targets:
            if target.kind != "file" or not target.target:
                continue
            try:
                new_path = dialog.renamed.get(Path(target.target).expanduser().resolve())
                if new_path is not None:
                    target.target = str(new_path)
                    updated += 1
            except (OSError, ValueError):
                continue

        for attribute in ("context_path", "translation_checkpoint_path"):
            value = getattr(self.profile, attribute, None)
            if not value:
                continue
            try:
                new_path = dialog.renamed.get(Path(value).expanduser().resolve())
                if new_path is not None:
                    setattr(self.profile, attribute, str(new_path))
            except (OSError, ValueError):
                continue

        self.save()
        self.statusBar().showMessage(
            f"เปลี่ยนชื่อ {len(dialog.renamed)} ไฟล์ · อัปเดตลิงก์ในโปรแกรม {updated} รายการ",
            7000,
        )

    def add_dynamic(self):
        if not self.step():return
        ref,ok=QInputDialog.getItem(self,"Dynamic chapter","Reference:",["CURRENT_SOURCE_CHAPTER","CURRENT_TRANSLATED_CHAPTER","CURRENT_REVIEWED_CHAPTER"],0,False)
        if ok:self.step().files.append(StepFile(label=ref.replace("CURRENT_","").replace("_"," ").title(),reference_type="dynamic",dynamic_reference=ref,file_type="chapter",order=len(self.step().files)));self.save();self.refresh_files()
    def move_file(self,d):
        f=self.file()
        if f:
            i=next(n for n,x in enumerate(self.step().files) if x.id==f.id)
            j=WorkflowService.move(self.step().files,i,d);self.save();self.refresh_files();self.files.setCurrentRow(j)
    def rename_file_label(self):
        f=self.file()
        if f:
            name,ok=QInputDialog.getText(self,"Rename Display Label","Label:",text=f.label)
            if ok:f.label=name.strip() or f.label;self.save();self.refresh_files()
    def file_manager(self):
        if not self.profile:return
        dialog=QDialog(self);dialog.setWindowTitle("Project File Manager");dialog.resize(780,560);layout=QVBoxLayout(dialog)
        search=QLineEdit();search.setPlaceholderText("Search filename or path");layout.addWidget(search)
        listing=QListWidget();layout.addWidget(listing,1)
        actions=QHBoxLayout();layout.addLayout(actions)
        def refresh():
            listing.clear();root=self.repo.profile_dir(self.profile.id)
            for path in sorted(root.rglob("*")):
                rel=path.relative_to(root).as_posix()
                if path.is_file() and path.name!="profile.json" and (not search.text() or search.text().lower() in rel.lower()):listing.addItem(rel)
        def selected():
            return self.repo.resolve_project_path(self.profile.id,listing.currentItem().text()) if listing.currentItem() else None
        def create():
            rel,ok=QInputDialog.getText(dialog,"Create Text File","Relative path (for example prompts/find_terms.txt):")
            if not ok or not rel:return
            if Path(rel).suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(dialog,"Unsupported","Use .txt, .md, or .json.");return
            path=self.repo.resolve_project_path(self.profile.id,rel)
            if path.exists():QMessageBox.warning(dialog,"Exists","File already exists.");return
            editor=Editor(dialog,"New text file")
            if editor.exec()==QDialog.Accepted:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(editor.text(),encoding="utf-8");refresh()
        def edit():
            path=selected()
            if not path:return
            if path.suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(dialog,"Unsupported","Only text, Markdown, and JSON can be edited.");return
            editor=Editor(dialog,"Edit "+path.name,path.read_text(encoding="utf-8"))
            if editor.exec()==QDialog.Accepted:path.write_text(editor.text(),encoding="utf-8");refresh()
        def rename():
            path=selected()
            if not path:return
            root=self.repo.profile_dir(self.profile.id)
            rel,ok=QInputDialog.getText(dialog,"Rename File","New relative path:",text=str(path.relative_to(root)))
            if not ok:return
            dest=self.repo.resolve_project_path(self.profile.id,rel)
            if dest.exists():QMessageBox.warning(dialog,"Exists","Destination already exists.");return
            old=path.relative_to(root).as_posix();dest.parent.mkdir(parents=True,exist_ok=True);path.rename(dest)
            new=dest.relative_to(root).as_posix()
            for step in self.profile.workflow.steps:
                for item in step.files:
                    if item.path==old:item.path=new
            self.save();refresh()
        def delete():
            path=selected()
            if not path:return
            if QMessageBox.question(dialog,"Delete File",f"Permanently delete {path.name}?")==QMessageBox.Yes:
                path.unlink()
                for step in self.profile.workflow.steps:
                    step.files=[item for item in step.files if item.reference_type=="external_file" or not item.path or self.repo.resolve_project_path(self.profile.id,item.path)!=path]
                self.save();refresh();self.refresh_files()
        def import_file():
            source,_=QFileDialog.getOpenFileName(dialog,"Import file","","Text files (*.txt *.md *.json)")
            if not source:return
            src=Path(source)
            if src.suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(dialog,"Unsupported","Use .txt, .md, or .json.");return
            rel,ok=QInputDialog.getText(dialog,"Import File","Destination relative path:",text="reference/"+src.name)
            if not ok:return
            dest=self.repo.resolve_project_path(self.profile.id,rel)
            if dest.exists():QMessageBox.warning(dialog,"Exists","Destination already exists.");return
            import shutil;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest);refresh()
        def attach():
            path=selected()
            if not path or not self.step():return
            rel=path.relative_to(self.repo.profile_dir(self.profile.id)).as_posix()
            if any(item.path==rel for item in self.step().files):
                QMessageBox.information(dialog,"Already added","This file is already attached to the selected step.");return
            label,ok=QInputDialog.getText(dialog,"Attach File","Display label:",text=path.stem)
            if not ok:return
            self.step().files.append(StepFile(label=label or path.stem,path=rel,file_type=path.parent.name,order=len(self.step().files)))
            self.save();self.refresh_files();self.statusBar().showMessage("File attached to selected step",2500)
        for label,fn in (("New",create),("Import",import_file),("Add to Step",attach),("Edit",edit),("Rename",rename),("Delete",delete)):
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        search.textChanged.connect(refresh);refresh();dialog.exec()
    def remove_file(self):
        f=self.file()
        if f:self.step().files.remove(f);self.save();self.refresh_files()
    def toggle_file(self,row):
        f=next((x for x in self.step().files if x.id==row.data(Qt.UserRole)),None) if self.step() else None
        if f:f.enabled=row.checkState()==Qt.Checked;self.save()
    def edit_file(self):
        f=self.file()
        if not f:return
        if f.reference_type=="dynamic":return
        path=Path(f.path).expanduser().resolve() if f.reference_type=="external_file" else self.repo.resolve_project_path(self.profile.id,f.path);dlg=Editor(self,"Edit "+f.label,path.read_text(encoding="utf-8") if path.exists() else "")
        if dlg.exec()==QDialog.Accepted:path.write_text(dlg.text(),encoding="utf-8");self.save()
    def preview(self):
        if not self.step():return
        try:text=self.assembler.assemble(self.profile,self.step(),self.settings.separator,self.settings.show_filename_heading)
        except Exception as e:QMessageBox.warning(self,"Preview unavailable",str(e));return
        dlg=QDialog(self);dlg.setWindowTitle("Preview: "+self.step().name);dlg.resize(850,650);l=QVBoxLayout(dlg);view=QTextEdit();view.setReadOnly(True);view.setPlainText(text);l.addWidget(view);l.addWidget(QLabel(f"{len(text):,} characters"))
        buttons=QDialogButtonBox(QDialogButtonBox.Close);copy=buttons.addButton("Copy Contents",QDialogButtonBox.ActionRole);copy.clicked.connect(lambda:self.copy_text(text));buttons.rejected.connect(dlg.reject);l.addWidget(buttons);dlg.exec()
    def copy_text(self,text):QApplication.clipboard().setText(text);self.statusBar().showMessage("Copied to clipboard",2500)
    def copy_step(self):
        step=self.step()
        if not step:return
        try:
            paths=[]
            for item in sorted(step.files,key=lambda x:x.order):
                if not item.enabled:continue
                if item.reference_type=="dynamic":
                    path=self.assembler.resolve(self.profile,item.dynamic_reference)
                elif item.reference_type=="external_file":
                    if not item.path:raise ValueError(f"Missing linked file path for {item.label}")
                    path=Path(item.path).expanduser().resolve()
                else:
                    if not item.path:raise ValueError(f"Missing file path for {item.label}")
                    path=self.repo.resolve_project_path(self.profile.id,item.path)
                if not path.is_file():raise FileNotFoundError(path)
                resolved=path.resolve()
                if resolved not in paths:paths.append(resolved)
            if not paths:
                self.statusBar().showMessage("No enabled files to copy",3000);return
            mime_data=QMimeData()
            mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
            QApplication.clipboard().setMimeData(mime_data)
            self.statusBar().showMessage(f"Copied {len(paths)} file(s) from {step.name}. Paste with Ctrl+V.",5000)
            next_row=WorkflowService.next_index(self.si,self.steps.count())
            self.si=next_row
            self.steps.blockSignals(True)
            self.steps.setCurrentRow(next_row)
            self.steps.blockSignals(False)
            self.update_step_indicator()
            self.refresh_files()
        except Exception as e:QMessageBox.warning(self,"Copy failed",str(e))
    def settings_dialog(self):
        """Open a separate management page; keep the main workspace action-focused."""
        original_lists=(self.profiles,self.steps,self.files)
        previous_profile_id=self.profile.id if self.profile else None
        active_step=self.step()
        active_step_id=active_step.id if active_step else None

        dialog=QDialog(self)
        dialog.setWindowTitle("ตั้งค่าและจัดการ")
        dialog.resize(1040,720)
        root=QVBoxLayout(dialog)
        tabs=QTabWidget()
        root.addWidget(tabs,1)

        self.profiles=QListWidget()
        self.profiles.setSpacing(1)
        self.profiles.setCursor(Qt.PointingHandCursor)
        self.profiles.setAccessibleName("รายการนิยาย")
        self.profiles.currentRowChanged.connect(self.select_profile)
        self.steps=QListWidget()
        self.steps.setSpacing(1)
        self.steps.setCursor(Qt.PointingHandCursor)
        self.steps.setAccessibleName("ขั้นตอนงาน")
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.currentRowChanged.connect(self.select_step)
        self.files=QListWidget()
        self.files.setSpacing(1)
        self.files.setCursor(Qt.PointingHandCursor)
        self.files.setAccessibleName("ไฟล์ของขั้นตอน")
        self.files.itemChanged.connect(self.toggle_file)

        def management_tab(title,widget,buttons):
            page=QWidget()
            layout=QVBoxLayout(page)
            layout.setContentsMargins(14,14,14,14)
            layout.addWidget(widget,1)
            grid=QGridLayout()
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            for index,(label,callback) in enumerate(buttons):
                button=QPushButton(label)
                button.setMinimumHeight(40)
                button.clicked.connect(callback)
                grid.addWidget(button,index//2,index%2)
            layout.addLayout(grid)
            tabs.addTab(page,title)

        profile_actions=[
            ("เพิ่มนิยาย",self.new_profile),("ทำสำเนา",self.duplicate_profile),
            ("ตั้งรูปปก",self.set_cover),("เอารูปปกออก",self.remove_cover),
            ("เลือก Context",self.set_context_file),("เปลี่ยนชื่อ",self.rename_profile),
            ("ตัวเปิดไฟล์",self.launcher_dialog),("ลบนิยาย",self.delete_profile),
        ]
        step_actions=[
            ("เพิ่มขั้นตอน",self.add_step),("เปลี่ยนชื่อ",self.rename_step),
            ("ทำสำเนา",self.duplicate_step),("ลบขั้นตอน",self.delete_step),
            ("เลื่อนขึ้น",lambda:self.move_step(-1)),("เลื่อนลง",lambda:self.move_step(1)),
            ("บันทึกเป็นแม่แบบ",self.save_template),
        ]
        file_actions=[
            ("เพิ่มไฟล์",self.add_file),("อ้างอิงบทปัจจุบัน",self.add_dynamic),
            ("เอาออกจากขั้นตอน",self.remove_file),("เลื่อนขึ้น",lambda:self.move_file(-1)),
            ("เลื่อนลง",lambda:self.move_file(1)),("เปลี่ยนชื่อที่แสดง",self.rename_file_label),
            ("จัดการไฟล์",self.file_manager),("ดูตัวอย่าง",self.preview),
        ]
        management_tab("นิยาย",self.profiles,profile_actions)
        management_tab("ขั้นตอน",self.steps,step_actions)
        management_tab("ไฟล์ของขั้นตอน",self.files,file_actions)

        preferences=QWidget()
        prefs=QVBoxLayout(preferences)
        appearance=QComboBox()
        appearance.addItems(["System","Light","Dark"])
        appearance.setCurrentText(self.settings.appearance)
        prefs.addWidget(QLabel("รูปลักษณ์"))
        prefs.addWidget(appearance)
        separator=QLineEdit(self.settings.separator)
        prefs.addWidget(QLabel("ตัวคั่นเนื้อหา (ใช้ {FILE_NAME})"))
        prefs.addWidget(separator)
        checks=[]
        for label,attr in (("แสดงชื่อไฟล์","show_filename_heading"),("ยืนยันก่อนลบ","confirm_before_deleting"),("เปิดนิยายล่าสุดเมื่อเริ่มโปรแกรม","open_last_profile")):
            check=QCheckBox(label)
            check.setChecked(getattr(self.settings,attr))
            prefs.addWidget(check)
            checks.append((check,attr))
        prefs.addStretch(1)
        tabs.addTab(preferences,"ทั่วไป")

        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Close)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)

        result=QDialog.Rejected
        try:
            self.refresh_profiles(previous_profile_id)
            result=dialog.exec()
            if result==QDialog.Accepted:
                self.settings.appearance=appearance.currentText()
                self.settings.separator=separator.text()
                for check,attr in checks:
                    setattr(self.settings,attr,check.isChecked())
                self.save()
                self.apply_theme()
        finally:
            self.profiles,self.steps,self.files=original_lists
            self.refresh_profiles(self.profile.id if self.profile else previous_profile_id)
            if self.profile and self.profile.workflow.steps:
                restored=next((i for i,step in enumerate(self.profile.workflow.steps) if step.id==active_step_id),0)
                self.steps.setCurrentRow(restored)
                if self.si!=restored:
                    self.select_step(restored)
            else:
                self.si=-1
                self.refresh_files()
