import json, os, re, tempfile
from pathlib import Path
from dataclasses import asdict
from .models import AppSettings, NovelGroup, NovelProfile, Workflow, WorkflowTemplate, migrate_legacy_basic_workflow, migrate_legacy_vocabulary_step
from .vocabulary import parse_json

def data_root():
    # Version 1.1 starts with a clean application data namespace. Legacy data is left untouched.
    return Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"NovelWorkflow"

def read_json(path, default):
    path=Path(path)
    if not path.exists(): return default
    raw=path.read_text(encoding="utf-8")
    if not raw.strip(): return default
    try: return parse_json(raw)
    except ValueError as exc: raise ValueError(f"Could not safely recover {path}") from exc

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
        self.settings_path=self.root/"settings.json"; self.templates_path=self.root/"templates.json";self.groups_path=self.root/"groups.json"
        self.profiles_dir.mkdir(parents=True,exist_ok=True)
    def profile_dir(self,pid):
        if not re.fullmatch(r"[a-fA-F0-9]{32}",pid): raise ValueError("Invalid profile ID")
        return self.profiles_dir/pid
    def list_profiles(self):
        profiles=[]
        missing_order=[]
        for folder in self.profiles_dir.iterdir():
            path=folder/"profile.json"
            if not path.is_file():continue
            data=read_json(path,{})
            profile=NovelProfile.from_dict(data)
            if data.get("schema_version", 1) < 2:
                self.save_profile(profile)
            profiles.append(profile)
            if "order" not in data:missing_order.append(profile)
        if missing_order:
            missing_ids={profile.id for profile in missing_order}
            next_order=max((profile.order for profile in profiles if profile.id not in missing_ids),default=-1)+1
            for profile in sorted(missing_order,key=lambda item:item.name.casefold()):
                profile.order=next_order
                next_order+=1
                self.save_profile(profile)
        return sorted(profiles,key=lambda profile:(profile.order,profile.name.casefold()))

    def next_profile_order(self):
        return max((profile.order for profile in self.list_profiles()),default=-1)+1

    def move_profile(self,pid,direction):
        profiles=self.list_profiles()
        index=next((i for i,profile in enumerate(profiles) if profile.id==pid),None)
        if index is None:raise ValueError(f"Unknown profile: {pid}")
        destination=max(0,min(len(profiles)-1,index+direction))
        if destination!=index:
            profile=profiles.pop(index)
            profiles.insert(destination,profile)
            for order,profile in enumerate(profiles):
                profile.order=order
                self.save_profile(profile)
        return destination
    def save_profile(self,p):
        folder=self.profile_dir(p.id); folder.mkdir(parents=True,exist_ok=True)
        for c in self.CATEGORIES: (folder/c).mkdir(exist_ok=True)
        write_json(folder/"profile.json",asdict(p))
    def delete_profile(self,pid):
        import shutil; shutil.rmtree(self.profile_dir(pid))
        for order,profile in enumerate(self.list_profiles()):
            if profile.order!=order:
                profile.order=order
                self.save_profile(profile)
        groups=[g for g in self.load_groups()]
        for group in groups:group.profile_ids=[profile_id for profile_id in group.profile_ids if profile_id!=pid]
        self.save_groups(groups)
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
            templates=[WorkflowTemplate("Novel Translation Basic",Workflow.defaults())]
            self.save_templates(templates)
            return templates
        templates=[WorkflowTemplate(
            x["name"],
            Workflow.from_dict(x.get("workflow",{})),
            WorkflowTemplate.from_dict(x).vocabulary_step,
        ) for x in data]
        changed=False
        for template in templates:
            changed=migrate_legacy_basic_workflow(template.workflow) or changed
            profile=NovelProfile(workflow=template.workflow,vocabulary_step=template.vocabulary_step)
            if migrate_legacy_vocabulary_step(profile):
                template.workflow=profile.workflow
                template.vocabulary_step=profile.vocabulary_step
                changed=True
        if changed:
            self.save_templates(templates)
        return templates
    def save_templates(self,items): write_json(self.templates_path,[{"name":x.name,"workflow":asdict(x.workflow),"vocabulary_step":asdict(x.vocabulary_step) if x.vocabulary_step else None} for x in items])
    def load_groups(self):
        data=read_json(self.groups_path,[])
        if not isinstance(data,list):raise ValueError("Group data must be a JSON array")
        return [NovelGroup.from_dict(item) for item in data]
    def save_groups(self,groups):
        known={profile.id for profile in self.list_profiles()}
        for group in groups:
            if not group.name.strip():raise ValueError("Group name cannot be empty")
            group.profile_ids=list(dict.fromkeys(pid for pid in group.profile_ids if pid in known))
        write_json(self.groups_path,[asdict(group) for group in groups])
