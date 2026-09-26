from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import *
from .models import AppSettings, StepFile, Workflow
from .services import ProfileService, WorkflowService, AssemblyService
from .storage import ProjectRepository

class Editor(QDialog):
    def __init__(self,parent,title,text=""):
        super().__init__(parent);self.setWindowTitle(title);self.resize(760,560);lay=QVBoxLayout(self)
        self.edit=QTextEdit();self.edit.setPlainText(text);lay.addWidget(self.edit)
        buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);lay.addWidget(buttons)
        self.edit.addAction(QAction(self.edit,shortcut=QKeySequence.Save,triggered=self.accept))
    def text(self):return self.edit.toPlainText()

class MainWindow(QMainWindow):
    def __init__(self,repo=None):
        super().__init__();self.repo=repo or ProjectRepository();self.ps=ProfileService(self.repo);self.assembler=AssemblyService(self.repo);self.settings=self.repo.load_settings();self.profile=None;self.si=-1
        self.setWindowTitle("Novel Translation Workflow Manager");self.resize(1180,720);self.build();self.refresh_profiles()
    def build(self):
        bar=self.addToolBar("Navigation");bar.setMovable(False);bar.addWidget(QLabel("Novel: "));self.novel=QLabel("None");bar.addWidget(self.novel);bar.addSeparator();bar.addWidget(QLabel("Chapter: "))
        self.chapter=QSpinBox();self.chapter.setMinimum(1);self.chapter.valueChanged.connect(self.chapter_changed);bar.addWidget(self.chapter)
        for label,fn in (("◀",lambda:self.chapter.setValue(max(1,self.chapter.value()-1))),("▶",lambda:self.chapter.setValue(self.chapter.value()+1)),("Settings",self.settings_dialog)):
            a=QAction(label,self);a.triggered.connect(fn);bar.addAction(a)
        splitter=QSplitter();self.setCentralWidget(splitter)
        self.profiles=QListWidget();self.profiles.currentRowChanged.connect(self.select_profile);splitter.addWidget(self.column("PROFILES",self.profiles,[("New Profile",self.new_profile),("Duplicate",self.duplicate_profile),("Rename",self.rename_profile),("Delete",self.delete_profile)]))
        self.steps=QListWidget();self.steps.currentRowChanged.connect(self.select_step);splitter.addWidget(self.column("WORKFLOW STEPS",self.steps,[("Add Step",self.add_step),("Rename",self.rename_step),("Duplicate",self.duplicate_step),("Delete",self.delete_step),("Move Up",lambda:self.move_step(-1)),("Move Down",lambda:self.move_step(1)),("Save as Template",self.save_template)]))
        self.files=QListWidget();self.files.itemChanged.connect(self.toggle_file);splitter.addWidget(self.column("STEP FILES",self.files,[("Add File",self.add_file),("Add Dynamic Chapter",self.add_dynamic),("Remove from Step",self.remove_file),("Move File Up",lambda:self.move_file(-1)),("Move File Down",lambda:self.move_file(1)),("Rename Label",self.rename_file_label),("File Manager",self.file_manager),("Preview",self.preview),("COPY STEP",self.copy_step)]));splitter.setSizes([240,300,640])
        self.statusBar();self.shortcut("Ctrl+Shift+C",self.copy_step);self.shortcut("Ctrl+P",self.preview);self.shortcut("Ctrl+R",self.refresh);self.shortcut("Ctrl+S",self.save)
    def column(self,title,widget,buttons):
        w=QWidget();l=QVBoxLayout(w);l.addWidget(QLabel("<b>"+title+"</b>"));l.addWidget(widget,1)
        for label,fn in buttons:b=QPushButton(label);b.clicked.connect(fn);l.addWidget(b)
        return w
    def shortcut(self,key,fn):a=QAction(self);a.setShortcut(QKeySequence(key));a.triggered.connect(fn);self.addAction(a)
    def refresh(self):self.refresh_profiles(self.profile.id if self.profile else None)
    def refresh_profiles(self,pid=None):
        self.ps_list=self.repo.list_profiles();self.profiles.blockSignals(True);self.profiles.clear()
        for p in self.ps_list:self.profiles.addItem(p.name)
        idx=next((i for i,p in enumerate(self.ps_list) if p.id==(pid or (self.settings.last_profile_id if self.settings.open_last_profile else None))),0 if self.ps_list else -1);self.profiles.setCurrentRow(idx);self.profiles.blockSignals(False)
        if idx>=0:self.select_profile(idx)
        else:self.profile=None;self.novel.setText("None");self.refresh_steps()
    def select_profile(self,i):
        if i<0 or i>=len(getattr(self,"ps_list",[])):return
        self.profile=self.ps_list[i];self.settings.last_profile_id=self.profile.id;self.novel.setText(self.profile.name)
        self.chapter.blockSignals(True);self.chapter.setValue(self.profile.chapter_state.current_chapter);self.chapter.blockSignals(False);self.refresh_steps()
    def refresh_steps(self):
        self.steps.blockSignals(True);self.steps.clear()
        if self.profile:
            for i,s in enumerate(self.profile.workflow.steps):self.steps.addItem(f"{i+1}. {s.name}")
        self.steps.blockSignals(False);self.steps.setCurrentRow(0 if self.profile and self.profile.workflow.steps else -1);self.refresh_files()
    def select_step(self,i):self.si=i;self.refresh_files()
    def step(self):return self.profile.workflow.steps[self.si] if self.profile and 0<=self.si<len(self.profile.workflow.steps) else None
    def refresh_files(self):
        self.files.blockSignals(True);self.files.clear();s=self.step()
        if s:
            for f in sorted(s.files,key=lambda x:x.order):
                row=QListWidgetItem(f.label or f.path or f.dynamic_reference);row.setFlags(row.flags()|Qt.ItemIsUserCheckable);row.setCheckState(Qt.Checked if f.enabled else Qt.Unchecked);row.setData(Qt.UserRole,f.id);self.files.addItem(row)
        self.files.blockSignals(False)
    def save(self):
        if self.profile:self.repo.save_profile(self.profile)
        self.repo.save_settings(self.settings);self.statusBar().showMessage("Saved",2000)
    def chapter_changed(self,n):
        if self.profile:self.profile.chapter_state.current_chapter=n;self.save()
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
        src,_=QFileDialog.getOpenFileName(self,"Import file","","Text files (*.txt *.md *.json)")
        if not src:return
        p=Path(src)
        if p.suffix.lower() not in (".txt",".md",".json"):QMessageBox.warning(self,"Unsupported","Choose .txt, .md, or .json.");return
        label,ok=QInputDialog.getText(self,"File label","Display name:",text=p.stem)
        if not ok:return
        rel="reference/"+p.name;dst=self.repo.resolve_project_path(self.profile.id,rel);dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():QMessageBox.warning(self,"Exists","That filename already exists.");return
        import shutil;shutil.copy2(p,dst);self.step().files.append(StepFile(label=label or p.stem,path=rel,file_type="reference",order=len(self.step().files)));self.save();self.refresh_files()
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
                rel=str(path.relative_to(root)).replace("\\\\","/")
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
            old=str(path.relative_to(root)).replace("\\\\","/");dest.parent.mkdir(parents=True,exist_ok=True);path.rename(dest)
            new=str(dest.relative_to(root)).replace("\\\\","/")
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
                    step.files=[item for item in step.files if not item.path or self.repo.resolve_project_path(self.profile.id,item.path)!=path]
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
        for label,fn in (("New",create),("Import",import_file),("Edit",edit),("Rename",rename),("Delete",delete)):
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
        path=self.repo.resolve_project_path(self.profile.id,f.path);dlg=Editor(self,"Edit "+f.label,path.read_text(encoding="utf-8") if path.exists() else "")
        if dlg.exec()==QDialog.Accepted:path.write_text(dlg.text(),encoding="utf-8");self.save()
    def preview(self):
        if not self.step():return
        try:text=self.assembler.assemble(self.profile,self.step(),self.settings.separator,self.settings.show_filename_heading)
        except Exception as e:QMessageBox.warning(self,"Preview unavailable",str(e));return
        dlg=QDialog(self);dlg.setWindowTitle("Preview: "+self.step().name);dlg.resize(850,650);l=QVBoxLayout(dlg);view=QTextEdit();view.setReadOnly(True);view.setPlainText(text);l.addWidget(view);l.addWidget(QLabel(f"{len(text):,} characters"))
        buttons=QDialogButtonBox(QDialogButtonBox.Close);copy=buttons.addButton("Copy All",QDialogButtonBox.ActionRole);copy.clicked.connect(lambda:self.copy_text(text));buttons.rejected.connect(dlg.reject);l.addWidget(buttons);dlg.exec()
    def copy_text(self,text):QApplication.clipboard().setText(text);self.statusBar().showMessage("Copied to clipboard",2500)
    def copy_step(self):
        if not self.step():return
        try:
            text=self.assembler.assemble(self.profile,self.step(),self.settings.separator,self.settings.show_filename_heading);self.copy_text(text);QMessageBox.information(self,"Copied",f"Copied: {self.step().name}\n{len(text):,} characters")
        except Exception as e:QMessageBox.warning(self,"Copy failed",str(e))
    def settings_dialog(self):
        d=QDialog(self);d.setWindowTitle("Settings");l=QVBoxLayout(d);appearance=QComboBox();appearance.addItems(["System","Light","Dark"]);appearance.setCurrentText(self.settings.appearance);l.addWidget(QLabel("Appearance"));l.addWidget(appearance)
        separator=QLineEdit(self.settings.separator);l.addWidget(QLabel("Separator (use {FILE_NAME})"));l.addWidget(separator)
        checks=[]
        for label,attr in (("Show filename heading","show_filename_heading"),("Confirm before deleting","confirm_before_deleting"),("Open last profile on startup","open_last_profile")):
            c=QCheckBox(label);c.setChecked(getattr(self.settings,attr));l.addWidget(c);checks.append((c,attr))
        b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);b.accepted.connect(d.accept);b.rejected.connect(d.reject);l.addWidget(b)
        if d.exec()==QDialog.Accepted:
            self.settings.appearance=appearance.currentText();self.settings.separator=separator.text()
            for c,a in checks:setattr(self.settings,a,c.isChecked())
            self.save()
