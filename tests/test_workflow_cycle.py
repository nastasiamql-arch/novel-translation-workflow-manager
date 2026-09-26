from novel_workflow.models import Workflow, WorkflowStep, migrate_legacy_basic_workflow
from novel_workflow.services import WorkflowService


def test_basic_workflow_defaults_to_three_steps():
    assert [step.name for step in Workflow.defaults().steps] == [
        "หาศัพท์",
        "แปล",
        "ตรวจคำแปล",
    ]


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


def test_copy_advances_from_final_step_back_to_first():
    assert WorkflowService.next_index(0, 3) == 1
    assert WorkflowService.next_index(1, 3) == 2
    assert WorkflowService.next_index(2, 3) == 0
    assert WorkflowService.next_index(0, 0) == -1
