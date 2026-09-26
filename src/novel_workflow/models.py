from dataclasses import asdict, dataclass, field
from typing import Any
import uuid

def uid(): return uuid.uuid4().hex

@dataclass
class StepFile:
    id: str = field(default_factory=uid)
    label: str = ""
    reference_type: str = "repository_file"
    path: str | None = None
    dynamic_reference: str | None = None
    file_type: str = "custom"
    enabled: bool = True
    order: int = 0
    @classmethod
    def from_dict(cls, d): return cls(**{k:v for k,v in d.items() if k in cls.__dataclass_fields__})

@dataclass
class WorkflowStep:
    id: str = field(default_factory=uid)
    name: str = "New step"
    files: list[StepFile] = field(default_factory=list)
    @classmethod
    def from_dict(cls,d): return cls(d.get("id",uid()),d.get("name","New step"),[StepFile.from_dict(x) for x in d.get("files",[])])

@dataclass
class Workflow:
    steps: list[WorkflowStep] = field(default_factory=list)
    @classmethod
    def defaults(cls): return cls([WorkflowStep(name=n) for n in ("หาศัพท์","แปล","ตรวจคำแปล","เกลาสำนวน")])
    @classmethod
    def from_dict(cls,d): return cls([WorkflowStep.from_dict(x) for x in d.get("steps",[])])

@dataclass
class ChapterState:
    current_chapter: int = 1
    statuses: dict[str,str] = field(default_factory=dict)

@dataclass
class NovelProfile:
    id: str = field(default_factory=uid)
    name: str = "Novel"
    workflow: Workflow = field(default_factory=Workflow.defaults)
    chapter_state: ChapterState = field(default_factory=ChapterState)
    @classmethod
    def from_dict(cls,d):
        s=d.get("chapter_state",{})
        return cls(d.get("id",uid()),d.get("name","Novel"),Workflow.from_dict(d.get("workflow",{})),ChapterState(int(s.get("current_chapter",1)),s.get("statuses",{})))

@dataclass
class AppSettings:
    appearance: str = "System"
    separator: str = "==============================\n{FILE_NAME}\n=============================="
    show_filename_heading: bool = True
    confirm_before_deleting: bool = True
    open_last_profile: bool = True
    last_profile_id: str | None = None

@dataclass
class WorkflowTemplate:
    name: str
    workflow: Workflow
