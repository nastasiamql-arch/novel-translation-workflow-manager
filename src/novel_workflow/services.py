from copy import deepcopy
from pathlib import Path
import re
from .models import NovelProfile, Workflow, WorkflowStep, StepFile, uid
from .storage import ProjectRepository

DYNAMIC=("CURRENT_SOURCE_CHAPTER","CURRENT_TRANSLATED_CHAPTER","CURRENT_REVIEWED_CHAPTER")
class ProfileService:
    def __init__(self,repo): self.repo=repo
    def create(self,name,workflow=None):
        p=NovelProfile(name=name.strip() or "Novel",workflow=deepcopy(workflow or Workflow.defaults())); self.repo.save_profile(p); return p
    def duplicate(self,source,name,glossary=False,characters=False):
        p=NovelProfile(name=name.strip() or source.name+" Copy",workflow=deepcopy(source.workflow)); self.repo.save_profile(p)
        src,dst=self.repo.profile_dir(source.id),self.repo.profile_dir(p.id)
        import shutil
        for cat,copy in (("prompts",True),("style",True),("glossary",glossary),("characters",characters)):
            if copy and (src/cat).exists(): shutil.copytree(src/cat,dst/cat,dirs_exist_ok=True)
        for s in p.workflow.steps:
            s.files=[f for f in s.files if f.reference_type=="dynamic" or (f.path and (dst/f.path).is_file())]
        self.repo.save_profile(p); return p

class WorkflowService:
    @staticmethod
    def add_step(w,name): s=WorkflowStep(name=name); w.steps.append(s); return s
    @staticmethod
    def duplicate_step(w,i):
        s=deepcopy(w.steps[i]); s.id=uid()
        for f in s.files:f.id=uid()
        s.name+=" copy";w.steps.insert(i+1,s);return s
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
                 and re.search(rf"(?<!\d){n}(?!\d)",f.stem)]
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
            else:
                if not item.path:raise ValueError(f"Missing file path for {item.label}")
                path=self.repo.resolve_project_path(p.id,item.path);label=item.label or path.name
            if not path.is_file():raise FileNotFoundError(path)
            content=path.read_text(encoding="utf-8-sig").strip()
            if content:parts.append((separator.format(FILE_NAME=label)+"\n"+content) if show_heading else content)
        return "\n\n".join(parts)
