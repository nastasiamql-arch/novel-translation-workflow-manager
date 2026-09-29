import json
from novel_workflow.models import LaunchTarget, NovelGroup, NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.services import AssemblyService, ProfileService, WorkflowService
from novel_workflow.storage import ProjectRepository, data_root, read_json
from novel_workflow.launcher import LauncherService
import pytest
from unittest.mock import call, patch

def test_profiles_are_independent(tmp_path):
    repo=ProjectRepository(tmp_path);svc=ProfileService(repo);a=svc.create("A");b=svc.create("B")
    (repo.profile_dir(a.id)/"source"/"chapter_25.txt").write_text("A",encoding="utf-8")
    assert not (repo.profile_dir(b.id)/"source"/"chapter_25.txt").exists()
    assert [p.name for p in repo.list_profiles()]==["A","B"]

def test_duplicate_profile_preserves_separate_vocabulary_step(tmp_path):
    repo=ProjectRepository(tmp_path)
    source=ProfileService(repo).create("A")
    source.vocabulary_step.files.append(StepFile(
        label="Current chapter",reference_type="dynamic",
        dynamic_reference="CURRENT_SOURCE_CHAPTER",
    ))
    repo.save_profile(source)

    duplicate=ProfileService(repo).duplicate(source,"A Copy")

    assert duplicate.vocabulary_step.name=="หาศัพท์"
    assert duplicate.vocabulary_step.files[0].dynamic_reference=="CURRENT_SOURCE_CHAPTER"

def test_workflow_and_ordering():
    w=Workflow.defaults();s=WorkflowService.add_step(w,"custom")
    s.files=[StepFile(label="a",order=0),StepFile(label="b",order=1)];s.files[0].enabled=False
    step_index=w.steps.index(s)
    copy=WorkflowService.duplicate_step(w,step_index);assert copy.id!=s.id and copy.files[0].id!=s.files[0].id
    assert WorkflowService.move(w.steps,step_index+1,-1)==step_index
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


@pytest.mark.parametrize("raw", ["", "   ", "\n\t"])
def test_read_json_empty_or_whitespace_returns_default_without_rewriting(tmp_path, raw):
    f=tmp_path/"empty.json"
    f.write_text(raw,encoding="utf-8")
    default={"safe":True}
    assert read_json(f,default) is default
    assert f.read_text(encoding="utf-8")==raw


def test_data_root_uses_clean_novelworkflow_namespace(tmp_path):
    with patch.dict("os.environ",{"LOCALAPPDATA":str(tmp_path)}):
        assert data_root()==tmp_path/"NovelWorkflow"


def test_copy_advancement_cycles_through_workflow_steps():
    assert WorkflowService.next_index(0,3)==1
    assert WorkflowService.next_index(1,3)==2
    assert WorkflowService.next_index(2,3)==0
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


def test_profile_order_and_browse_fields_load_save_and_legacy_defaults(tmp_path):
    repo=ProjectRepository(tmp_path)
    profile=NovelProfile(name="Ordered",order=7,last_browse_directory=str(tmp_path))
    repo.save_profile(profile)
    loaded=NovelProfile.from_dict(json.loads((repo.profile_dir(profile.id)/"profile.json").read_text(encoding="utf-8")))
    assert loaded.order==7 and loaded.last_browse_directory==str(tmp_path)
    legacy=NovelProfile.from_dict({"id":"a"*32,"name":"Legacy"})
    assert legacy.order==0 and legacy.last_browse_directory is None


def test_legacy_profiles_migrate_to_stable_name_order_then_persist(tmp_path):
    repo=ProjectRepository(tmp_path)
    for name,pid in (("Zulu","b"*32),("Alpha","a"*32)):
        folder=repo.profile_dir(pid);folder.mkdir(parents=True)
        (folder/"profile.json").write_text(json.dumps({"id":pid,"name":name}),encoding="utf-8")
    profiles=repo.list_profiles()
    assert [(profile.name,profile.order) for profile in profiles]==[("Alpha",0),("Zulu",1)]
    assert [json.loads((repo.profile_dir(profile.id)/"profile.json").read_text(encoding="utf-8"))["order"] for profile in profiles]==[0,1]


