from novel_workflow.models import NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.services import AssemblyService, ProfileService, WorkflowService
from novel_workflow.storage import ProjectRepository, read_json
import pytest

def test_profiles_are_independent(tmp_path):
    repo=ProjectRepository(tmp_path);svc=ProfileService(repo);a=svc.create("A");b=svc.create("B")
    (repo.profile_dir(a.id)/"source"/"Novel - 25.txt").write_text("A",encoding="utf-8")
    assert not (repo.profile_dir(b.id)/"source"/"chapter_25.txt").exists()
    assert [p.name for p in repo.list_profiles()]==["A","B"]

def test_workflow_and_ordering():
    w=Workflow.defaults();s=WorkflowService.add_step(w,"custom")
    s.files=[StepFile(label="a",order=0),StepFile(label="b",order=1)];s.files[0].enabled=False
    copy=WorkflowService.duplicate_step(w,4);assert copy.id!=s.id and copy.files[0].id!=s.files[0].id
    assert WorkflowService.move(w.steps,5,-1)==4
    assert WorkflowService.move(s.files,0,1)==1 and s.files[1].order==1

def test_chapter_reference_resolves_without_editing_step(tmp_path):
    repo=ProjectRepository(tmp_path);p=NovelProfile(name="A");repo.save_profile(p);root=repo.profile_dir(p.id)
    step=WorkflowStep(name="terms",files=[StepFile(label="chapter",reference_type="dynamic",dynamic_reference="CURRENT_SOURCE_CHAPTER")])
    service=AssemblyService(repo)
    (root/"source"/"chapter_25.txt").write_text("chapter 25",encoding="utf-8")
    assert "chapter 25" in service.assemble(p,step,"## {FILE_NAME}")
    p.chapter_state.current_chapter=26;(root/"source"/"Novel - 26.txt").write_text("chapter 26",encoding="utf-8")
    assert "chapter 26" in service.assemble(p,step,"## {FILE_NAME}")

def test_traversal_and_json_recovery(tmp_path):
    repo=ProjectRepository(tmp_path);p=NovelProfile()
    with pytest.raises(ValueError):repo.resolve_project_path(p.id,"../../outside")
    f=tmp_path/"bad.json";raw='{"ok":true,}';f.write_text(raw,encoding="utf-8")
    assert read_json(f,{})=={"ok":True} and f.read_text(encoding="utf-8")==raw
    f.write_text('{"ok":',encoding="utf-8")
    with pytest.raises(ValueError):read_json(f,{})
