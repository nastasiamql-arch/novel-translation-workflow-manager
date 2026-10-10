from dataclasses import dataclass, field
import uuid

def uid(): return uuid.uuid4().hex

def _daily_activity_from_dict(value):
    if not isinstance(value, dict): return {}
    activity = {}
    for day, chapters in value.items():
        if not isinstance(chapters, list): continue
        parsed = set()
        for chapter in chapters:
            try: number = int(chapter)
            except (TypeError, ValueError): continue
            if not isinstance(chapter, bool) and number > 0: parsed.add(number)
        activity[str(day)] = sorted(parsed)
    return activity

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
    def defaults(cls): return cls([WorkflowStep(name=n) for n in ("แปล","ตรวจคำแปล")])
    @classmethod
    def from_dict(cls,d): return cls([WorkflowStep.from_dict(x) for x in d.get("steps",[])])

_LEGACY_BASIC_STEP_NAMES = ("หาศัพท์","แปล","ตรวจคำแปล","เกลาสำนวน")
PROFILE_SCHEMA_VERSION = 8

def migrate_profile_schema(profile: "NovelProfile") -> bool:
    """Advance old profile documents after additive, non-destructive upgrades."""
    if profile.schema_version >= PROFILE_SCHEMA_VERSION:
        return False
    profile.schema_version = PROFILE_SCHEMA_VERSION
    return True

def migrate_legacy_basic_workflow(workflow: Workflow) -> bool:
    """Remove only the old built-in fourth step, leaving custom workflows intact."""
    if tuple(step.name for step in workflow.steps) != _LEGACY_BASIC_STEP_NAMES:
        return False
    workflow.steps.pop()
    return True


def migrate_legacy_vocabulary_step(profile: "NovelProfile") -> bool:
    """Move the former first workflow step into the separate vocabulary tool."""
    if not profile.workflow.steps or profile.workflow.steps[0].name.strip() != "หาศัพท์":
        return False
    legacy_step = profile.workflow.steps.pop(0)
    current = profile.vocabulary_step
    if current is None or not current.files:
        profile.vocabulary_step = legacy_step
    else:
        # Preserve both sets of links if a partially migrated profile contains
        # data in each place.
        known = {item.id for item in current.files}
        current.files.extend(item for item in legacy_step.files if item.id not in known)
    return True

@dataclass
class ChapterState:
    current_chapter: int = 1
    statuses: dict[str,str] = field(default_factory=dict)

@dataclass
class TxtExportSettings:
    filename: str = "segverified"
    directory: str = ""
    start: int = 1
    end: int = 100
    current: int = 1
    advanced_range: bool = False
    mode: str = "legacy"
    @property
    def txt_export_filename(self): return self.filename
    @txt_export_filename.setter
    def txt_export_filename(self, value): self.filename=value
    @property
    def txt_export_directory(self): return self.directory
    @txt_export_directory.setter
    def txt_export_directory(self, value): self.directory=value
    @property
    def txt_export_start(self): return self.start
    @txt_export_start.setter
    def txt_export_start(self, value): self.start=value
    @property
    def txt_export_end(self): return self.end
    @txt_export_end.setter
    def txt_export_end(self, value): self.end=value
    @property
    def txt_export_current(self): return self.current
    @txt_export_current.setter
    def txt_export_current(self, value): self.current=value
    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict): return cls()
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        values.setdefault("advanced_range", any(key in data for key in ("start", "end", "current")))
        return cls(**values)

