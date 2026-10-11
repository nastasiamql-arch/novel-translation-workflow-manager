"""Create real upgrade fixtures using the release build's snapshot service."""
import json
from pathlib import Path
import sys
from novel_workflow.models import NovelProfile, StepFile, WorkflowStep
from novel_workflow.storage import ProjectRepository
from novel_workflow.services import AssemblyService
from novel_workflow.polish_history import PolishHistory


def main():
    profile_path, main_folder = map(Path, sys.argv[1:])
    profile = NovelProfile.from_dict(json.loads(profile_path.read_text(encoding='utf-8-sig')))
    profile.main_folder = str(main_folder)
    step = WorkflowStep(name='Polish', files=[StepFile(path='source/chapter_1.txt', enabled=False)])
    profile.workflow.steps.append(step); profile.polish_history_step_id = step.id
    repo = ProjectRepository(profile_path.parent.parent.parent)
    repo.save_profile(profile)
    snapshot = PolishHistory(repo, AssemblyService(repo)).create(profile, step, '6-10')
    print(snapshot.path)


if __name__ == '__main__': main()