def test_profile_order_move_delete_and_restart_are_persistent(tmp_path):
    repo=ProjectRepository(tmp_path)
    service=ProfileService(repo)
    profiles=[service.create(name) for name in ("Zulu","Alpha","Mike")]
    assert [profile.name for profile in repo.list_profiles()]==["Zulu","Alpha","Mike"]
    repo.move_profile(profiles[2].id,-1)
    assert [profile.name for profile in repo.list_profiles()]==["Zulu","Mike","Alpha"]
    repo.move_profile(profiles[2].id,1)
    assert [profile.name for profile in repo.list_profiles()]==["Zulu","Alpha","Mike"]
    repo.move_profile(profiles[2].id,-2)
    reopened=ProjectRepository(tmp_path)
    assert [profile.name for profile in reopened.list_profiles()]==["Mike","Zulu","Alpha"]
    reopened.delete_profile(profiles[0].id)
    remaining=reopened.list_profiles()
    assert [(profile.name,profile.order) for profile in remaining]==[("Mike",0),("Alpha",1)]


def test_new_duplicate_and_rename_keep_deterministic_profile_order(tmp_path):
    repo=ProjectRepository(tmp_path/"app")
    service=ProfileService(repo)
    first=service.create("First")
    second=service.create("Second")
    duplicate=service.duplicate(first,"Copy")
    assert [p.id for p in repo.list_profiles()]==[first.id,second.id,duplicate.id]
    duplicate.name="Aardvark";repo.save_profile(duplicate)
    assert [p.id for p in repo.list_profiles()]==[first.id,second.id,duplicate.id]
    assert [(p.name,p.order) for p in repo.list_profiles()]==[("First",0),("Second",1),("Aardvark",2)]


def test_profile_browse_directory_fallback_and_memory_are_independent(tmp_path):
    repo=ProjectRepository(tmp_path/"app")
    main=tmp_path/"novel";main.mkdir()
    last_a=tmp_path/"external-a";last_a.mkdir()
    last_b=tmp_path/"external-b";last_b.mkdir()
    profile_a=ProfileService(repo).create("A")
    profile_b=ProfileService(repo).create("B")
    profile_a.main_folder=str(main)
    assert ProfileService.browse_directory(repo,profile_a)==main
    selected=last_a/"context.txt";selected.touch()
    ProfileService.remember_browse_directory(repo,profile_a,selected)
    ProfileService.remember_browse_directory(repo,profile_b,last_b)
    reopened=ProjectRepository(tmp_path/"app")
    loaded={p.id:p for p in reopened.list_profiles()}
    assert ProfileService.browse_directory(reopened,loaded[profile_a.id])==last_a
    assert ProfileService.browse_directory(reopened,loaded[profile_b.id])==last_b
    loaded[profile_a.id].last_browse_directory=str(tmp_path/"removed")
    assert ProfileService.browse_directory(reopened,loaded[profile_a.id])==main


def test_profile_browse_directory_falls_back_to_app_profile_then_home(tmp_path):
    repo=ProjectRepository(tmp_path/"app")
    profile=NovelProfile(id="c"*32,name="No folder")
    home=tmp_path/"home";home.mkdir()
    assert ProfileService.browse_directory(repo,profile,home)==home
    repo.save_profile(profile)
    assert ProfileService.browse_directory(repo,profile,home)==repo.profile_dir(profile.id)
    profile.last_browse_directory=str(tmp_path/"gone")
    assert ProfileService.browse_directory(repo,profile,home)==repo.profile_dir(profile.id)


def test_launcher_plan_opens_main_folder_and_enabled_items_in_order(tmp_path):
    profile=NovelProfile(main_folder=str(tmp_path/"novel"),launch_targets=[
        LaunchTarget(label="last",kind="file",target="z.txt",enabled=True,order=2),
        LaunchTarget(label="off",kind="file",target="off.txt",enabled=False,order=0),
        LaunchTarget(label="first",kind="application",target="tool.exe",order=1)])
    plan=LauncherService.build_plan(profile)
    assert [(item.kind,item.label) for item in plan]==[
        ("folder","โฟลเดอร์หลัก"),("application","first"),("file","last")]