@dataclass
class NovelSourceBinding:
    source_id: str
    book_url: str
    remote_book_id: str
    content_mode: str = "raw_zh"
    last_known_chapter_count: int = 0
    last_downloaded_chapter: int = 0
    last_checked_at: str | None = None
    last_downloaded_at: str | None = None
    skip_existing: bool = True
    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict): return None
        fields = cls.__dataclass_fields__
        data = {key: item for key, item in value.items() if key in fields}
        if not all(data.get(key) for key in ("source_id", "book_url", "remote_book_id")): return None
        return cls(**data)

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
    source_binding: NovelSourceBinding | None = None
    workflow: Workflow = field(default_factory=Workflow.defaults)
    vocabulary_step: WorkflowStep | None = field(default_factory=lambda: WorkflowStep(name="หาศัพท์"))
    chapter_state: ChapterState = field(default_factory=ChapterState)
    main_folder: str = ""
    launch_targets: list[LaunchTarget] = field(default_factory=list)
    context_path: str | None = None
    status: str = "translating"
    translation_goal_target: int | None = None
    translation_goal_baseline: int | None = None
    translation_checkpoint_path: str | None = None
    translation_daily_activity: dict[str, list[int]] = field(default_factory=dict)
    cover_image_path: str | None = None
    working_files: list[StepFile] = field(default_factory=list)
    open_working_tabs_on_open: bool = False
    order: int = 0
    last_browse_directory: str | None = None
    schema_version: int = PROFILE_SCHEMA_VERSION
    removed_vocabulary_data: dict = field(default_factory=dict)
    txt_export_draft: str = ""
    verified_goal_target: int | None = None
    verified_goal_count: int = 0
    verified_export_history: list[dict] = field(default_factory=list)
    verified_goal_cycles: list[dict] = field(default_factory=list)
    txt_export_settings: TxtExportSettings = field(default_factory=TxtExportSettings)
    @classmethod
    def from_dict(cls,d):
        state=d.get("chapter_state",{})
        return cls(
            id=d.get("id",uid()),
            name=d.get("name","Novel"),
            source_binding=NovelSourceBinding.from_dict(d.get("source_binding")),
            order=int(d.get("order",0)),
            schema_version=int(d.get("schema_version",1)),
            workflow=Workflow.from_dict(d.get("workflow",{})),
            vocabulary_step=(
                WorkflowStep.from_dict(d["vocabulary_step"])
                if isinstance(d.get("vocabulary_step"), dict)
                else WorkflowStep(name="หาศัพท์")
            ),
            chapter_state=ChapterState(int(state.get("current_chapter",1)),state.get("statuses",{})),
            main_folder=str(d.get("main_folder","")),
            last_browse_directory=d.get("last_browse_directory"),
            launch_targets=[LaunchTarget.from_dict(x) for x in d.get("launch_targets",[])],
            context_path=d.get("context_path"),
            status=str(d.get("status","translating")),
            translation_goal_target=d.get("translation_goal_target"),
            translation_goal_baseline=d.get("translation_goal_baseline"),
            translation_checkpoint_path=d.get("translation_checkpoint_path"),
            translation_daily_activity=_daily_activity_from_dict(d.get("translation_daily_activity", {})),
            cover_image_path=d.get("cover_image_path"),
            working_files=[StepFile.from_dict(item) for item in d.get("working_files", [])],
            open_working_tabs_on_open=bool(d.get("open_working_tabs_on_open", False)),
            txt_export_draft=str(d.get("txt_export_draft", "")),
            verified_goal_target=d.get("verified_goal_target"),
            verified_goal_count=max(0, int(d.get("verified_goal_count", 0))),
            verified_export_history=d.get("verified_export_history", []),
            verified_goal_cycles=d.get("verified_goal_cycles", []),
            txt_export_settings=TxtExportSettings.from_dict(d.get("txt_export_settings")),
            removed_vocabulary_data={
                **(d.get("removed_vocabulary_data", {}) if isinstance(d.get("removed_vocabulary_data"), dict) else {}),
                **{key: d[key] for key in ("vocabulary_polish_step", "vocabulary_settings") if key in d},
            },
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
    copy_files_as_zip: bool = False
    appearance: str = "Light"
    appearance_migrated: bool = False
    flat_vscode_theme_migrated: bool = False
    editor_style_migrated: bool = False
    separator: str = "==============================\n{FILE_NAME}\n=============================="
    show_filename_heading: bool = True
    confirm_before_deleting: bool = True
    open_last_profile: bool = True
    last_profile_id: str | None = None
    editor_tabs: dict[str, list[str]] = field(default_factory=dict)
    editor_active_tabs: dict[str, int] = field(default_factory=dict)
    editor_tab_order: dict[str, list[str]] = field(default_factory=dict)
    editor_active_tab_keys: dict[str, str] = field(default_factory=dict)
    workspace_step_indices: dict[str, int] = field(default_factory=dict)
    workspace_vocabulary_modes: dict[str, bool] = field(default_factory=dict)
    workspace_open_profile_ids: list[str] = field(default_factory=list)
    closed_workspace_profile_ids: list[str] = field(default_factory=list)
    editor_positions: dict[str, dict[str, dict[str, int]]] = field(default_factory=dict)
    navigation_width: int = 180
    navigation_collapsed: bool = False
    sidebar_width: int = 290
    sidebar_visible: bool = True
    editor_font_size: float = 11.0
    last_update_check_date: str | None = None
    txt_export_filename: str = "segverified"
    txt_export_directory: str = ""
    txt_export_start: int = 1
    txt_export_end: int = 100
    txt_export_current: int = 1

@dataclass
class WorkflowTemplate:
    name: str
    workflow: Workflow
    vocabulary_step: WorkflowStep | None = field(default_factory=lambda: WorkflowStep(name="หาศัพท์"))
    removed_vocabulary_data: dict = field(default_factory=dict)
    @classmethod
    def from_dict(cls, data):
        vocabulary = data.get("vocabulary_step")
        return cls(
            data.get("name", "Workflow"),
            Workflow.from_dict(data.get("workflow", {})),
            WorkflowStep.from_dict(vocabulary) if isinstance(vocabulary, dict) else WorkflowStep(name="หาศัพท์"),
            {
                **(data.get("removed_vocabulary_data", {}) if isinstance(data.get("removed_vocabulary_data"), dict) else {}),
                **{key: data[key] for key in ("vocabulary_polish_step",) if key in data},
            },
        )
