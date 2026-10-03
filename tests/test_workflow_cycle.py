import json

from novel_workflow.models import (
    NovelProfile,
    StepFile,
    Workflow,
    WorkflowStep,
    WorkflowTemplate,
    migrate_legacy_basic_workflow,
    migrate_legacy_vocabulary_step,
)
from novel_workflow.services import WorkflowService
from novel_workflow.storage import ProjectRepository


def test_basic_workflow_defaults_to_two_translation_steps():
    assert [step.name for step in Workflow.defaults().steps] == [
        "แปล",
        "ตรวจคำแปล",
    ]


def test_legacy_vocabulary_step_moves_out_without_losing_files():
    vocabulary_file = StepFile(label="Glossary", path="glossary.txt")
    translation = WorkflowStep(name="แปล")
    review = WorkflowStep(name="ตรวจคำแปล")
    profile = NovelProfile(
        workflow=Workflow([
            WorkflowStep(name="หาศัพท์", files=[vocabulary_file]),
            translation,
            review,
        ])
    )

    assert migrate_legacy_vocabulary_step(profile)
    assert profile.vocabulary_step.name == "หาศัพท์"
    assert profile.vocabulary_step.files[0].id == vocabulary_file.id
    assert profile.workflow.steps == [translation, review]
    assert not migrate_legacy_vocabulary_step(profile)


def test_old_profile_keeps_vocabulary_and_archives_removed_ai_settings():
    existing = StepFile(id="original-vocab-file", label="Glossary", path="glossary.txt")
    profile = NovelProfile.from_dict({
        "name": "Old profile",
        "vocabulary_step": {"name": "หาศัพท์", "files": [existing.__dict__]},
        "vocabulary_settings": {"provider": "openai", "model": "legacy-model"},
        "workflow": {"steps": [{"name": "แปล", "files": []}]},
    })
    assert profile.vocabulary_step.name == "หาศัพท์"
    assert [item.id for item in profile.vocabulary_step.files] == [existing.id]
    assert profile.removed_vocabulary_data["vocabulary_settings"]["model"] == "legacy-model"
    assert not hasattr(profile, "vocabulary_polish_step")


def test_removed_vocabulary_data_survives_profile_save_without_becoming_a_feature(tmp_path):
    repo = ProjectRepository(tmp_path)
    old_polish = {"name": "เกลาศัพท์", "files": [{"label": "old terms", "path": "terms.txt"}]}
    profile = NovelProfile.from_dict({
        "name": "Old profile",
        "vocabulary_step": {"name": "หาศัพท์", "files": []},
        "vocabulary_polish_step": old_polish,
        "vocabulary_settings": {"provider": "anthropic", "model": "old-model"},
    })
    repo.save_profile(profile)
    restored = next(item for item in repo.list_profiles() if item.id == profile.id)
    assert restored.vocabulary_step.name == "หาศัพท์"
    assert restored.removed_vocabulary_data["vocabulary_polish_step"] == old_polish
    assert restored.removed_vocabulary_data["vocabulary_settings"]["provider"] == "anthropic"
    assert not hasattr(restored, "vocabulary_polish_step")


def test_schema_three_profile_migrates_to_six_and_keeps_removed_data(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile_id = "0123456789abcdef0123456789abcdef"
    profile_path = repo.profile_dir(profile_id) / "profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(json.dumps({
        "id": profile_id,
        "name": "Legacy",
        "order": 0,
        "schema_version": 3,
        "workflow": {"steps": [{"name": "แปล", "files": []}]},
        "vocabulary_step": {"name": "หาศัพท์", "files": [{"id": "file-id", "label": "ศัพท์", "path": "terms.txt"}]},
        "vocabulary_polish_step": {"name": "เกลาศัพท์", "files": [{"label": "old terms", "path": "polish.txt"}]},
        "vocabulary_settings": {"provider": "openai", "model": "legacy"},
    }), encoding="utf-8")

    loaded = repo.list_profiles()[0]
    persisted = json.loads(profile_path.read_text(encoding="utf-8"))

    assert loaded.schema_version == 6
    assert loaded.vocabulary_step.files[0].id == "file-id"
    assert persisted["schema_version"] == 6
    assert persisted["removed_vocabulary_data"]["vocabulary_polish_step"]["files"][0]["path"] == "polish.txt"
    assert persisted["removed_vocabulary_data"]["vocabulary_settings"]["model"] == "legacy"


