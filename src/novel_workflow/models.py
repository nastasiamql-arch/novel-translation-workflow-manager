from dataclasses import dataclass, field
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
    def from_dict(cls,d):
        return cls(id=d.get("id",uid()),name=d.get("name","New step"),files=[StepFile.from_dict(x) for x in d.get("files",[])])

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
class LaunchTarget:
    id: str = field(default_factory=uid)
    label: str = ""
    kind: str = "file"
    target: str = ""
    arguments: list[str] = field(default_factory=list)
    enabled: bool = True
    order: int = 0
    @classmethod
    def from_dict(cls,d): return cls(**{k:v for k,v in d.items() if k in cls.__dataclass_fields__})

@dataclass
class NovelProfile:
    id: str = field(default_factory=uid)
    name: str = "Novel"
    workflow: Workflow = field(default_factory=Workflow.defaults)
    chapter_state: ChapterState = field(default_factory=ChapterState)
    main_folder: str = ""
    launch_targets: list[LaunchTarget] = field(default_factory=list)
    context_path: str | None = None
    status: str = "translating"
    translation_goal_target: int | None = None
    translation_goal_baseline: int | None = None
    @classmethod
    def from_dict(cls,d):
        state=d.get("chapter_state",{})
        return cls(
            id=d.get("id",uid()),
            name=d.get("name","Novel"),
            workflow=Workflow.from_dict(d.get("workflow",{})),
            chapter_state=ChapterState(int(state.get("current_chapter",1)),state.get("statuses",{})),
            main_folder=str(d.get("main_folder","")),
            launch_targets=[LaunchTarget.from_dict(x) for x in d.get("launch_targets",[])],
            context_path=d.get("context_path"),
            status=str(d.get("status","translating")),
            translation_goal_target=d.get("translation_goal_target"),
            translation_goal_baseline=d.get("translation_goal_baseline"),
        )

@dataclass
class NovelGroup:
    id: str = field(default_factory=uid)
    name: str = ""
    profile_ids: list[str] = field(default_factory=list)
    description: str = ""
    order: int = 0
    default_goal_chapters: int | None = None
    caught_up_profile_ids: list[str] = field(default_factory=list)
    completed_goal_cycles: int = 0
    last_goal_reset_at: str | None = None
    @classmethod
    def from_dict(cls,d): return cls(**{k:v for k,v in d.items() if k in cls.__dataclass_fields__})

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
