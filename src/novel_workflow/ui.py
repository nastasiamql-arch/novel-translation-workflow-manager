from pathlib import Path
from dataclasses import asdict as asdict_target
from PySide6.QtCore import Qt, QUrl, QSize, QTimer, QMimeData
from PySide6.QtGui import QAction, QKeySequence, QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import *
from .models import AppSettings, LaunchTarget, NovelGroup, StepFile, Workflow, migrate_legacy_basic_workflow, order_profiles
from .services import ProfileService, WorkflowService, AssemblyService
from .launcher import LauncherService
from .storage import ProjectRepository
from .translation_progress import latest_context_chapter, sync_profile_context, daily_chapter_count, goal_progress
from .progress_dialog import TranslationDashboardPage
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
        self.dashboard_page=None
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
        bar.setIconSize(QSize(20,20))
        logo=Path(__file__).resolve().parent/"resources"/"novelworkflow.png"
        mark=QLabel()
        if logo.is_file(): mark.setPixmap(QPixmap(str(logo)).scaled(24,24,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        bar.addWidget(mark)
        brand=QLabel("<b>NovelWorkflow</b>")
        brand.setObjectName("brandTitle")
        bar.addWidget(brand)
        spacer=QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
        bar.addWidget(spacer)
        for label,fn in (("+ เพิ่มนิยาย",self.new_profile),("เปิดนิยาย",self.launch_profile),("นำเข้าข้อมูลเดิม",self.import_launcher_config)):
            a=QAction(label,self);a.triggered.connect(fn);bar.addAction(a)
        page_menu=QMenu(self)
        for label,key in (("หน้าหลัก","home"),("นิยาย","novels"),("ขั้นตอนงาน","workflow"),("ความคืบหน้า","progress"),("กลุ่มนิยาย","groups"),("ไฟล์","files"),("ตั้งค่า","settings")):
            action=page_menu.addAction(label);action.triggered.connect(lambda checked=False,k=key:self.open_destination(k))
        page_button=QToolButton();page_button.setText("เปิดหน้า");page_button.setPopupMode(QToolButton.InstantPopup);page_button.setMenu(page_menu);bar.addWidget(page_button)

        root=QWidget()
        root_layout=QHBoxLayout(root)
        root_layout.setContentsMargins(0,0,0,0)
        root_layout.setSpacing(0)
        sidebar=QFrame();sidebar.setObjectName("appSidebar");sidebar.setFixedWidth(176)
        side_layout=QVBoxLayout(sidebar);side_layout.setContentsMargins(8,12,8,8);side_layout.setSpacing(3)
        side_title=QLabel("WORKSPACE");side_title.setObjectName("sectionHeading");side_layout.addWidget(side_title)
        self.nav_buttons={}
        for key,label in (("home","หน้าหลัก"),("novels","นิยาย"),("groups","กลุ่มนิยาย"),("files","ไฟล์"),("progress","ความคืบหน้า"),("settings","ตั้งค่า")):
            button=QToolButton();button.setText(label);button.setToolButtonStyle(Qt.ToolButtonTextOnly);button.setCheckable(True);button.setAutoExclusive(True);button.setObjectName("navItem");button.setMinimumHeight(34);button.clicked.connect(lambda checked=False,k=key:self.open_destination(k));side_layout.addWidget(button);self.nav_buttons[key]=button
        side_layout.addStretch(1)
        self.sidebar_status=QLabel("พร้อมทำงาน");self.sidebar_status.setObjectName("mutedLabel");self.sidebar_status.setWordWrap(True);side_layout.addWidget(self.sidebar_status)
        root_layout.addWidget(sidebar)
        # The workspace tabs already provide the complete navigation menu.
        # Keep a single navigation surface instead of showing the same items twice.
        sidebar.hide()
        self.main_tabs=QTabWidget();self.main_tabs.setObjectName("workspaceTabs");self.main_tabs.setDocumentMode(True);self.main_tabs.setTabsClosable(True);self.main_tabs.tabCloseRequested.connect(self.close_workspace_tab);root_layout.addWidget(self.main_tabs,1)
        self.novel=QLabel("ยังไม่ได้เลือกนิยาย")
        self.novel.setObjectName("currentNovel")
        self.novel.setWordWrap(True)
        self.novel.setMinimumHeight(62)
        self.novel.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum)
        splitter=QSplitter()
        splitter.setChildrenCollapsible(False)
        workflow_root=QWidget();workflow_layout=QVBoxLayout(workflow_root);workflow_layout.setContentsMargins(8,8,8,8);workflow_layout.setSpacing(8);workflow_layout.addWidget(self.novel);workflow_layout.addWidget(splitter,1)
        self.workspace_page=workflow_root
        self.profiles=QListWidget()
        self.profiles.setSpacing(1)
        self.profiles.setCursor(Qt.PointingHandCursor)
        self.profiles.setAccessibleName("รายการนิยาย")
        self.profiles.setToolTip("ลากนิยายขึ้นหรือลงเพื่อเปลี่ยนลำดับ")
        self.profiles.setDragDropMode(QAbstractItemView.InternalMove)
        self.profiles.setDefaultDropAction(Qt.MoveAction)
        self.profiles.setDropIndicatorShown(True)
        self.profiles.setDragEnabled(True)
        self.profiles.setAcceptDrops(True)
        self.profiles.setDragDropOverwriteMode(False)
        self.profiles.currentRowChanged.connect(self.select_profile)
        self.profiles.itemDoubleClicked.connect(lambda item:self.open_novel_workspace(item.data(Qt.UserRole)))
        self.profiles.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profiles.customContextMenuRequested.connect(self._profile_context_menu)
        self.profiles.model().rowsMoved.connect(self._profile_rows_moved)
        self.steps=QListWidget()
        self.steps.setSpacing(1)
        self.steps.setMinimumHeight(164)
        self.steps.setCursor(Qt.PointingHandCursor)
        self.steps.setAccessibleName("ขั้นตอนงาน")
        self.steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.steps.currentRowChanged.connect(self.select_step)
        self.steps.setContextMenuPolicy(Qt.CustomContextMenu)
        self.steps.customContextMenuRequested.connect(self._step_context_menu)
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
        self.files.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._workflow_file_context_menu)
        splitter.addWidget(self.column("ไฟล์ของขั้นตอน",self.files,[("จัดรูปแบบเลขบท",self.rename_chapter_files),("COPY STEP",self.copy_step)]))
        splitter.setSizes([360,800])
        self.workspace_lists=(self.profiles,self.steps,self.files)
        self.dashboard_page=TranslationDashboardPage(self,[],self.repo,self.refresh_translation_progress)
        self.pages={};self.page_keys={}
        self.home_page=self.build_home_page()
        self.add_workspace_tab("home","หน้าหลัก",self.home_page,closable=False)
        self.novels_page=self.build_novels_page()
        self.add_workspace_tab("novels","นิยาย",self.novels_page,closable=False)
        self.workflow_page=workflow_root
        self.add_workspace_tab("workflow","ขั้นตอนงาน",self.workflow_page,closable=False)
        self.add_workspace_tab("progress", "ความคืบหน้า", self.dashboard_page, closable=False)
        self.setCentralWidget(root)
        self.main_tabs.currentChanged.connect(self.on_main_tab_changed)
        self.nav_buttons["home"].setChecked(True)
        self.main_tabs.setCurrentWidget(self.home_page)
        self.statusBar().showMessage("เลือกนิยายและขั้นตอนเพื่อเริ่มทำงาน")
        self.shortcut("Ctrl+Shift+C",self.copy_step)
        self.shortcut("Ctrl+P",self.preview)
        self.shortcut("Ctrl+R",self.refresh)
        self.shortcut("Ctrl+S",self.save)
        self.progress_timer=QTimer(self)
        self.progress_timer.setInterval(10000)
        self.progress_timer.timeout.connect(self.refresh_translation_progress)
        self.progress_timer.start()

    def add_workspace_tab(self,key,title,widget,closable=True):
        if key in self.pages:
            existing=self.pages[key]
            if self.main_tabs.indexOf(existing)<0:
                index=self.main_tabs.addTab(existing,title)
                self.main_tabs.setTabWhatsThis(index,key)
                self._add_tab_close_button(existing)
            self.main_tabs.setCurrentWidget(existing);return existing
        index=self.main_tabs.addTab(widget,title);self.pages[key]=widget;self.page_keys[id(widget)]=key
        self.main_tabs.setTabWhatsThis(index,key)
        self._add_tab_close_button(widget)
        self.main_tabs.setCurrentIndex(index);return widget

    def _add_tab_close_button(self,widget):
        button=QToolButton();button.setText("×");button.setObjectName("tabCloseButton");button.setToolTip("ปิดแท็บนี้");button.setAccessibleName("ปิดแท็บนี้");button.setFixedSize(20,20);button.clicked.connect(lambda checked=False,w=widget:self.close_workspace_tab(self.main_tabs.indexOf(w)) if self.main_tabs.indexOf(w)>=0 else None)
        index=self.main_tabs.indexOf(widget)
        if index>=0:self.main_tabs.tabBar().setTabButton(index,QTabBar.RightSide,button)

    def close_workspace_tab(self,index):
        widget=self.main_tabs.widget(index);key=self.page_keys.get(id(widget))
        if key in ("home","novels","workflow","progress"):return
        state=getattr(self,"_files_states",{}).get(key)
        if state and self._files_dirty(state):
            answer=QMessageBox.question(self,"ปิดแท็บไฟล์","บันทึกการแก้ไขก่อนปิดแท็บหรือไม่?",QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
            if answer==QMessageBox.Cancel:return
            if answer==QMessageBox.Save and not self._files_save(key):return
        self.main_tabs.removeTab(index)
        if key in ("home","novels","workflow","progress"):
            return
        self.pages.pop(key,None);self.page_keys.pop(id(widget),None);widget.deleteLater()

    def build_home_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(22,20,22,20);layout.setSpacing(12)
        title=QLabel("ทำงานต่อ");title.setObjectName("pageTitle");layout.addWidget(title)
        self.home_current=QLabel("เลือกนิยายเพื่อเริ่มทำงาน");self.home_current.setObjectName("bodyLabel");layout.addWidget(self.home_current)
        actions=QHBoxLayout()
        for label,key in (("เปิดรายการนิยาย","novels"),("ดูความคืบหน้า","progress"),("จัดการกลุ่ม","groups")):
            button=QPushButton(label);button.clicked.connect(lambda checked=False,k=key:self.open_destination(k));actions.addWidget(button)
        actions.addStretch(1);layout.addLayout(actions)
        recent_title=QLabel("นิยายของคุณ");recent_title.setObjectName("sectionHeading");layout.addWidget(recent_title)
        self.home_novels=QListWidget();self.home_novels.itemDoubleClicked.connect(lambda item:self.open_novel_workspace(item.data(Qt.UserRole)));layout.addWidget(self.home_novels,1)
        return page

    def build_novels_page(self):
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(20,18,20,18);layout.setSpacing(10)
        title=QLabel("นิยาย");title.setObjectName("pageTitle");layout.addWidget(title)
        hint=QLabel("ดับเบิลคลิกนิยายเพื่อเปิดพื้นที่ทำงาน หรือคลิกขวาเพื่อดูการจัดการ");hint.setObjectName("mutedLabel");layout.addWidget(hint)
        layout.addWidget(self.profiles,1)
        actions=QHBoxLayout()
        for label,fn in (("เพิ่มนิยาย",self.new_profile),("ทำสำเนา",self.duplicate_profile),("เปลี่ยนชื่อ",self.rename_profile),("เปิดขั้นตอนงาน",lambda:self.open_destination("workflow")),("เปิดตัวเลือก",self.launch_profile)):
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        actions.addStretch(1);layout.addLayout(actions);return page

    def open_novel_workspace(self,profile_id):
        profile=next((item for item in getattr(self,"ps_list",[]) if item.id==profile_id),None)
        if not profile:return
        key="novel:"+profile.id
        if key in self.pages:self.main_tabs.setCurrentWidget(self.pages[key]);self.set_profile_by_id(profile.id);return
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(22,18,22,18)
        heading=QLabel(profile.name);heading.setObjectName("pageTitle");layout.addWidget(heading)
        meta=QLabel(str(self.repo.profile_dir(profile.id)));meta.setObjectName("mutedLabel");layout.addWidget(meta)
        goal=getattr(profile,"default_goal_chapters",None) or 0
        latest=None
        try:
            if profile.context_path and Path(profile.context_path).is_file():latest=latest_context_chapter(Path(profile.context_path).read_text(encoding="utf-8-sig",errors="replace"))
        except OSError:pass
        summary=QLabel(f"{len(profile.workflow.steps)} ขั้นตอน · เป้าหมาย {goal} บท · Context ล่าสุด {latest if latest is not None else 'ยังไม่เชื่อมต่อ'}");summary.setObjectName("bodyLabel");layout.addWidget(summary)
        buttons=QHBoxLayout()
        for label,action in (("เปิดขั้นตอนงาน","workflow"),("ไฟล์","files"),("ตัวเปิดไฟล์","launcher")):
            button=QPushButton(label);button.clicked.connect(lambda checked=False,a=action,pid=profile.id:self.open_novel_action(pid,a));buttons.addWidget(button)
        buttons.addStretch(1);layout.addLayout(buttons);layout.addStretch(1)
        self.add_workspace_tab(key,profile.name,page,True);self.set_profile_by_id(profile.id)

    def set_profile_by_id(self,profile_id):
        row=next((i for i,item in enumerate(self.ps_list) if item.id==profile_id),-1)
        if row>=0:self.profiles.setCurrentRow(row)

    def open_novel_action(self,profile_id,action):
        self.set_profile_by_id(profile_id)
        if action=="workflow":self.open_destination("workflow")
        elif action=="files":self.file_manager()
        elif action=="launcher":self.launcher_dialog()

    def open_destination(self,key):
        if key in ("home","novels","workflow","progress"):
            title={"home":"หน้าหลัก","novels":"นิยาย","workflow":"ขั้นตอนงาน","progress":"ความคืบหน้า"}[key]
            widget={"home":self.home_page,"novels":self.novels_page,"workflow":self.workflow_page,"progress":self.dashboard_page}[key]
            self.add_workspace_tab(key,title,widget,True)
        elif key=="groups":self.groups_dialog()
        elif key=="files":self.file_manager()
        elif key=="settings":self.settings_dialog()
        button=self.nav_buttons.get(key)
        if button:button.setChecked(True)

    def _profile_context_menu(self,point):
        item=self.profiles.itemAt(point)
        if item and item.data(Qt.UserRole):self.profiles.setCurrentItem(item)
        menu=QMenu(self.profiles)
        for label,fn in (("เปิดพื้นที่นิยาย",lambda:self.open_novel_workspace(self.profile.id) if self.profile else None),("เปิดขั้นตอนงาน",lambda:self.open_destination("novels")),("ทำสำเนา",self.duplicate_profile),("เปลี่ยนชื่อ",self.rename_profile),("ตั้งรูปปก",self.set_cover),("เลือกไฟล์ Context",self.set_context_file),("จัดการตัวเปิดไฟล์",self.launcher_dialog),("ลบนิยาย",self.delete_profile)):
            menu.addAction(label,fn)
        menu.addSeparator();menu.addAction("เพิ่มนิยาย",self.new_profile);menu.exec(self.profiles.mapToGlobal(point))

    def _step_context_menu(self,point):
        item=self.steps.itemAt(point)
        if item:self.steps.setCurrentItem(item)
        menu=QMenu(self.steps)
        for label,fn in (("เพิ่มขั้นตอน",self.add_step),("เปลี่ยนชื่อ",self.rename_step),("ทำสำเนา",self.duplicate_step),("เลื่อนขึ้น",lambda:self.move_step(-1)),("เลื่อนลง",lambda:self.move_step(1)),("บันทึกเป็นแม่แบบ",self.save_template),("ลบขั้นตอน",self.delete_step)):
            menu.addAction(label,fn)
        menu.exec(self.steps.mapToGlobal(point))

    def _workflow_file_context_menu(self,point):
        item=self.files.itemAt(point)
        if item:self.files.setCurrentItem(item)
        menu=QMenu(self.files)
        for label,fn in (("เพิ่มไฟล์เข้าขั้นตอน",self.add_file),("อ้างอิงบทปัจจุบัน",self.add_dynamic),("แก้ไขไฟล์ข้อความ",self.edit_file),("ดูตัวอย่างขั้นตอน",self.preview),("จัดการไฟล์ทั้งหมด",self.file_manager),("จัดรูปแบบเลขบท",self.rename_chapter_files),("เอาออกจากขั้นตอน",self.remove_file)):
            menu.addAction(label,fn)
        menu.exec(self.files.mapToGlobal(point))

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
        stored_order=getattr(self.settings,"profile_order",[])
        if not isinstance(stored_order,list):stored_order=[]
        stored_order=[profile_id for profile_id in stored_order if isinstance(profile_id,str)]
        self.ps_list=order_profiles(self.repo.list_profiles(),stored_order)
        normalized_order=[profile.id for profile in self.ps_list]
        if normalized_order!=stored_order:
            self.settings.profile_order=normalized_order
            try:self.repo.save_settings(self.settings)
            except OSError as exc:
                if hasattr(self,"statusBar"):self.statusBar().showMessage(f"บันทึกลำดับนิยายไม่สำเร็จ: {exc}",6000)
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
            item.setData(Qt.UserRole,profile.id)
            item.setToolTip(f"{profile.name}\\nลากเพื่อเปลี่ยนลำดับ")
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
        if hasattr(self,"home_novels"):
            self.home_novels.clear()
            for profile in self.ps_list:
                row=QListWidgetItem(profile.name);row.setData(Qt.UserRole,profile.id);self.home_novels.addItem(row)
            if self.profile:self.home_current.setText(f"เรื่องล่าสุด: {self.profile.name} · {len(self.profile.workflow.steps)} ขั้นตอน")
            else:self.home_current.setText("ยังไม่มีนิยาย · เลือกเพิ่มนิยายจากหน้ารายการนิยาย")
    def _profile_rows_moved(self,*_):
        ordered_ids=[
            self.profiles.item(index).data(Qt.UserRole)
            for index in range(self.profiles.count())
            if self.profiles.item(index).data(Qt.UserRole)
        ]
        if len(ordered_ids)!=len(self.ps_list):return
        previous_order=list(self.settings.profile_order)
        self.ps_list=order_profiles(self.ps_list,ordered_ids)
        self.settings.profile_order=ordered_ids
        try:
            self.repo.save_settings(self.settings)
        except OSError as exc:
            self.settings.profile_order=previous_order
            self.statusBar().showMessage(f"บันทึกลำดับนิยายไม่สำเร็จ: {exc}",6000)
            self.refresh_profiles(self.profile.id if self.profile else None)
            return
        selected=self.profiles.currentItem()
        if selected is not None:
            profile_id=selected.data(Qt.UserRole)
            self.profile=next((profile for profile in self.ps_list if profile.id==profile_id),self.profile)
        self.statusBar().showMessage("บันทึกลำดับนิยายแล้ว",2500)

    def refresh_translation_progress(self):
        profiles=getattr(self,"ps_list",[])
        for profile in profiles:
            if sync_profile_context(profile):self.repo.save_profile(profile)
        if self.profile:
            self.profile=next((profile for profile in profiles if profile.id==self.profile.id),self.profile)
        dashboard=getattr(self,"dashboard_page",None)
        if dashboard is not None and self.main_tabs.currentWidget() is dashboard:dashboard.set_profiles(profiles)
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
        self.dashboard_page.set_profiles(profiles)
        self.main_tabs.setCurrentWidget(self.dashboard_page)
        self.dashboard_page.tabs.setCurrentIndex(1)
        self.dashboard_page.goal_tabs.setCurrentIndex(0)
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
        current=self.main_tabs.currentWidget() if hasattr(self,"main_tabs") else None
        key=self.page_keys.get(id(current),"") if current is not None else ""
        if key.startswith("files:") and self._files_dirty(self._files_states[key]):return self._files_save(key)
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
        resolved_context=str(context.resolve())
        previous_context=str(Path(self.profile.context_path).expanduser().resolve()) if self.profile.context_path else None
        self.profile.context_path=resolved_context
        self.profile.translation_checkpoint_path=resolved_context
        self.profile.chapter_state.current_chapter=chapter
        if self.profile.translation_goal_target is not None and (
            self.profile.translation_goal_baseline is None or previous_context != resolved_context
        ):
            self.profile.translation_goal_baseline=chapter
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
        mode_labels = ["เติม 0 ให้ครบ 4 หลัก", "ตัด 0 ด้านหน้า"]
        mode_label, ok = QInputDialog.getItem(self, "รูปแบบเลขบท", "เลือกวิธีจัดเลข:", mode_labels, 0, False)
        if not ok:
            return
        mode = "pad" if mode_label == mode_labels[0] else "strip"
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ที่มีไฟล์บท", start)
        if not folder:
            return
        try:
            dialog = ChapterRenameDialog(folder, self, mode)
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
        """Open settings as an in-window tab, creating it on first use."""
        if getattr(self,"settings_page",None) is not None:
            self.main_tabs.setCurrentWidget(self.settings_page)
            return

        previous_profile_id=self.profile.id if self.profile else None
        active_step=self.step()
        active_step_id=active_step.id if active_step else None
        page=QWidget()
        root=QVBoxLayout(page)
        intro=QLabel("จัดการนิยาย ขั้นตอน และไฟล์จากแท็บด้านล่าง · ค่าทั่วไปบันทึกเมื่อกดบันทึก")
        intro.setObjectName("mutedLabel")
        root.addWidget(intro)
        tabs=QTabWidget()
        tabs.setDocumentMode(True)
        root.addWidget(tabs,1)

        self.settings_profiles=QListWidget()
        self.settings_profiles.setSpacing(1)
        self.settings_profiles.setCursor(Qt.PointingHandCursor)
        self.settings_profiles.setAccessibleName("รายการนิยาย")
        self.settings_profiles.currentRowChanged.connect(self.select_profile)
        self.settings_steps=QListWidget()
        self.settings_steps.setSpacing(1)
        self.settings_steps.setCursor(Qt.PointingHandCursor)
        self.settings_steps.setAccessibleName("ขั้นตอนงาน")
        self.settings_steps.setSelectionMode(QAbstractItemView.SingleSelection)
        self.settings_steps.currentRowChanged.connect(self.select_step)
        self.settings_files=QListWidget()
        self.settings_files.setSpacing(1)
        self.settings_files.setCursor(Qt.PointingHandCursor)
        self.settings_files.setAccessibleName("ไฟล์ของขั้นตอน")
        self.settings_files.itemChanged.connect(self.toggle_file)
        self.settings_lists=(self.settings_profiles,self.settings_steps,self.settings_files)

        def management_tab(title,widget,buttons):
            tab=QWidget()
            layout=QVBoxLayout(tab)
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
            tabs.addTab(tab,title)

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
        management_tab("นิยาย",self.settings_profiles,profile_actions)
        management_tab("ขั้นตอน",self.settings_steps,step_actions)
        management_tab("ไฟล์ของขั้นตอน",self.settings_files,file_actions)

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
        buttons.accepted.connect(lambda:self._save_settings_page(appearance,separator,checks))
        buttons.rejected.connect(lambda:self.main_tabs.setCurrentWidget(self.workspace_page))
        buttons.button(QDialogButtonBox.Save).setText("บันทึกการตั้งค่า")
        buttons.button(QDialogButtonBox.Close).setText("กลับไปทำงาน")
        root.addWidget(buttons)

        self.settings_page=page
        self.main_tabs.addTab(page,"ตั้งค่า")
        self.refresh_profiles(previous_profile_id)
        if self.profile and self.profile.workflow.steps:
            restored=next((i for i,step in enumerate(self.profile.workflow.steps) if step.id==active_step_id),0)
            self.steps.setCurrentRow(restored)
        self.main_tabs.setCurrentWidget(page)

    def _save_settings_page(self,appearance,separator,checks):
        self.settings.appearance=appearance.currentText()
        self.settings.separator=separator.text()
        for check,attr in checks:
            setattr(self.settings,attr,check.isChecked())
        try:
            self.repo.save_settings(self.settings)
        except OSError as exc:
            QMessageBox.warning(self,"บันทึกการตั้งค่าไม่สำเร็จ",str(exc))
            return
        self.apply_theme()
        self.statusBar().showMessage("บันทึกการตั้งค่าแล้ว",2500)

    def _restore_active_step(self,step_id=None):
        if not self.profile or not self.profile.workflow.steps:
            self.si=-1
            self.refresh_files()
            return
        row=next((i for i,step in enumerate(self.profile.workflow.steps) if step.id==step_id),0)
        self.steps.setCurrentRow(row)

    def on_main_tab_changed(self,index):
        current=self.main_tabs.widget(index)
        key=self.page_keys.get(id(current),"")
        if key.startswith(("novel:","files:","launcher:","preview:")):
            profile_id=key.split(":",2)[1]
            self.set_profile_by_id(profile_id)
        nav_key=key.split(":",1)[0] if key.startswith(("novel:","files:","launcher:","preview:")) else key
        if nav_key in ("workflow","novel"):nav_key="novels"
        if nav_key in self.nav_buttons:self.nav_buttons[nav_key].setChecked(True)
        settings_lists=getattr(self,"settings_lists",None)
        if settings_lists is not None:
            using_settings=self.profiles is settings_lists[0]
            if current is self.settings_page and not using_settings:
                profile_id=self.profile.id if self.profile else None
                active=self.step()
                step_id=active.id if active else None
                self.profiles,self.steps,self.files=settings_lists
                self.refresh_profiles(profile_id)
                self._restore_active_step(step_id)
            elif current is not self.settings_page and using_settings:
                profile_id=self.profile.id if self.profile else None
                active=self.step()
                step_id=active.id if active else None
                self.profiles,self.steps,self.files=self.workspace_lists
                self.refresh_profiles(profile_id)
                self._restore_active_step(step_id)
        if current is self.dashboard_page:
            self.refresh_translation_progress()

    def groups_dialog(self):
        key="groups"
        if key in self.pages:
            self.main_tabs.setCurrentWidget(self.pages[key]);self._refresh_groups_page();return
        page=QWidget();root=QVBoxLayout(page);root.setContentsMargins(20,18,20,18);root.setSpacing(10)
        heading=QLabel("กลุ่มนิยาย");heading.setObjectName("pageTitle");root.addWidget(heading)
        row=QHBoxLayout();selector=QListWidget();selector.setMaximumWidth(240);details=QWidget();form=QVBoxLayout(details)
        name=QLineEdit();name.setPlaceholderText("ชื่อกลุ่ม");members=QListWidget();members.setAccessibleName("นิยายในกลุ่ม")
        form.addWidget(QLabel("ชื่อกลุ่ม"));form.addWidget(name);form.addWidget(QLabel("สมาชิก"));form.addWidget(members,1)
        row.addWidget(selector);row.addWidget(details,1);root.addLayout(row,1)
        self.groups_page=page;self.groups_selector=selector;self.groups_name=name;self.groups_members=members
        actions=QHBoxLayout()
        for label,fn in (("สร้างกลุ่ม",self._new_group_page),("ลบกลุ่ม",self._delete_group_page),("บันทึก",self._save_group_page),("เปิดกลุ่ม",self._launch_group_page)):
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        actions.addStretch(1);root.addLayout(actions)
        selector.currentRowChanged.connect(self._show_group_page)
        self.add_workspace_tab(key,"กลุ่มนิยาย",page,True);self._refresh_groups_page()

    def _refresh_groups_page(self):
        if not hasattr(self,"groups_selector"):return
        groups=self.repo.load_groups();selected=self.groups_selector.currentItem().data(Qt.UserRole) if self.groups_selector.currentItem() else None
        self._groups_cache=groups;self.groups_selector.blockSignals(True);self.groups_selector.clear()
        for group in groups:
            row=QListWidgetItem(group.name);row.setData(Qt.UserRole,group.id);self.groups_selector.addItem(row)
        target=next((i for i,g in enumerate(groups) if g.id==selected),0 if groups else -1)
        self.groups_selector.setCurrentRow(target);self.groups_selector.blockSignals(False);self._show_group_page(target)

    def _show_group_page(self,index):
        if not hasattr(self,"groups_members"):return
        self.groups_members.clear();groups=getattr(self,"_groups_cache",[])
        current=groups[index] if 0<=index<len(groups) else None
        self.groups_name.setText(current.name if current else "");self.groups_name.setEnabled(current is not None)
        for profile in self.repo.list_profiles():
            item=QListWidgetItem(profile.name);item.setData(Qt.UserRole,profile.id);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if current and profile.id in current.profile_ids else Qt.Unchecked);self.groups_members.addItem(item)

    def _save_group_page(self):
        row=self.groups_selector.currentRow();groups=getattr(self,"_groups_cache",[])
        if not 0<=row<len(groups):return
        group=groups[row];group.name=self.groups_name.text().strip() or group.name;group.profile_ids=[self.groups_members.item(i).data(Qt.UserRole) for i in range(self.groups_members.count()) if self.groups_members.item(i).checkState()==Qt.Checked]
        self.repo.save_groups(groups);self._refresh_groups_page();self.statusBar().showMessage("บันทึกกลุ่มแล้ว",2500)

    def _new_group_page(self):
        name,ok=QInputDialog.getText(self,"สร้างกลุ่ม","ชื่อกลุ่ม:")
        if not ok or not name.strip():return
        groups=self.repo.load_groups();groups.append(NovelGroup(name=name.strip(),order=len(groups)));self.repo.save_groups(groups);self._refresh_groups_page();self.groups_selector.setCurrentRow(len(groups)-1)

    def _delete_group_page(self):
        row=self.groups_selector.currentRow();groups=getattr(self,"_groups_cache",[])
        if not 0<=row<len(groups):return
        group=groups[row]
        if QMessageBox.question(self,"ลบกลุ่ม",f"ลบกลุ่ม {group.name}?")!=QMessageBox.Yes:return
        groups.pop(row);self.repo.save_groups(groups);self._refresh_groups_page()

    def _launch_group_page(self):
        self._save_group_page();row=self.groups_selector.currentRow();groups=getattr(self,"_groups_cache",[])
        if not 0<=row<len(groups):return
        results=self.launcher.launch_group(groups[row],self.repo.list_profiles());failures=[m for ok,m in results if not ok];succeeded=sum(1 for ok,_ in results if ok)
        if failures:QMessageBox.warning(self,"เปิดกลุ่ม",f"เปิดสำเร็จ {succeeded} รายการ\n\n"+"\n".join(failures))
        else:self.statusBar().showMessage(f"เปิดกลุ่ม {groups[row].name} แล้ว",4000)

    def file_manager(self):
        if not self.profile:
            self.statusBar().showMessage("เลือกรายการนิยายก่อนเปิดไฟล์",3000);return
        key="files:"+self.profile.id
        if key in self.pages:
            self.main_tabs.setCurrentWidget(self.pages[key]);return
        page=QWidget();root=QVBoxLayout(page);root.setContentsMargins(16,14,16,14);root.setSpacing(8)
        title=QLabel("ไฟล์ · "+self.profile.name);title.setObjectName("pageTitle");root.addWidget(title)
        split=QSplitter();split.setChildrenCollapsible(False)
        left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,0,0);search=QLineEdit();search.setPlaceholderText("ค้นหาไฟล์");listing=QListWidget();listing.setSelectionMode(QAbstractItemView.ExtendedSelection);ll.addWidget(search);ll.addWidget(listing,1)
        right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(16,8,0,8);path_label=QLabel("เลือกไฟล์ที่ต้องการเปิด");path_label.setObjectName("pageTitle");rl.addWidget(path_label);hint=QLabel("เลือกได้หลายไฟล์พร้อมกัน แล้วกด “เปิดไฟล์ที่เลือก” เพื่อเปิดด้วยโปรแกรมเริ่มต้นของ Windows.");hint.setObjectName("mutedLabel");hint.setWordWrap(True);rl.addWidget(hint);rl.addStretch(1)
        split.addWidget(left);split.addWidget(right);split.setSizes([520,560]);root.addWidget(split,1)
        actions=QHBoxLayout()
        for label,fn in (("เปิดไฟล์ที่เลือก",lambda:self._files_open_selected(key)),("ลบไฟล์ที่เลือก",lambda:self._files_delete_selected(key)),("สร้างไฟล์",lambda:self._files_create(key)),("นำเข้าไฟล์",lambda:self._files_import(key)),("แนบกับขั้นตอน",lambda:self._files_attach(key))):
            button=QPushButton(label);button.clicked.connect(fn);actions.addWidget(button)
        actions.addStretch(1);root.addLayout(actions)
        state={"key":key,"profile_id":self.profile.id,"page":page,"title":title,"search":search,"list":listing,"path":path_label,"selected":None}
        self._files_states=getattr(self,"_files_states",{});self._files_states[key]=state
        search.textChanged.connect(lambda:self._refresh_files_page(key));listing.currentItemChanged.connect(lambda *_:self._files_select(key))
        listing.setContextMenuPolicy(Qt.CustomContextMenu);listing.customContextMenuRequested.connect(lambda point:self._files_context_menu(key,point))
        self.add_workspace_tab(key,"ไฟล์ · "+self.profile.name,page,True);self._refresh_files_page(key)

    def _files_root(self,key):
        state=self._files_states.get(key);return self.repo.profile_dir(state["profile_id"]) if state else None

    def _refresh_files_page(self,key):
        state=getattr(self,"_files_states",{}).get(key)
        if not state:return
        listing=state["list"];selected=state.get("selected");listing.blockSignals(True);listing.clear();root=self._files_root(key);query=state["search"].text().lower()
        if root and root.exists():
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.name!="profile.json":
                    rel=path.relative_to(root).as_posix()
                    if query in rel.lower():
                        item=QListWidgetItem(rel);item.setData(Qt.UserRole,rel);listing.addItem(item)
                        if rel==selected:listing.setCurrentItem(item)
        listing.blockSignals(False)
        if listing.currentItem():self._files_select(key)
        elif selected:state["selected"]=None;state["path"].setText("เลือกไฟล์ที่ต้องการเปิด")

    def _files_select(self,key):
        state=self._files_states.get(key);row=state["list"].currentItem() if state else None
        if not state or not row:return
        rel=row.data(Qt.UserRole);state["selected"]=rel
        count=len(state["list"].selectedItems())
        state["path"].setText(f"เลือกแล้ว {count} ไฟล์" if count>1 else rel)

    def _files_open_selected(self,key):
        state=self._files_states.get(key)
        if not state:return
        selected=state["list"].selectedItems()
        if not selected:
            self.statusBar().showMessage("เลือกไฟล์ที่ต้องการเปิดก่อน",2500);return
        opened=0
        for item in selected:
            try:
                path=self.repo.resolve_project_path(state["profile_id"],item.data(Qt.UserRole))
                if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):opened+=1
            except (OSError,ValueError):
                continue
        self.statusBar().showMessage(f"เปิดไฟล์แล้ว {opened} จาก {len(selected)} ไฟล์",3500)

    def _files_dirty(self,state):return False

    def _files_save(self,key,ask=False):
        state=self._files_states.get(key)
        if not state or not self._files_dirty(state):return True
        if ask:
            answer=QMessageBox.question(self,"บันทึกการแก้ไข", "บันทึกการเปลี่ยนแปลงก่อนหรือไม่?",QMessageBox.Save|QMessageBox.Discard|QMessageBox.Cancel)
            if answer==QMessageBox.Cancel:return False
            if answer==QMessageBox.Discard:state["editor"].setPlainText(state["original_content"]);return True
        try:content=state["editor"].toPlainText();self.repo.resolve_project_path(state["profile_id"],state["selected"]).write_text(content,encoding="utf-8");state["original_content"]=content;state["dirty"].setText("บันทึกแล้ว");self.statusBar().showMessage("บันทึกไฟล์แล้ว",2000);return True
        except (OSError,ValueError) as exc:QMessageBox.warning(self,"บันทึกไฟล์ไม่สำเร็จ",str(exc));return False

    def _files_context_menu(self,key,point):
        state=self._files_states.get(key)
        if not state:return
        menu=QMenu(state["list"])
        for label,fn in (("แนบกับขั้นตอนที่เลือก",lambda:self._files_attach(key)),("เปลี่ยนชื่อ",lambda:self._files_rename(key)),("ลบไฟล์",lambda:self._files_delete(key))):menu.addAction(label,fn)
        menu.exec(state["list"].mapToGlobal(point))

    def _files_create(self,key):
        rel,ok=QInputDialog.getText(self,"สร้างไฟล์ข้อความ","ตำแหน่งไฟล์ใหม่ (.txt, .md หรือ .json):")
        if not ok or not rel:return
        if Path(rel).suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(self,"ชนิดไฟล์ไม่รองรับ","ใช้ไฟล์ .txt, .md หรือ .json");return
        try:path=self.repo.resolve_project_path(self._files_states[key]["profile_id"],rel)
        except ValueError as exc:QMessageBox.warning(self,"ตำแหน่งไม่ถูกต้อง",str(exc));return
        if path.exists():QMessageBox.warning(self,"มีไฟล์นี้แล้ว","เลือกชื่อหรือตำแหน่งใหม่");return
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text("",encoding="utf-8");self._refresh_files_page(key)

    def _files_import(self,key):
        source,_=QFileDialog.getOpenFileName(self,"นำเข้าไฟล์","","Text files (*.txt *.md *.json)")
        if not source:return
        src=Path(source)
        if src.suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(self,"ชนิดไฟล์ไม่รองรับ","ใช้ไฟล์ .txt, .md หรือ .json");return
        rel,ok=QInputDialog.getText(self,"นำเข้าไฟล์","ตำแหน่งปลายทาง:",text="reference/"+src.name)
        if not ok:return
        try:dest=self.repo.resolve_project_path(self._files_states[key]["profile_id"],rel)
        except ValueError as exc:QMessageBox.warning(self,"ตำแหน่งไม่ถูกต้อง",str(exc));return
        if dest.exists():QMessageBox.warning(self,"มีไฟล์นี้แล้ว","จะไม่เขียนทับไฟล์เดิม");return
        import shutil;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest);self._refresh_files_page(key)

    def _files_rename(self,key):
        state=self._files_states.get(key);old=state.get("selected") if state else None
        if not old:return
        rel,ok=QInputDialog.getText(self,"เปลี่ยนชื่อไฟล์","ตำแหน่งใหม่:",text=old)
        if not ok or not rel:return
        try:src=self.repo.resolve_project_path(state["profile_id"],old);dest=self.repo.resolve_project_path(state["profile_id"],rel)
        except ValueError as exc:QMessageBox.warning(self,"ตำแหน่งไม่ถูกต้อง",str(exc));return
        if dest.exists():QMessageBox.warning(self,"มีไฟล์นี้แล้ว","จะไม่เขียนทับไฟล์เดิม");return
        dest.parent.mkdir(parents=True,exist_ok=True);src.rename(dest);profile=next((p for p in self.ps_list if p.id==state["profile_id"]),None)
        if profile:
            for step in profile.workflow.steps:
                for item in step.files:
                    if item.path==old:item.path=dest.relative_to(self.repo.profile_dir(profile.id)).as_posix()
            self.repo.save_profile(profile)
        state["selected"]=dest.relative_to(self.repo.profile_dir(state["profile_id"])).as_posix();self._refresh_files_page(key)

    def _files_delete(self,key):
        state=self._files_states.get(key);rel=state.get("selected") if state else None
        if not rel:return
        if QMessageBox.question(self,"ลบไฟล์",f"ลบ {Path(rel).name}? ")!=QMessageBox.Yes:return
        path=self.repo.resolve_project_path(state["profile_id"],rel);path.unlink(missing_ok=True);profile=next((p for p in self.ps_list if p.id==state["profile_id"]),None)
        if profile:
            for step in profile.workflow.steps:step.files=[f for f in step.files if f.reference_type=="external_file" or not f.path or self.repo.resolve_project_path(profile.id,f.path)!=path]
            self.repo.save_profile(profile)
        state["selected"]=None;self.refresh_files_page(key);self.refresh_files()

    def _files_delete_selected(self,key):
        state=self._files_states.get(key)
        if not state:return
        rows=state["list"].selectedItems()
        if not rows:
            self.statusBar().showMessage("เลือกไฟล์ที่ต้องการลบก่อน",2500);return
        paths=[]
        for row in rows:
            try:paths.append(self.repo.resolve_project_path(state["profile_id"],row.data(Qt.UserRole)))
            except ValueError:continue
        if not paths:return
        answer=QMessageBox.question(self,"ลบไฟล์ที่เลือก",f"ยืนยันลบ {len(paths)} ไฟล์ที่เลือกหรือไม่?",QMessageBox.Yes|QMessageBox.No)
        if answer!=QMessageBox.Yes:return
        profile=next((p for p in self.ps_list if p.id==state["profile_id"]),None)
        removed=set()
        for path in paths:
            try:
                path.unlink(missing_ok=True);removed.add(path)
            except OSError as exc:
                QMessageBox.warning(self,"ลบไฟล์ไม่สำเร็จ",f"{path.name}: {exc}")
        if profile and removed:
            for step in profile.workflow.steps:
                step.files=[item for item in step.files if item.reference_type=="external_file" or not item.path or self.repo.resolve_project_path(profile.id,item.path) not in removed]
            self.repo.save_profile(profile)
        state["selected"]=None;self._refresh_files_page(key);self.refresh_files()
        self.statusBar().showMessage(f"ลบไฟล์แล้ว {len(removed)} ไฟล์",3000)

    def _files_attach(self,key):
        state=self._files_states.get(key);rel=state.get("selected") if state else None
        if not state or not rel or not self.step():return
        profile=next((p for p in self.ps_list if p.id==state["profile_id"]),None)
        if not profile:return
        if any(f.path==rel for f in self.step().files):self.statusBar().showMessage("ไฟล์นี้อยู่ในขั้นตอนแล้ว",2500);return
        path=self.repo.resolve_project_path(profile.id,rel);self.step().files.append(StepFile(label=path.stem,path=rel,file_type=path.parent.name,order=len(self.step().files)));self.save();self.refresh_files()

    def launcher_dialog(self):
        if not self.profile:return
        profile=self.profile;key="launcher:"+profile.id
        if key in self.pages:self.main_tabs.setCurrentWidget(self.pages[key]);return
        page=QWidget();root=QVBoxLayout(page);root.setContentsMargins(20,18,20,18);title=QLabel("ตัวเปิดไฟล์ · "+profile.name);title.setObjectName("pageTitle");root.addWidget(title)
        folder=QLineEdit(profile.main_folder);folder.setPlaceholderText("โฟลเดอร์หลักของนิยาย");browse=QPushButton("เลือกโฟลเดอร์");folderrow=QHBoxLayout();folderrow.addWidget(folder,1);folderrow.addWidget(browse);root.addLayout(folderrow)
        listing=QListWidget();root.addWidget(listing,1);targets=[LaunchTarget.from_dict(asdict_target(item)) for item in profile.launch_targets]
        def refresh():
            listing.clear()
            for target in sorted(targets,key=lambda x:x.order):
                item=QListWidgetItem(f"{target.label}  ·  {target.target}");item.setData(Qt.UserRole,target.id);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if target.enabled else Qt.Unchecked);listing.addItem(item)
        browse.clicked.connect(lambda:folder.setText(QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์นิยาย",folder.text()) or folder.text()))
        actions=QHBoxLayout()
        for label,kind in (("เพิ่มโปรแกรม","application"),("เพิ่มไฟล์","file"),("เพิ่มโฟลเดอร์","folder"),("เพิ่มเว็บไซต์","website")):
            button=QPushButton(label);button.clicked.connect(lambda checked=False,k=kind:self._launcher_add_target(targets,k,refresh));actions.addWidget(button)
        remove=QPushButton("เอาออก");remove.clicked.connect(lambda:targets.__setitem__(slice(None),[t for t in targets if not listing.currentItem() or t.id!=listing.currentItem().data(Qt.UserRole)]));remove.clicked.connect(refresh);actions.addWidget(remove)
        save=QPushButton("บันทึก");save.setObjectName("primaryButton");save.clicked.connect(lambda:self._launcher_save(profile,folder,listing,targets));actions.addWidget(save);actions.addStretch(1);root.addLayout(actions);refresh()
        self.add_workspace_tab(key,"ตัวเปิดไฟล์ · "+profile.name,page,True)

    def _launcher_add_target(self,targets,kind,refresh):
        if kind=="application":target,_=QFileDialog.getOpenFileName(self,"เลือกโปรแกรม","","Applications (*.exe);;All files (*)")
        elif kind=="folder":target=QFileDialog.getExistingDirectory(self,"เลือกโฟลเดอร์")
        elif kind=="website":target,ok=QInputDialog.getText(self,"เพิ่มเว็บไซต์","URL (http/https):");target=target if ok else ""
        else:target,_=QFileDialog.getOpenFileName(self,"เลือกไฟล์")
        if not target:return
        label=Path(target).stem if kind!="website" else target
        if kind=="website":label,ok=QInputDialog.getText(self,"ชื่อเว็บไซต์","ชื่อ:",text=target);label=label if ok else ""
        if label:targets.append(LaunchTarget(label=label,kind=kind,target=target,order=len(targets)));refresh()

    def _launcher_save(self,profile,folder,listing,targets):
        for i in range(listing.count()):
            row=listing.item(i);target=next((t for t in targets if t.id==row.data(Qt.UserRole)),None)
            if target:target.enabled=row.checkState()==Qt.Checked;target.order=i
        profile.main_folder=folder.text().strip();profile.launch_targets=targets;self.repo.save_profile(profile);self.statusBar().showMessage("บันทึกตัวเปิดไฟล์แล้ว",2500)

    def preview(self):
        if not self.step() or not self.profile:return
        try:text=self.assembler.assemble(self.profile,self.step(),self.settings.separator,self.settings.show_filename_heading)
        except Exception as exc:QMessageBox.warning(self,"ดูตัวอย่างไม่ได้",str(exc));return
        key=f"preview:{self.profile.id}:{self.step().id}"
        if key in self.pages:
            state=self._preview_states[key];state["text"]=text;state["view"].setPlainText(text);state["title"].setText(f"ตัวอย่าง · {self.profile.name} / {self.step().name}");state["count"].setText(f"{len(text):,} ตัวอักษร");self.main_tabs.setCurrentWidget(self.pages[key]);return
        page=QWidget();layout=QVBoxLayout(page);layout.setContentsMargins(18,16,18,16);title=QLabel(f"ตัวอย่าง · {self.profile.name} / {self.step().name}");title.setObjectName("pageTitle");layout.addWidget(title)
        view=QPlainTextEdit();view.setReadOnly(True);view.setPlainText(text);layout.addWidget(view,1);bar=QHBoxLayout();count=QLabel(f"{len(text):,} ตัวอักษร");bar.addWidget(count);bar.addStretch(1);copy=QPushButton("คัดลอกเนื้อหา");bar.addWidget(copy);layout.addLayout(bar)
        self._preview_states=getattr(self,"_preview_states",{});state={"text":text,"view":view,"title":title,"count":count};self._preview_states[key]=state;copy.clicked.connect(lambda:self.copy_text(state["text"]))
        self.add_workspace_tab(key,"ตัวอย่าง · "+self.step().name,page,True)

    def settings_dialog(self):
        key="settings"
        if key in self.pages:self.main_tabs.setCurrentWidget(self.pages[key]);return
        page=QWidget();root=QVBoxLayout(page);root.setContentsMargins(22,20,22,20);root.setSpacing(12);title=QLabel("ตั้งค่า");title.setObjectName("pageTitle");root.addWidget(title)
        appearance=QComboBox();appearance.addItems(["System","Light","Dark"]);appearance.setCurrentText(self.settings.appearance);root.addWidget(QLabel("รูปลักษณ์"));root.addWidget(appearance)
        separator=QLineEdit(self.settings.separator);root.addWidget(QLabel("ตัวคั่นเนื้อหา (ใช้ {FILE_NAME})"));root.addWidget(separator)
        checks=[]
        for label,attr in (("แสดงชื่อไฟล์","show_filename_heading"),("ยืนยันก่อนลบ","confirm_before_deleting"),("เปิดนิยายล่าสุดเมื่อเริ่มโปรแกรม","open_last_profile")):
            check=QCheckBox(label);check.setChecked(getattr(self.settings,attr));root.addWidget(check);checks.append((check,attr))
        save=QPushButton("บันทึกการตั้งค่า");save.setObjectName("primaryButton");root.addWidget(save);root.addStretch(1);save.clicked.connect(lambda:self._save_settings_page(appearance,separator,checks));self.add_workspace_tab(key,"ตั้งค่า",page,True)

    def file(self):return self.step().files[self.files.currentRow()] if self.step() and 0<=self.files.currentRow()<len(self.step().files) else None
    def edit_file(self):self.file_manager()

    def delete_profile(self):
        if not self.profile:return
        profile_id=self.profile.id
        if QMessageBox.question(self,"ลบนิยาย",f"ลบ {self.profile.name} และไฟล์ทั้งหมดของเรื่องนี้?")!=QMessageBox.Yes:return
        keys=[key for key in self.pages if key.startswith((f"novel:{profile_id}",f"files:{profile_id}",f"launcher:{profile_id}",f"preview:{profile_id}:"))]
        for key in keys:
            index=self.main_tabs.indexOf(self.pages[key])
            if index>=0:self.close_workspace_tab(index)
            if key in self.pages:return
        self.repo.delete_profile(profile_id);self.profile=None;self.refresh_profiles()
