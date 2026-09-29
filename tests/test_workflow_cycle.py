import json

from novel_workflow.models import (
    NovelProfile,
    StepFile,
    Workflow,
    WorkflowStep,
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