@pytest.mark.parametrize("executable,expected", [
    ("Code.exe", True), ("code.exe", True), ("code.cmd", True), ("code", True),
    (r"C:\Users\X\AppData\Local\Programs\Microsoft VS Code\Code.exe", True),
    ('"C:\\Users\\X\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"', True),
    (r"C:\Users\X\AppData\Local\Programs\Microsoft VS Code Insiders\Code - Insiders.exe", True),
    ("code-insiders.bat", True),
    ("random-editor.exe", False), ("my-code-helper.exe", False),
])
def test_vscode_target_detection(executable, expected):
    entry=LaunchTarget(kind="application",target=executable)
    assert LauncherService.is_vscode_target(entry) is expected


@pytest.mark.parametrize("arguments", [
    ["--reuse-window", "--profile", "Novel"], ["-r", "--profile", "Novel"],
    ["--new-window", "--profile", "Novel"], ["-n", "--profile", "Novel"],
])
def test_vscode_arguments_force_one_new_window(arguments):
    normalized=LauncherService.normalized_vscode_arguments(arguments)
    assert "-r" not in normalized and "--reuse-window" not in normalized
    assert normalized.count("-n") + normalized.count("--new-window") == 1
    assert "--profile" in normalized and "Novel" in normalized


def test_vscode_profile_groups_folder_and_enabled_files_without_reopening_files(tmp_path):
    folder=tmp_path/"A";folder.mkdir()
    executable=tmp_path/"Code.exe";executable.touch()
    first=folder/"a.md";first.touch()
    second=folder/"b.txt";second.touch()
    profile=NovelProfile(main_folder=str(folder),launch_targets=[
        LaunchTarget(label="Code",kind="application",target=str(executable),arguments=["--reuse-window","--profile","Novel"],order=0),
        LaunchTarget(label="second",kind="file",target=str(second),order=2),
        LaunchTarget(label="first",kind="file",target=str(first),order=1),
        LaunchTarget(label="disabled file",kind="file",target=str(folder/"disabled.md"),enabled=False,order=3),
        LaunchTarget(label="disabled editor",kind="application",target=str(tmp_path/"disabled.exe"),enabled=False,order=4),
    ])
    with patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.os.startfile", create=True) as startfile:
        results=LauncherService().launch_profile(profile)
    command=popen.call_args.args[0]
    assert command == [str(executable),"--profile","Novel","--new-window",str(folder),str(first),str(second)]
    assert all(success for success,_ in results)
    startfile.assert_called_once_with(str(folder))


def test_default_vscode_file_association_groups_existing_profile_without_app_target(tmp_path):
    folder=tmp_path/"novel";folder.mkdir()
    executable=tmp_path/"Code.exe";executable.touch()
    first=folder/"chapter.md";first.touch()
    second=folder/"glossary.txt";second.touch()
    profile=NovelProfile(main_folder=str(folder),launch_targets=[
        LaunchTarget(label="chapter",kind="file",target=str(first),order=0),
        LaunchTarget(label="glossary",kind="file",target=str(second),order=1),
    ])
    with patch.object(LauncherService,"default_open_application",return_value=executable), \
         patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.os.startfile",create=True) as startfile:
        results=LauncherService().launch_profile(profile)
    assert all(success for success,_ in results)
    assert popen.call_count==1
    command=popen.call_args.args[0]
    assert command==[str(executable),"--new-window",str(folder),str(first),str(second)]
    startfile.assert_called_once_with(str(folder))


def test_vscode_profile_opens_main_folder_in_windows_file_explorer(tmp_path):
    folder=tmp_path/"novel";folder.mkdir()
    executable=tmp_path/"Code.exe";executable.touch()
    profile=NovelProfile(main_folder=str(folder),launch_targets=[
        LaunchTarget(label="Code",kind="application",target=str(executable),order=0),
    ])
    with patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.os.startfile",create=True) as startfile:
        results=LauncherService().launch_profile(profile)
    assert all(success for success,_ in results)
    assert popen.call_count==1
    assert str(folder) in popen.call_args.args[0]
    startfile.assert_called_once_with(str(folder))


