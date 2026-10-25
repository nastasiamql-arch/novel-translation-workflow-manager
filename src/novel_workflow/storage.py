import json, os, re, tempfile
from threading import RLock
from functools import wraps
from pathlib import Path
from dataclasses import asdict
from .models import AppSettings, NovelGroup, NovelProfile, Workflow, WorkflowTemplate, migrate_legacy_basic_workflow, migrate_legacy_vocabulary_step, migrate_profile_schema

def data_root():
    # Version 1.1 starts with a clean application data namespace. Legacy data is left untouched.
    return Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"NovelWorkflow"

def read_json(path, default):
    path=Path(path)
    if not path.exists(): return default
    raw=path.read_text(encoding="utf-8")
    if not raw.strip(): return default
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

def profile_guard(function):
    @wraps(function)
    def guarded(self, *args, **kwargs):
        with self.profile_lock:
            return function(self, *args, **kwargs)
    return guarded


class ProjectRepository:
    CATEGORIES=("prompts","glossary","characters","style","source","translated","reviewed","notes","reference","custom")
    def __init__(self,root=None):
        self.profile_lock = RLock()
        self.export_recovery_errors = {}
        self.root=Path(root) if root else data_root(); self.profiles_dir=self.root/"profiles"
        self.settings_path=self.root/"settings.json"; self.templates_path=self.root/"templates.json";self.groups_path=self.root/"groups.json"
        self.profiles_dir.mkdir(parents=True,exist_ok=True)
    def profile_dir(self,pid):
        if not re.fullmatch(r"[a-fA-F0-9]{32}",pid): raise ValueError("Invalid profile ID")
        return self.profiles_dir/pid
    def load_batch_draft(self, profile_id, kind):
        if kind not in {"translation", "vocabulary"}:
            raise ValueError("Invalid batch draft kind")
        data=read_json(self.profile_dir(profile_id)/"batch_drafts.json",{})
        if not isinstance(data,dict) or data.get("schema_version",1) not in (1,2):
            return ""
        drafts=data.get("drafts",{})
        return drafts.get(kind,"") if isinstance(drafts,dict) and isinstance(drafts.get(kind,""),str) else ""
    def save_batch_draft(self, profile_id, kind, text):
        if kind not in {"translation", "vocabulary"}:
            raise ValueError("Invalid batch draft kind")
        if not isinstance(text,str):
            raise TypeError("Batch draft must be text")
        path=self.profile_dir(profile_id)/"batch_drafts.json"
        data=read_json(path,{})
        if not isinstance(data,dict): raise ValueError("Invalid batch drafts file; preserving existing data")
        if data.get("schema_version") not in (None,1,2):
            raise ValueError("Unsupported batch draft schema")
        drafts=data.get("drafts",{})
        if not isinstance(drafts,dict): raise ValueError("Invalid batch drafts file")
        data["schema_version"]=2
        data["drafts"]={**drafts,kind:text}
        write_json(path,data)
    @profile_guard
    def list_profiles(self):
        profiles=[]
        missing_order=[]
        for folder in self.profiles_dir.iterdir():
            path=folder/"profile.json"
            if not path.is_file():continue
            from .export_recovery import recover_export, ExportRecoveryConflict
            try:
                recover_export(self, folder.name)
                self.export_recovery_errors.pop(folder.name, None)
            except ExportRecoveryConflict as exc:
                self.export_recovery_errors[folder.name] = str(exc)
                data=read_json(path,{})
                # Show the profile with its pre-transaction confirmed statistics.
                # Keep every live file untouched until the conflict is resolved.
                journal=read_json(folder/'translator_export_transaction.json',{})
                original=next(e.get('backup') for e in journal['entries'] if Path(e['path']).resolve()==path.resolve())
                before=read_json(Path(original),{})
                data['id']=folder.name
                data['translator_export_events']=before.get('translator_export_events',[])
                data['translator_goal_baseline']=before.get('translator_goal_baseline')
                profiles.append(NovelProfile.from_dict(data))
                continue
            data=read_json(path,{})
            profile=NovelProfile.from_dict(data)
            changed=False
            if data.get("schema_version", 1) < 5:
                if "txt_export_settings" not in data:
                    legacy_settings=self.load_settings()
                    profile.txt_export_settings.filename=legacy_settings.txt_export_filename
                    profile.txt_export_settings.directory=legacy_settings.txt_export_directory
                    profile.txt_export_settings.start=legacy_settings.txt_export_start
                    profile.txt_export_settings.end=legacy_settings.txt_export_end
                    profile.txt_export_settings.current=legacy_settings.txt_export_current
                    profile.txt_export_settings.advanced_range=True
                profile.schema_version=5
                changed=True
            if migrate_profile_schema(profile):
                changed=True
            # Old profiles must not retain a live website binding; save_profile
            # makes a lossless backup before removing only the obsolete field.
            if "source_binding" in data:
                changed=True
            if changed:
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

    @profile_guard
    def load_profile(self, profile_id):
        """Read a single profile without scanning unrelated novels.

        Keep export recovery and schema migration on the same guarded path
        as list_profiles; conflicts must never be silently overwritten.
        """
        folder = self.profile_dir(profile_id)
        path = folder / "profile.json"
        if not path.is_file():
            raise FileNotFoundError(path)
        from .export_recovery import recover_export
        recover_export(self, profile_id)
        data = read_json(path, {})
        if not isinstance(data, dict) or not data:
            raise ValueError(f"Invalid profile data: {path}")
        if data.get("schema_version", 1) < 5 or "source_binding" in data:
            return next(item for item in self.list_profiles() if item.id == profile_id)
        profile = NovelProfile.from_dict(data)
        if migrate_profile_schema(profile):
            self.save_profile(profile)
        return profile

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
    @profile_guard
    def save_profile(self,p, *, destination=None):
        if p.id in self.export_recovery_errors:
            raise OSError(self.export_recovery_errors[p.id])
        folder=self.profile_dir(p.id); folder.mkdir(parents=True,exist_ok=True)
        for c in self.CATEGORIES: (folder/c).mkdir(exist_ok=True)
        path=folder/"profile.json"
        serialized=asdict(p)
        # Preserve fields written by newer schema versions or extensions that this
        # version does not understand; known model fields remain authoritative.
        existing=read_json(path,{})
        # One-time cleanup of obsolete pre-v4 profile metadata. Preserve the
        # complete original file outside the active profile.json before dropping
        # that field; never touch source files, Translator, Context or Export.
        if isinstance(existing, dict) and "source_binding" in existing:
            backup = folder / "profile.json.pre-v4-upgrade.bak"
            if not backup.exists() and path.is_file():
                try:
                    with backup.open("xb") as saved:
                        saved.write(path.read_bytes())
                        saved.flush()
                        os.fsync(saved.fileno())
                except FileExistsError:
                    pass
            existing = {key: value for key, value in existing.items()
                        if key != "source_binding"}
        if isinstance(existing,dict):
            known=NovelProfile.__dataclass_fields__
            serialized={**{key:value for key,value in existing.items() if key not in known},**serialized}
        def preserve_unknown(previous, current):
            if isinstance(previous, dict) and isinstance(current, dict):
                return {**previous, **{key: preserve_unknown(previous.get(key), value) for key, value in current.items()}}
            if isinstance(previous, list) and isinstance(current, list):
                by_id = {item.get("id"): item for item in previous if isinstance(item, dict) and item.get("id")}
                result=[]
                for index,item in enumerate(current):
                    old=by_id.get(item.get("id"), {}) if isinstance(item,dict) else {}
                    if not old and index < len(previous) and isinstance(previous[index],dict) and not previous[index].get("id"):
                        old=previous[index]
                    result.append(preserve_unknown(old,item) if isinstance(item,dict) else item)
                return result
            return current
        merged = preserve_unknown(existing, serialized)
        # This known map is a live set of pending reminders, not extensible
        # metadata. Acknowledging one must delete its key on disk too.
        merged["chapter_number_pending_files"] = dict(
            serialized.get("chapter_number_pending_files", {})
        )
        write_json(Path(destination) if destination else path, merged)
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
        settings = AppSettings(**{k:v for k,v in d.items() if k in AppSettings.__dataclass_fields__})
        if not settings.history_zip_migrated:
            # The previous release shared one ZIP switch across Workflow and
            # History. Preserve the user's History ZIP choice, but restore the
            # original normal-copy behavior for Workflow steps on upgrade.
            settings.history_copy_as_zip = bool(settings.copy_files_as_zip)
            settings.copy_files_as_zip = False
            settings.history_zip_migrated = True
            self.save_settings(settings)
        return settings
    def save_settings(self,s):
        existing=read_json(self.settings_path,{})
        write_json(self.settings_path,{**(existing if isinstance(existing,dict) else {}),**asdict(s)})
    def load_templates(self):
        data=read_json(self.templates_path,None)
        if data is None:
            templates=[WorkflowTemplate("Novel Translation Basic",Workflow.defaults())]
            self.save_templates(templates)
            return templates
        templates=[WorkflowTemplate.from_dict(x) for x in data]
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
    def save_templates(self,items): write_json(self.templates_path,[{"name":x.name,"workflow":asdict(x.workflow),"vocabulary_step":asdict(x.vocabulary_step) if x.vocabulary_step else None,"removed_vocabulary_data":x.removed_vocabulary_data} for x in items])
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
