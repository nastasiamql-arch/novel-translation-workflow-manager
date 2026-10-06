import os
import subprocess
import sys
from pathlib import Path
import pytest
from novel_workflow.storage import write_json
from novel_workflow.update_bootstrap import APP_ID, HELPER, installer_arguments, read_update_result

ROOT=Path(__file__).resolve().parents[1]


def test_stable_installer_identity_and_update_mode():
    assert APP_ID == "B93AE24C-43D9-4D38-A880-93A607EA8D41"
    installer=(ROOT/'installer.iss').read_text(encoding='utf-8')
    assert f'AppId={{{{{APP_ID}}}' in installer
    assert 'UsePreviousAppDir=yes' in installer
    assert 'UsePreviousTasks=yes' in installer
    assert 'UsePreviousGroup=yes' in installer
    assert 'skipifsilent' not in installer
    assert "{param:PALANTIRUPDATE|0}" in installer
    assert 'NovelWorkflow.lnk' in installer
    assert 'NovelWorkflow\\*' in installer
    assert 'LOCALAPPDATA' not in installer and 'profiles' not in installer
    args=installer_arguments('C:/Existing Palantir', 'C:/Temp/update.log')
    assert '/PALANTIRUPDATE=1' in args and '/VERYSILENT' in args
    assert '/NORESTART' in args and '/CLOSEAPPLICATIONS' in args
    assert any(arg.startswith('/DIR=') for arg in args)
    assert any(arg.startswith('/LOG=') for arg in args)
    assert '/SUPPRESSMSGBOXES' not in args


@pytest.mark.skipif(sys.platform!='win32',reason='Windows updater integration')
@pytest.mark.parametrize('exit_code',[0,3])
def test_detached_helper_simulated_upgrade_preserves_data_and_path(tmp_path,exit_code):
    import hashlib
    install=tmp_path/'existing installation'; install.mkdir()
    data=tmp_path/'NovelWorkflow'; data.mkdir()
    (data/'profiles.json').write_text('{"legacy":"preserved"}',encoding='utf-8')
    shortcut=install/'Palantir Novel.lnk'; shortcut.write_text('existing',encoding='utf-8')
    executable=install/'Palantir.cmd'; executable.write_text('@echo off\r\nexit /b 0\r\n',encoding='utf-8')
    old=executable.read_bytes()
    new=tmp_path/'new-app.cmd'; new.write_text('@echo off\r\nrem new version\r\nexit /b 0\r\n',encoding='utf-8')
    installer=tmp_path/'simulated-setup.cmd'
    script='@echo off\r\n'
    if exit_code==0: script+=f'copy /y "{new}" "{executable}" >nul\r\n'
    script+=f'exit /b {exit_code}\r\n'
    installer.write_text(script,encoding='utf-8')
    payload=installer.read_bytes()
    exited=subprocess.Popen(['cmd.exe','/c','exit','0']); exited.wait()
    result=data/'result.json'; log=data/'update.log'
    manifest=data/'pending.json'
    write_json(manifest,dict(pid=exited.pid,installer=str(installer),executable=str(executable),
        install_dir=str(install),size=len(payload),sha256=hashlib.sha256(payload).hexdigest(),
        version='3.4.0',result=str(result),log=str(log)))
    helper=data/'helper.ps1'; helper.write_text(HELPER,encoding='utf-8-sig')
    completed=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(helper),'-Manifest',str(manifest)],capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,(completed.stdout,completed.stderr)
    import json
    outcome=json.loads(result.read_text(encoding='utf-8-sig'))
    assert outcome['success']==(exit_code==0),outcome
    assert outcome['exit_code']==exit_code
    assert (data/'profiles.json').read_text(encoding='utf-8')=='{"legacy":"preserved"}'
    assert list(install.glob('*.lnk'))==[shortcut]
    assert executable.read_bytes()==(new.read_bytes() if exit_code==0 else old)


def test_result_marker_is_consumed_once(tmp_path):
    updates=tmp_path/'updates'; updates.mkdir()
    write_json(updates/'result.json',dict(success=True,version='3.4.0'))
    assert read_update_result(tmp_path)==dict(success=True,version='3.4.0')
    assert read_update_result(tmp_path) is None
