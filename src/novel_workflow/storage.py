import json, os, re, tempfile
from pathlib import Path
from dataclasses import asdict
from .models import AppSettings, NovelProfile, Workflow, WorkflowTemplate

def data_root():
    return Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"NovelTranslationWorkflowManager"

def read_json(path, default):
    if not path.exists(): return default
    raw=path.read_text(encoding="utf-8")
    try: return json.loads(raw)
    except json.JSONDecodeError as exc:
        fixed=re.sub(r",\s*([}\]])",r"\1",raw)
        if fixed==raw: raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
        with tempfile.NamedTemporaryFile("w",encoding="utf-8",suffix=".json",delete=False) as f:
            f.write(fixed); temp=Path(f.name)
        try: return json.loads(temp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as err: raise ValueError(f"Could not safely recover {path}: {err}") from err
        finally: temp.unlink(missing_ok=True)

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(value,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)

class ProjectRepository:
    CATEGORIES=("prompts","glossary","characters","style","source","translated","reviewed","notes","reference","custom")
    def __init__(self,root=None):
        self.root=Path(root) if root else data_root(); self.profiles_dir=self.root/"profiles"
        self.settings_path=self.root/"settings.json"; self.templates_path=self.root/"templates.json"
        self.profiles_dir.mkdir(parents=True,exist_ok=True)
    def profile_dir(self,pid):
        if not re.fullmatch(r"[a-fA-F0-9]{32}",pid): raise ValueError("Invalid profile ID")
        return self.profiles_dir/pid
    def list_profiles(self):
        return [NovelProfile.from_dict(read_json(p/"profile.json",{})) for p in sorted(self.profiles_dir.iterdir()) if (p/"profile.json").is_file()]
    def save_profile(self,p):
        folder=self.profile_dir(p.id); folder.mkdir(parents=True,exist_ok=True)
        for c in self.CATEGORIES: (folder/c).mkdir(exist_ok=True)
        write_json(folder/"profile.json",asdict(p))
    def delete_profile(self,pid):
        import shutil; shutil.rmtree(self.profile_dir(pid))
    def resolve_project_path(self,pid,rel):
        root=self.profile_dir(pid).resolve(); target=(root/rel).resolve()
        if target!=root and root not in target.parents: raise ValueError("Path escapes profile directory")
        return target
    def load_settings(self):
        d=read_json(self.settings_path,{})
        return AppSettings(**{k:v for k,v in d.items() if k in AppSettings.__dataclass_fields__})
    def save_settings(self,s): write_json(self.settings_path,asdict(s))
    def load_templates(self):
        data=read_json(self.templates_path,None)
        if data is None:
            t=[WorkflowTemplate("Novel Translation Basic",Workflow.defaults())]; self.save_templates(t); return t
        return [WorkflowTemplate(x["name"],Workflow.from_dict(x.get("workflow",{}))) for x in data]
    def save_templates(self,items): write_json(self.templates_path,[{"name":x.name,"workflow":asdict(x.workflow)} for x in items])
