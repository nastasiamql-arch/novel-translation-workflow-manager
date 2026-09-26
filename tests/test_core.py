import json
from novel_workflow.models import LaunchTarget, NovelGroup, NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.services import AssemblyService, ProfileService, WorkflowService
from novel_workflow.storage import ProjectRepository, read_json
from novel_workflow.launcher import LauncherService
import pytest

def test_profiles_are_independent(tmp_path):
    repo=ProjectRepository(tmp_path);svc=ProfileService(repo);a=svc.create("A");b=svc.create("B")
    (repo.profile_dir(a.id)/"source"/"chapter_25.txt").write_text("A",encoding="utf-8")
    assert not (repo.profile_dir(b.id)/"source"/"chapter_25.txt").exists()
    assert [p.name for p in repo.list_profiles()]==["A","B"]

def test_workflow_and_ordering():
    w=Workflow.defaults();s=WorkflowService.add_step(w,"custom")
    s.files=[StepFile(label="a",order=0),StepFile(label="b",order=1)];s.files[0].enabled=False
    copy=WorkflowService.duplicate_step(w,4);assert copy.id!=s.id and copy.files[0].id!=s.files[0].id
    assert WorkflowService.move(w.steps,5,-1)==4
    assert WorkflowService.move(s.files,0,1)==1 and s.files[1].order==1

def test_chapter_reference_resolves_without_editing_step(tmp_path):
    repo=ProjectRepository(tmp_path);p=NovelProfile(name="A");p.chapter_state.current_chapter=25;repo.save_profile(p);root=repo.profile_dir(p.id)
    step=WorkflowStep(name="terms",files=[StepFile(label="chapter",reference_type="dynamic",dynamic_reference="CURRENT_SOURCE_CHAPTER")])
    service=AssemblyService(repo)
    (root/"source"/"Novel - 25.txt").write_text("chapter 25",encoding="utf-8")
    assert "chapter 25" in service.assemble(p,step,"## {FILE_NAME}")
    p.chapter_state.current_chapter=26;(root/"source"/"Novel - 26.txt").write_text("chapter 26",encoding="utf-8")
    assert "chapter 26" in service.assemble(p,step,"## {FILE_NAME}")

def test_linked_source_uses_latest_contents(tmp_path):
    repo=ProjectRepository(tmp_path/"app");profile=NovelProfile(name="Linked")
    repo.save_profile(profile)
    source=tmp_path/"outside"/"chapter-25.txt";source.parent.mkdir();source.write_text("old chapter",encoding="utf-8")
    step=WorkflowStep(name="translate",files=[StepFile(label="Source",reference_type="external_file",path=str(source),order=0)])
    service=AssemblyService(repo)
    before=service.assemble(profile,step,"## {FILE_NAME}")
    source.write_text("updated chapter",encoding="utf-8")
    after=service.assemble(profile,step,"## {FILE_NAME}")
    assert "old chapter" in before and "updated chapter" not in before
    assert "updated chapter" in after and "old chapter" not in after

def test_traversal_and_json_recovery(tmp_path):
    repo=ProjectRepository(tmp_path);p=NovelProfile()
    with pytest.raises(ValueError):repo.resolve_project_path(p.id,"../../outside")
    f=tmp_path/"bad.json";raw='{"ok":true,}';f.write_text(raw,encoding="utf-8")
    assert read_json(f,{})=={"ok":True} and f.read_text(encoding="utf-8")==raw
    f.write_text('{"ok":',encoding="utf-8")
    with pytest.raises(ValueError):read_json(f,{})


def test_copy_advancement_cycles_through_workflow_steps():
    assert WorkflowService.next_index(0,4)==1
    assert WorkflowService.next_index(2,4)==3
    assert WorkflowService.next_index(3,4)==0
    assert WorkflowService.next_index(0,0)==-1


def test_launcher_profile_and_groups_are_saved_independently(tmp_path):
    repo=ProjectRepository(tmp_path)
    first=NovelProfile(name="A",main_folder=str(tmp_path/"A"),launch_targets=[LaunchTarget(label="Docs",kind="website",target="https://example.com",order=0)])
    second=NovelProfile(name="B")
    repo.save_profile(first);repo.save_profile(second)
    group=NovelGroup(name="Set",profile_ids=[first.id,second.id],description="work set")
    repo.save_groups([group])
    loaded={profile.id:profile for profile in repo.list_profiles()}
    assert loaded[first.id].main_folder==str(tmp_path/"A")
    assert loaded[first.id].launch_targets[0].target=="https://example.com"
    assert repo.load_groups()[0].profile_ids==[first.id,second.id]

def test_launcher_import_merges_targets_groups_and_preserves_source(tmp_path):
    repo=ProjectRepository(tmp_path/"app")
    existing=NovelProfile(name="Existing",main_folder=str(tmp_path/"novel"))
    repo.save_profile(existing)
    payload={
        "schemaVersion":8,
        "novels":[{"id":"old-novel-1","name":"Existing","mainFolder":str(tmp_path/"novel"),
          "status":"paused","contextPath":None,"translationGoal":{"targetChapters":20,"baselineChapter":4},
          "files":[{"id":"f1","name":"Glossary","path":str(tmp_path/"terms.md"),"enabled":True,"order":0}],
          "applications":[{"id":"a1","name":"Editor","executablePath":str(tmp_path/"editor.exe"),"arguments":["--profile","novel"],"enabled":True,"order":1}],
          "websites":[{"id":"w1","name":"Wiki","url":"https://example.com","enabled":False,"order":2}]}],
        "groups":[{"id":"old-group-1","name":"Reading Set","novelIds":["old-novel-1"],"description":"group"}]
    }
    source=tmp_path/"launcher.json"
    source.write_text(json.dumps(payload),encoding="utf-8")
    original=source.read_text(encoding="utf-8")
    result=repo.import_launcher_config(source)
    loaded=repo.list_profiles()[0]
    assert result=={"profiles":0,"groups":1,"launch_targets":3}
    assert source.read_text(encoding="utf-8")==original
    assert loaded.id==existing.id and loaded.status=="paused"
    assert loaded.translation_goal_target==20 and loaded.translation_goal_baseline==4
    assert [item.kind for item in loaded.launch_targets]==["file","application","website"]
    assert loaded.launch_targets[1].arguments==["--profile","novel"]
    assert repo.load_groups()[0].profile_ids==[existing.id]

def test_launcher_plan_opens_main_folder_and_enabled_items_in_order(tmp_path):
    profile=NovelProfile(main_folder=str(tmp_path/"novel"),launch_targets=[
        LaunchTarget(label="last",kind="file",target="z.txt",enabled=True,order=2),
        LaunchTarget(label="off",kind="file",target="off.txt",enabled=False,order=0),
        LaunchTarget(label="first",kind="application",target="tool.exe",order=1)])
    plan=LauncherService.build_plan(profile)
    assert [(item.kind,item.label) for item in plan]==[
        ("folder","โฟลเดอร์หลัก"),("application","first"),("file","last")]

def test_copy_advancement_cycles_through_workflow_steps():
    assert WorkflowService.next_index(0,4)==1
    assert WorkflowService.next_index(2,4)==3
    assert WorkflowService.next_index(3,4)==0
    assert WorkflowService.next_index(0,0)==-1
