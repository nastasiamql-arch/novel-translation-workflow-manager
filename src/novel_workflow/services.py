from copy import deepcopy
from pathlib import Path
import re
from .models import NovelProfile, Workflow, WorkflowStep, StepFile, uid
from .storage import ProjectRepository
from .text_normalization import normalize_file_text

DYNAMIC=("CURRENT_SOURCE_CHAPTER","CURRENT_TRANSLATED_CHAPTER","CURRENT_REVIEWED_CHAPTER")
class ProfileService:
    def __init__(self,repo): self.repo=repo
    def create(self,name,workflow=None,vocabulary_step=None,removed_vocabulary_data=None):
        p=NovelProfile(name=name.strip() or "Novel",order=self.repo.next_profile_order(),workflow=deepcopy(workflow or Workflow.defaults()),vocabulary_step=deepcopy(vocabulary_step) if vocabulary_step else WorkflowStep(name="หาศัพท์"),removed_vocabulary_data=deepcopy(removed_vocabulary_data or {})); self.repo.save_profile(p); return p
    def duplicate(self,source,name,glossary=False,characters=False):
        p=NovelProfile(name=name.strip() or source.name+" Copy",order=self.repo.next_profile_order(),workflow=deepcopy(source.workflow),vocabulary_step=deepcopy(source.vocabulary_step),removed_vocabulary_data=deepcopy(source.removed_vocabulary_data)); self.repo.save_profile(p)
        src,dst=self.repo.profile_dir(source.id),self.repo.profile_dir(p.id)
        import shutil
        for cat,copy in (("prompts",True),("style",True),("glossary",glossary),("characters",characters)):
            if copy and (src/cat).exists(): shutil.copytree(src/cat,dst/cat,dirs_exist_ok=True)
        for s in p.workflow.steps:
            s.files=[f for f in s.files if f.reference_type=="dynamic" or (f.path and (dst/f.path).is_file())]
        if p.vocabulary_step:
            p.vocabulary_step.files=[f for f in p.vocabulary_step.files if f.reference_type=="dynamic" or (f.path and (dst/f.path).is_file())]
        self.repo.save_profile(p); return p

    @staticmethod
    def browse_directory(repo,profile,home=None):
        """Choose the profile's last-used folder, novel folder, app folder, or home."""
        for candidate in (profile.last_browse_directory,profile.main_folder):
            if candidate:
                path=Path(candidate).expanduser()
                if path.is_dir():return path
        profile_root=repo.profile_dir(profile.id)
        if profile_root.is_dir():return profile_root
        return Path(home).expanduser() if home else Path.home()

    @staticmethod
    def remember_browse_directory(repo,profile,path):
        selected=Path(path).expanduser()
        directory=selected if selected.is_dir() else selected.parent
        if not directory.is_dir():return False
        profile.last_browse_directory=str(directory.resolve())
        repo.save_profile(profile)
        return True

class WorkflowService:
    @staticmethod
    def add_step(w,name): s=WorkflowStep(name=name); w.steps.append(s); return s
    @staticmethod
    def duplicate_step(w,i):
        s=deepcopy(w.steps[i]); s.id=uid()
        for f in s.files:f.id=uid()
        s.name+=" copy";w.steps.insert(i+1,s);return s
    @staticmethod
    def next_index(i,count):
        return (i+1)%count if count>0 else -1
    @staticmethod
    def move(items,i,d):
        j=max(0,min(len(items)-1,i+d));items.insert(j,items.pop(i))
        for n,x in enumerate(items):
            if hasattr(x,"order"):x.order=n
        return j

class AssemblyService:
    def __init__(self,repo):self.repo=repo
    def resolve(self,p,ref):
        cat={"CURRENT_SOURCE_CHAPTER":"source","CURRENT_TRANSLATED_CHAPTER":"translated","CURRENT_REVIEWED_CHAPTER":"reviewed"}[ref]
        folder=self.repo.profile_dir(p.id)/cat; n=p.chapter_state.current_chapter
        if not folder.exists(): raise FileNotFoundError(f"No {cat} folder exists for chapter {n}")
        supported={".txt",".md",".json"}
        matches=[f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in supported
                 and re.search(rf"(?<!\d)0*{n}(?!\d)",f.stem)]
        exact=[f for f in matches if f.stem.casefold()==f"chapter_{n}".casefold()]
        matches=exact or matches
        if len(matches)==1:return matches[0]
        if len(matches)>1:raise ValueError(f"Multiple {cat} files match chapter {n}: "+", ".join(f.name for f in matches))
        raise FileNotFoundError(f"No {cat} file contains chapter number {n}")
    def assemble(self,p,step,separator,show_heading=True):
        parts=[]
        for item in sorted(step.files,key=lambda x:x.order):
            if not item.enabled:continue
            if item.reference_type=="dynamic":
                if item.dynamic_reference not in DYNAMIC:raise ValueError("Unsupported dynamic chapter reference")
                path=self.resolve(p,item.dynamic_reference); label=item.label or f"Chapter {p.chapter_state.current_chapter}"
            elif item.reference_type=="external_file":
                if not item.path:raise ValueError(f"Missing linked file path for {item.label}")
                path=Path(item.path).expanduser().resolve();label=item.label or path.name
            else:
                if not item.path:raise ValueError(f"Missing file path for {item.label}")
                path=self.repo.resolve_project_path(p.id,item.path);label=item.label or path.name
            if not path.is_file():raise FileNotFoundError(path)
            content=path.read_text(encoding="utf-8-sig")
            content = normalize_file_text(path, content)
            if content != '':parts.append((separator.format(FILE_NAME=label)+"\n"+content) if show_heading else content)
        return "\n".join(parts)