def test_custom_workflow_without_vocabulary_step_is_preserved():
    profile = NovelProfile(workflow=Workflow([
        WorkflowStep(name="เตรียมข้อมูล"),
        WorkflowStep(name="แปล"),
    ]))

    assert not migrate_legacy_vocabulary_step(profile)
    assert [step.name for step in profile.workflow.steps] == ["เตรียมข้อมูล", "แปล"]


def test_legacy_template_moves_vocabulary_files_to_separate_field(tmp_path):
    repo = ProjectRepository(tmp_path)
    legacy_file = StepFile(label="Terms", path="glossary.txt")
    repo.templates_path.write_text(
        json.dumps([{
            "name": "Old workflow",
            "workflow": {"steps": [
                {"name": "หาศัพท์", "files": [{
                    "id": legacy_file.id,
                    "label": legacy_file.label,
                    "path": legacy_file.path,
                }]},
                {"name": "แปล", "files": []},
                {"name": "ตรวจคำแปล", "files": []},
            ]},
        }]),
        encoding="utf-8",
    )

    template = repo.load_templates()[0]

    assert [step.name for step in template.workflow.steps] == ["แปล", "ตรวจคำแปล"]
    assert template.vocabulary_step.files[0].id == legacy_file.id
    persisted = json.loads(repo.templates_path.read_text(encoding="utf-8"))[0]
    assert persisted["vocabulary_step"]["files"][0]["id"] == legacy_file.id
    assert "vocabulary_polish_step" not in persisted


def test_template_preserves_removed_vocabulary_data_without_exposing_polish_step(tmp_path):
    repo = ProjectRepository(tmp_path)
    template = WorkflowTemplate(
        "Polish template",
        Workflow.defaults(),
        WorkflowStep(name="หาศัพท์", files=[StepFile(label="find")]),
        {"vocabulary_polish_step": {"name": "เกลาศัพท์", "files": [{"label": "polish"}]}},
    )
    repo.save_templates([template])
    loaded = repo.load_templates()[0]
    assert [item.label for item in loaded.vocabulary_step.files] == ["find"]
    assert loaded.removed_vocabulary_data["vocabulary_polish_step"]["files"][0]["label"] == "polish"


def test_legacy_basic_fourth_step_is_removed_once():
    workflow = Workflow(
        [
            WorkflowStep(name="หาศัพท์"),
            WorkflowStep(name="แปล"),
            WorkflowStep(name="ตรวจคำแปล"),
            WorkflowStep(name="เกลาสำนวน"),
        ]
    )

    assert migrate_legacy_basic_workflow(workflow)
    assert [step.name for step in workflow.steps] == ["หาศัพท์", "แปล", "ตรวจคำแปล"]
    assert not migrate_legacy_basic_workflow(workflow)


def test_custom_four_step_workflow_is_preserved():
    workflow = Workflow(
        [
            WorkflowStep(name="หาศัพท์"),
            WorkflowStep(name="แปล"),
            WorkflowStep(name="ตรวจคำแปล"),
            WorkflowStep(name="ตรวจศัพท์เฉพาะ"),
        ]
    )

    assert not migrate_legacy_basic_workflow(workflow)
    assert len(workflow.steps) == 4


def test_copy_advances_between_two_translation_steps():
    assert WorkflowService.next_index(0, 2) == 1
    assert WorkflowService.next_index(1, 2) == 0
    assert WorkflowService.next_index(0, 0) == -1
