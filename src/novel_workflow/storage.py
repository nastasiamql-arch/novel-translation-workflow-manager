import json, os, re, tempfile
from pathlib import Path
from dataclasses import asdict
from .models import AppSettings, LaunchTarget, NovelGroup, NovelProfile, Workflow, WorkflowTemplate, migrate_legacy_basic_workflow
from .translation_progress import latest_context_chapter

def data_root():
    # Keep the existing location so current NovelTranslationWorkflowManager data is reused.
    return Path(os.environ.get("LOCALAPPDATA",Path.home()/"AppData"/"Local"))/"NovelTranslationWorkflowManager"

def read_json(path, default):
    path=Path(path)
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
        self.settings_path=self.root/"settings.json"; self.templates_path=self.root/"templates.json";self.groups_path=self.root/"groups.json"
        self.profiles_dir.mkdir(parents=True,exist_ok=True)
    def profile_dir(self,pid):
        if not re.fullmatch(r"[a-fA-F0-9]{32}",pid): raise ValueError("Invalid profile ID")
        return self.profiles_dir/pid
    def list_profiles(self):
        return sorted([NovelProfile.from_dict(read_json(p/"profile.json",{})) for p in self.profiles_dir.iterdir() if (p/"profile.json").is_file()], key=lambda profile: profile.name.casefold())
    def save_profile(self,p):
        folder=self.profile_dir(p.id); folder.mkdir(parents=True,exist_ok=True)
        for c in self.CATEGORIES: (folder/c).mkdir(exist_ok=True)
        write_json(folder/"profile.json",asdict(p))
    def delete_profile(self,pid):
        import shutil; shutil.rmtree(self.profile_dir(pid))
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
        templates=[WorkflowTemplate(x["name"],Workflow.from_dict(x.get("workflow",{}))) for x in data]
        changed=False
        for template in templates:
            if template.name.strip().casefold()=="novel translation basic":
                changed=migrate_legacy_basic_workflow(template.workflow) or changed
        if changed:
            self.save_templates(templates)
        return templates
    def save_templates(self,items): write_json(self.templates_path,[{"name":x.name,"workflow":asdict(x.workflow)} for x in items])
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
    def import_launcher_config(self,path):
        """Merge a Novel Launcher config export into profiles and groups without changing its source."""
        data=read_json(Path(path),None)
        if not isinstance(data,dict) or not isinstance(data.get("novels"),list):
            raise ValueError("This is not a valid Novel Launcher configuration")
        if not all(isinstance(novel,dict) for novel in data["novels"]):
            raise ValueError("Novel Launcher config contains an invalid novel entry")
        launcher_groups=data.get("groups",[])
        if not isinstance(launcher_groups,list) or not all(isinstance(group,dict) for group in launcher_groups):
            raise ValueError("Novel Launcher config contains invalid groups")
        translation_stats=data.get("translationStats",{})
        raw_checkpoints=translation_stats.get("checkpoints",[]) if isinstance(translation_stats,dict) else []
        checkpoints_by_novel={
            str(item.get("novelId")):item for item in raw_checkpoints
            if isinstance(item,dict) and item.get("novelId")
        } if isinstance(raw_checkpoints,list) else {}

        profiles=self.list_profiles()
        folder_key=lambda value: str(Path(value).expanduser()).replace("\\","/").rstrip("/").casefold()
        name_key=lambda value: re.sub(r"[^\w]+","",str(value),flags=re.UNICODE).casefold()
        by_folder={folder_key(p.main_folder):p for p in profiles if p.main_folder}
        by_name={}
        for profile in profiles: by_name.setdefault(name_key(profile.name),profile)
        id_map={};new_profiles=0;new_targets=0
        staged=[]
        for novel in data["novels"]:
            name=str(novel.get("name","Novel")).strip() or "Novel"
            folder=str(novel.get("mainFolder","") or "").strip()
            key=folder_key(folder) if folder else ""
            profile=by_folder.get(key) if key else None
            if profile is None:
                candidate=by_name.get(name_key(name))
                if candidate and (not folder or not candidate.main_folder or folder_key(candidate.main_folder)==key): profile=candidate
            if profile is None:
                profile=NovelProfile(name=name,main_folder=folder)
                new_profiles+=1
            elif folder and not profile.main_folder:
                profile.main_folder=folder
            profile.context_path=str(novel.get("contextPath")) if novel.get("contextPath") else profile.context_path
            imported_status=str(novel.get("status","translating"))
            if imported_status in ("translating","paused","completed"):profile.status=imported_status
            goal=novel.get("translationGoal")
            if isinstance(goal,dict):
                target=goal.get("targetChapters")
                baseline=goal.get("baselineChapter")
                profile.translation_goal_target=int(target) if target is not None else None
                profile.translation_goal_baseline=int(baseline) if baseline is not None else None
            if profile.context_path:
                context=Path(profile.context_path)
                if context.exists():
                    chapter_numbers=re.findall(r"(?im)^\s*บทที่\s*(\d+)",context.read_text(encoding="utf-8",errors="replace"))
                    if chapter_numbers:profile.chapter_state.current_chapter=int(chapter_numbers[-1])

            cover_source=novel.get("coverPath")
            if isinstance(cover_source,str) and cover_source:
                source=Path(cover_source).expanduser()
                suffix=source.suffix.lower()
                if suffix in {".png",".jpg",".jpeg",".webp",".bmp"} and source.is_file():
                    profile_root=self.profile_dir(profile.id)
                    cover_target=profile_root/"covers"/("cover"+suffix)
                    cover_target.parent.mkdir(parents=True,exist_ok=True)
                    import shutil
                    if source.resolve()!=cover_target.resolve(): shutil.copy2(source,cover_target)
                    profile.cover_image_path=cover_target.relative_to(profile_root).as_posix()
            old_id=str(novel.get("id",""))
            if old_id:id_map[old_id]=profile.id
            targets=[]
            for index,item in enumerate(novel.get("files",[]) if isinstance(novel.get("files",[]),list) else []):
                if not isinstance(item,dict) or not item.get("path"):continue
                targets.append(LaunchTarget(label=str(item.get("name") or Path(str(item["path"])).name),kind="file",target=str(item["path"]),enabled=bool(item.get("enabled",True)),order=int(item.get("order",index))))
            for index,item in enumerate(novel.get("applications",[]) if isinstance(novel.get("applications",[]),list) else []):
                if not isinstance(item,dict) or not item.get("executablePath"):continue
                args=item.get("arguments",[])
                targets.append(LaunchTarget(label=str(item.get("name") or "Application"),kind="application",target=str(item["executablePath"]),arguments=[str(arg) for arg in args] if isinstance(args,list) else [],enabled=bool(item.get("enabled",True)),order=int(item.get("order",index))))
            for index,item in enumerate(novel.get("websites",[]) if isinstance(novel.get("websites",[]),list) else []):
                if not isinstance(item,dict) or not item.get("url"):continue
                targets.append(LaunchTarget(label=str(item.get("name") or item["url"]),kind="website",target=str(item["url"]),enabled=bool(item.get("enabled",True)),order=int(item.get("order",index))))
            existing={(entry.kind,entry.target) for entry in profile.launch_targets}
            for target in targets:
                if (target.kind,target.target) not in existing:
                    target.order=len(profile.launch_targets);profile.launch_targets.append(target);new_targets+=1
                    existing.add((target.kind,target.target))

            checkpoint=checkpoints_by_novel.get(old_id)
            legacy_context=Path(str(checkpoint.get("contextPath",""))).expanduser() if checkpoint and checkpoint.get("contextPath") else None
            if legacy_context and legacy_context.is_file() and not (profile.context_path and Path(profile.context_path).expanduser().is_file()):
                profile.context_path=str(legacy_context.resolve())
            if not profile.context_path:
                candidates=[]
                for entry in profile.launch_targets:
                    candidate=Path(entry.target).expanduser()
                    if entry.kind=="file" and "context" in candidate.stem.casefold() and candidate.is_file():
                        resolved=candidate.resolve()
                        if resolved not in candidates:candidates.append(resolved)
                if len(candidates)==1:profile.context_path=str(candidates[0])
            if profile.context_path:
                context=Path(profile.context_path).expanduser()
                if context.is_file():
                    canonical=os.path.normcase(str(context.resolve()))
                    if profile.translation_checkpoint_path is None:
                        checkpoint_matches=False
                        if legacy_context and checkpoint and legacy_context.is_file():
                            checkpoint_matches=os.path.normcase(str(legacy_context.resolve()))==canonical
                        latest_known=None
                        if checkpoint_matches:
                            try:latest_known=int(checkpoint.get("latestChapter"))
                            except (TypeError,ValueError):latest_known=None
                        if latest_known is not None and latest_known > 0:
                            profile.chapter_state.current_chapter=latest_known
                        else:
                            latest=latest_context_chapter(context.read_text(encoding="utf-8-sig",errors="replace"))
                            if latest is not None:profile.chapter_state.current_chapter=latest
                        profile.translation_checkpoint_path=canonical
            if folder:by_folder[key]=profile
            by_name.setdefault(name_key(profile.name),profile)
            by_name.setdefault(name_key(name),profile)
            staged.append(profile)

        for profile in staged:self.save_profile(profile)
        groups=self.load_groups();new_groups=0
        for index,item in enumerate(launcher_groups):
            name=str(item.get("name","")).strip()
            if not name:continue
            member_ids=item.get("novelIds",[])
            mapped=list(dict.fromkeys(id_map[old_id] for old_id in member_ids if str(old_id) in id_map)) if isinstance(member_ids,list) else []
            existing=next((group for group in groups if group.name.casefold()==name.casefold()),None)
            caught=item.get("caughtUpNovelIds",[])
            mapped_caught=[id_map[old_id] for old_id in caught if str(old_id) in id_map] if isinstance(caught,list) else []
            if existing:
                existing.profile_ids=list(dict.fromkeys(existing.profile_ids+mapped))
                existing.caught_up_profile_ids=list(dict.fromkeys(existing.caught_up_profile_ids+mapped_caught))
                if existing.default_goal_chapters is None:existing.default_goal_chapters=item.get("defaultGoalChapters")
                existing.completed_goal_cycles=max(existing.completed_goal_cycles,int(item.get("completedGoalCycles",0) or 0))
                if not existing.last_goal_reset_at:existing.last_goal_reset_at=item.get("lastGoalResetAt")
                if not existing.description:existing.description=str(item.get("description",""))
            else:
                groups.append(NovelGroup(name=name,profile_ids=mapped,description=str(item.get("description","")),order=index,default_goal_chapters=item.get("defaultGoalChapters"),caught_up_profile_ids=mapped_caught,completed_goal_cycles=int(item.get("completedGoalCycles",0) or 0),last_goal_reset_at=item.get("lastGoalResetAt")));new_groups+=1
        self.save_groups(groups)
        return {"profiles":new_profiles,"groups":new_groups,"launch_targets":new_targets}