def test_default_non_vscode_association_keeps_file_association_behavior(tmp_path):
    file=tmp_path/"notes.md";file.touch()
    editor=tmp_path/"other-editor.exe";editor.touch()
    profile=NovelProfile(launch_targets=[LaunchTarget(kind="file",target=str(file))])
    with patch.object(LauncherService,"default_open_application",return_value=editor), \
         patch("novel_workflow.launcher.os.startfile",create=True) as startfile, \
         patch("novel_workflow.launcher.subprocess.Popen") as popen:
        LauncherService().launch_profile(profile)
    startfile.assert_called_once_with(str(file))
    popen.assert_not_called()


def test_vscode_primary_is_first_by_order_and_explicit_folder_stays_separate(tmp_path):
    code=tmp_path/"code";code.touch()
    other_code=tmp_path/"code.cmd";other_code.touch()
    explicit=tmp_path/"extra";explicit.mkdir()
    profile=NovelProfile(launch_targets=[
        LaunchTarget(label="later editor",kind="application",target=str(other_code),order=5),
        LaunchTarget(label="extra",kind="folder",target=str(explicit),order=3),
        LaunchTarget(label="primary",kind="application",target=str(code),order=1),
    ])
    with patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.os.startfile", create=True) as startfile:
        LauncherService().launch_profile(profile)
    assert popen.call_count==2
    assert popen.call_args_list[0].args[0][:2]==[str(code),"--new-window"]
    startfile.assert_called_once_with(str(explicit))


def test_non_vscode_targets_and_website_keep_existing_behavior(tmp_path):
    tool=tmp_path/"tool.exe";tool.touch()
    profile=NovelProfile(launch_targets=[
        LaunchTarget(label="tool",kind="application",target=str(tool),arguments=["--safe"]),
        LaunchTarget(label="site",kind="website",target="https://example.com"),
    ])
    with patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.webbrowser.open",return_value=True) as open_site:
        results=LauncherService().launch_profile(profile)
    assert all(success for success,_ in results)
    popen.assert_called_once_with([str(tool),"--safe"],shell=False)
    open_site.assert_called_once_with("https://example.com")


def test_profile_without_vscode_keeps_file_association_behavior(tmp_path):
    file=tmp_path/"notes.md";file.touch()
    profile=NovelProfile(launch_targets=[LaunchTarget(kind="file",target=str(file))])
    with patch.object(LauncherService,"default_open_application",return_value=None), \
         patch("novel_workflow.launcher.os.startfile",create=True) as startfile, \
         patch("novel_workflow.launcher.subprocess.Popen") as popen:
        LauncherService().launch_profile(profile)
    startfile.assert_called_once_with(str(file))
    popen.assert_not_called()


def test_open_group_launches_one_isolated_vscode_invocation_per_profile(tmp_path):
    profiles=[]
    for name in ("A","B"):
        folder=tmp_path/name;folder.mkdir()
        code=folder/"Code.exe";code.touch()
        files=[]
        for filename in (f"{name.lower()}1.md",f"{name.lower()}2.md"):
            path=folder/filename;path.touch()
            files.append(LaunchTarget(kind="file",target=str(path),order=len(files)+1))
        profiles.append(NovelProfile(name=name,main_folder=str(folder),launch_targets=[LaunchTarget(kind="application",target=str(code),order=0),*files]))
    group=NovelGroup(name="AB",profile_ids=[profile.id for profile in profiles])
    with patch("novel_workflow.launcher.subprocess.Popen") as popen, \
         patch("novel_workflow.launcher.os.startfile",create=True) as startfile:
        results=LauncherService().launch_group(group,profiles)
    assert all(success for success,_ in results)
    assert popen.call_count==2
    command_a,command_b=[call.args[0] for call in popen.call_args_list]
    assert str(tmp_path/"A") in command_a and all("\\B\\" not in arg for arg in command_a)
    assert str(tmp_path/"B") in command_b and all("\\A\\" not in arg for arg in command_b)
    assert "--new-window" in command_a and "--new-window" in command_b
    assert startfile.call_args_list==[
        call(str(tmp_path/"A")),call(str(tmp_path/"B"))
    ]

def test_copy_advancement_cycles_through_workflow_steps():
    assert WorkflowService.next_index(0,4)==1
    assert WorkflowService.next_index(2,4)==3
    assert WorkflowService.next_index(3,4)==0
    assert WorkflowService.next_index(0,0)==-1
