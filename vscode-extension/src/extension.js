'use strict';

const vscode = require('vscode');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const core = require('./core');
const { copyFileDropList } = require('./clipboard');

function safeProfileLabel(profile) {
  const chapter = Number(profile.chapter_state?.current_chapter || 1);
  const today = core.todayChapterCount(profile);
  const goal = core.goalProgress(profile);
  const progress = goal ? ` · เป้า ${goal.completed}/${goal.target}` : '';
  return `${profile.name} · บท ${chapter}${progress} · วันนี้ +${today}`;
}

function cloneWorkflow(workflow) {
  const result = structuredClone(workflow);
  for (const step of result.steps || []) {
    step.id = core.newId();
    step.files = (step.files || []).map(file => ({ ...file, id: core.newId() }));
  }
  return result;
}

class NovelTreeProvider {
  constructor(root, state) { this.root = root; this.state = state; this.emitter = new vscode.EventEmitter(); this.onDidChangeTreeData = this.emitter.event; }
  refresh() { this.emitter.fire(); }
  getTreeItem(node) {
    const item = new vscode.TreeItem(node.label, node.type === 'profile' || node.type === 'group' ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.None);
    item.contextValue = node.type === 'stepFile' ? 'novelStepFile' : node.type === 'step' ? 'novelStep' : node.type === 'profile' ? 'novelProfile' : node.type === 'group' ? 'novelGroup' : 'novelGroupMember';
    if (node.type === 'profile') {
      item.description = this.state.profileId === node.profile.id ? 'เลือกอยู่' : '';
      const cover = node.profile.cover_image_path;
      if (cover) {
        try {
          const file = core.containedPath(core.profileDirectory(this.root, node.profile.id), cover);
          if (fs.existsSync(file)) item.iconPath = vscode.Uri.file(file);
        } catch { /* invalid cover paths are ignored; profile data remains untouched */ }
      }
      item.iconPath ||= new vscode.ThemeIcon(this.state.profileId === node.profile.id ? 'book' : 'book');
      item.command = { command: 'novelWorkflow.selectProfile', title: 'Select novel', arguments: [node.profile.id] };
      item.tooltip = node.profile.name;
    } else if (node.type === 'group') {
      item.iconPath = new vscode.ThemeIcon('library');
      item.command = { command: 'novelWorkflow.openGroup', title: 'Open group', arguments: [node.group.id] };
    } else if (node.type === 'step') {
      item.iconPath = new vscode.ThemeIcon(this.state.stepId === node.step.id && this.state.profileId === node.profile.id ? 'circle-filled' : 'list-ordered');
      item.command = { command: 'novelWorkflow.selectStep', title: 'Select step', arguments: [node.profile.id, node.step.id] };
      item.tooltip = node.step.name;
    } else if (node.type === 'stepFile') {
      item.iconPath = new vscode.ThemeIcon(node.file.enabled ? 'check' : 'circle-outline');
      item.command = { command: 'novelWorkflow.openFile', title: 'Open file', arguments: [node.profile.id, node.step.id, node.file.id] };
      item.tooltip = node.file.reference_type === 'dynamic' ? `${node.file.label} · ${node.file.dynamic_reference}` : `${node.file.label} · ${node.file.path || ''}`;
    } else if (node.type === 'member') {
      item.iconPath = new vscode.ThemeIcon('book');
      item.command = { command: 'novelWorkflow.selectProfile', title: 'Select novel', arguments: [node.profile.id] };
    }
    return item;
  }
  getChildren(node) {
    let profiles;
    try { profiles = core.listProfiles(this.root); } catch (error) { return Promise.reject(error); }
    if (!node) {
      let groups = [];
      try { groups = core.readJson(path.join(this.root, 'groups.json'), []); } catch (error) { return Promise.reject(error); }
      return [
        ...groups.filter(group => group && group.name).map(group => ({ type: 'group', group, label: group.name })),
        ...profiles.map(profile => ({ type: 'profile', profile, label: safeProfileLabel(profile) }))
      ];
    }
    if (node.type === 'profile') return node.profile.workflow.steps.map((step, index) => ({ type: 'step', profile: node.profile, step, label: `${index + 1}. ${step.name}` }));
    if (node.type === 'step') return [...node.step.files].sort((a, b) => Number(a.order || 0) - Number(b.order || 0)).map(file => ({ type: 'stepFile', profile: node.profile, step: node.step, file, label: `${file.enabled ? '☑' : '☐'} ${file.label || file.path || file.dynamic_reference || 'ไฟล์'}` }));
    if (node.type === 'group') return (node.group.profile_ids || []).map(id => profiles.find(profile => profile.id === id)).filter(Boolean).map(profile => ({ type: 'member', profile, label: safeProfileLabel(profile) }));
    return [];
  }
}

function activate(context) {
  const config = vscode.workspace.getConfiguration('novelWorkflow');
  const configuredRoot = config.get('dataRoot', '').trim();
  const root = path.resolve(configuredRoot || core.defaultDataRoot());
  fs.mkdirSync(path.join(root, 'profiles'), { recursive: true });
  const state = {
    profileId: context.workspaceState.get('novelWorkflow.profileId'),
    stepId: context.workspaceState.get('novelWorkflow.stepId')
  };
  const provider = new NovelTreeProvider(root, state);
  const tree = vscode.window.createTreeView('novelWorkflow.profiles', { treeDataProvider: provider, showCollapseAll: true });
  context.subscriptions.push(tree);

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 20);
  status.command = 'novelWorkflow.setChapter';
  context.subscriptions.push(status);
  const copyAction = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  copyAction.text = '$(files) COPY STEP';
  copyAction.tooltip = 'คัดลอกไฟล์ของขั้นตอนปัจจุบัน แล้วเลื่อนไปขั้นตอนถัดไป';
  copyAction.command = 'novelWorkflow.copyStep';
  context.subscriptions.push(copyAction);

  const profiles = () => core.listProfiles(root);
  const profileFor = id => {
    const profile = profiles().find(item => item.id === (id || state.profileId));
    if (!profile) throw new Error('ไม่พบนิยายที่เลือก');
    return profile;
  };
  const stepFor = (profile, id) => {
    const step = profile.workflow.steps.find(item => item.id === (id || state.stepId));
    if (!step) throw new Error('ไม่พบขั้นตอนที่เลือก');
    return step;
  };
  const save = profile => core.saveProfile(root, profile);
  const refresh = () => {
    provider.refresh();
    updateStatus();
    vscode.commands.executeCommand('setContext', 'novelWorkflow.hasStep', Boolean(state.profileId && state.stepId));
  };
  const setSelection = async (profile, stepId) => {
    state.profileId = profile.id;
    state.stepId = stepId || profile.workflow.steps[0]?.id;
    await context.workspaceState.update('novelWorkflow.profileId', state.profileId);
    await context.workspaceState.update('novelWorkflow.stepId', state.stepId);
    const settingsFile = path.join(root, 'settings.json');
    const settings = core.readJson(settingsFile, {});
    settings.last_profile_id = profile.id;
    core.atomicWriteJson(settingsFile, settings);
    refresh();
  };
  const notifyError = error => vscode.window.showErrorMessage(`NovelWorkflow: ${error.message || error}`);
  const run = fn => async (...args) => { try { return await fn(...args); } catch (error) { return notifyError(error); } };
  const showChapterStatus = profile => `${safeProfileLabel(profile)}`;

  function updateStatus() {
    try {
      const profile = profileFor();
      status.text = `$(book) ${showChapterStatus(profile)}`;
      status.tooltip = 'เลือกเพื่อเปลี่ยนบทปัจจุบัน';
      status.show();
      if (state.stepId && profile.workflow.steps.some(step => step.id === state.stepId)) copyAction.show();
      else copyAction.hide();
    } catch { status.hide(); copyAction.hide(); }
  }

  async function selectProfile(id) {
    const profile = profileFor(id);
    await setSelection(profile);
  }

  const register = (name, fn) => context.subscriptions.push(vscode.commands.registerCommand(`novelWorkflow.${name}`, run(fn)));

  register('refresh', async () => {
    for (const profile of profiles()) if (core.syncContext(profile)) save(profile);
    refresh();
    vscode.window.setStatusBarMessage('NovelWorkflow อัปเดตแล้ว', 1800);
  });
  register('selectProfile', selectProfile);
  register('selectStep', async (profileId, stepId) => {
    const profile = profileFor(profileId);
    await setSelection(profile, stepId);
  });
  register('createProfile', async () => {
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อเรื่องนิยาย', placeHolder: 'เช่น นิยาย A', ignoreFocusOut: true });
    if (name === undefined) return;
    const templates = core.loadTemplates(root);
    const choice = await vscode.window.showQuickPick(templates.map(item => ({ label: item.name, description: `${item.workflow.steps.length} ขั้นตอน`, item })), { placeHolder: 'เลือก workflow template' });
    if (!choice) return;
    if (profiles().some(profile => profile.name.trim().toLocaleLowerCase() === String(name).trim().toLocaleLowerCase())) throw new Error('มีนิยายชื่อนี้อยู่แล้ว');
    const profile = core.createProfile(name, cloneWorkflow(choice.item.workflow));
    save(profile);
    await setSelection(profile);
    vscode.window.showInformationMessage(`สร้าง ${profile.name} แล้ว`);
  });
  register('renameProfile', async id => {
    const profile = profileFor(id);
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อใหม่', value: profile.name, ignoreFocusOut: true });
    if (name === undefined || !name.trim()) return;
    profile.name = name.trim(); save(profile); refresh();
  });
  register('duplicateProfile', async id => {
    const source = profileFor(id);
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อโปรไฟล์สำเนา', value: `${source.name} Copy`, ignoreFocusOut: true });
    if (name === undefined || !name.trim()) return;
    const options = await vscode.window.showQuickPick([
      { label: 'ไม่คัดลอก glossary/characters', value: false },
      { label: 'คัดลอก glossary/characters ด้วย', value: true }
    ], { placeHolder: 'เลือกข้อมูลเสริมที่จะคัดลอก' });
    if (!options) return;
    const copy = structuredClone(source);
    copy.id = core.newId(); copy.name = name.trim();
    copy.chapter_state = { current_chapter: 1, statuses: {} }; copy.main_folder = ''; copy.launch_targets = [];
    copy.context_path = null; copy.translation_goal_target = null; copy.translation_goal_baseline = null;
    copy.translation_checkpoint_path = null; copy.translation_daily_activity = {}; copy.cover_image_path = null;
    for (const step of copy.workflow.steps) {
      step.id = core.newId();
      step.files = step.files.filter(file => file.reference_type === 'dynamic' || (file.reference_type === 'repository_file' && (file.path.startsWith('prompts/') || file.path.startsWith('style/') || (options.value && (file.path.startsWith('glossary/') || file.path.startsWith('characters/')))))).map(file => ({ ...file, id: core.newId() }));
    }
    save(copy);
    const sourceDir = core.profileDirectory(root, source.id); const destDir = core.profileDirectory(root, copy.id);
    for (const category of ['prompts', 'style', ...(options.value ? ['glossary', 'characters'] : [])]) {
      const from = path.join(sourceDir, category);
      if (fs.existsSync(from)) fs.cpSync(from, path.join(destDir, category), { recursive: true });
    }
    await setSelection(copy);
    vscode.window.showInformationMessage(`ทำสำเนา ${source.name} เป็น ${copy.name} แล้ว`);
  });
  register('deleteProfile', async id => {
    const profile = profileFor(id);
    const answer = await vscode.window.showWarningMessage(`ลบโปรไฟล์ “${profile.name}” และข้อมูลในโฟลเดอร์ของโปรไฟล์หรือไม่?`, { modal: true }, 'ลบโปรไฟล์');
    if (answer !== 'ลบโปรไฟล์') return;
    const dir = core.profileDirectory(root, profile.id);
    fs.rmSync(dir, { recursive: true, force: false });
    const groupsFile = path.join(root, 'groups.json');
    const groups = core.readJson(groupsFile, []);
    for (const group of groups) group.profile_ids = (group.profile_ids || []).filter(pid => pid !== profile.id);
    core.atomicWriteJson(groupsFile, groups);
    const settingsFile = path.join(root, 'settings.json');
    const settings = core.readJson(settingsFile, {});
    if (settings.last_profile_id === profile.id) { delete settings.last_profile_id; core.atomicWriteJson(settingsFile, settings); }
    if (state.profileId === profile.id) { state.profileId = undefined; state.stepId = undefined; await context.workspaceState.update('novelWorkflow.profileId', undefined); await context.workspaceState.update('novelWorkflow.stepId', undefined); }
    refresh(); vscode.window.showInformationMessage(`ลบ ${profile.name} แล้ว`);
  });
  register('openProfile', async id => {
    const profile = profileFor(id); const targets = [];
    if (profile.main_folder) targets.push({ kind: 'folder', target: profile.main_folder, label: 'โฟลเดอร์นิยาย' });
    targets.push(...(profile.launch_targets || []).filter(target => target.enabled));
    if (!targets.length) {
      const folder = await vscode.window.showOpenDialog({ canSelectFolders: true, canSelectFiles: false, canSelectMany: false, openLabel: 'เลือกโฟลเดอร์นิยาย' });
      if (!folder?.[0]) return;
      profile.main_folder = folder[0].fsPath; save(profile);
      await vscode.commands.executeCommand('vscode.openFolder', folder[0], true);
      return;
    }
    for (const target of targets) await openTarget(target);
  });
  register('openProfileManager', async id => {
    const profile = profileFor(id);
    const folder = core.profileDirectory(root, profile.id);
    await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(folder), true);
  });
  register('setChapter', async id => {
    const profile = profileFor(id);
    const chapter = await vscode.window.showInputBox({ prompt: 'บทปัจจุบัน', value: String(profile.chapter_state.current_chapter || 1), validateInput: value => /^\d+$/.test(value) && Number(value) > 0 ? null : 'ใส่เลขบทเป็นจำนวนเต็มที่มากกว่า 0', ignoreFocusOut: true });
    if (chapter === undefined) return;
    profile.chapter_state.current_chapter = Number(chapter); save(profile); refresh();
  });
  register('setContextFile', async id => {
    const profile = profileFor(id);
    const file = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: false, filters: { 'Context files': ['md', 'txt', 'json'] }, openLabel: 'เลือกไฟล์ Context' });
    if (!file?.[0]) return;
    const chapter = core.latestContextChapter(fs.readFileSync(file[0].fsPath, 'utf8'));
    if (chapter === null) throw new Error('ไม่พบหัวข้อ “บทที่ <เลขบท>” ในไฟล์');
    profile.context_path = file[0].fsPath; profile.translation_checkpoint_path = file[0].fsPath;
    profile.chapter_state.current_chapter = chapter; save(profile); refresh();
    vscode.window.showInformationMessage(`เชื่อม Context แล้ว · บทล่าสุด ${chapter}`);
  });
  register('setCover', async id => {
    const profile = profileFor(id);
    const image = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: false, filters: { Images: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }, openLabel: 'เลือกรูปปก' });
    if (!image?.[0]) return;
    const ext = path.extname(image[0].fsPath).toLowerCase();
    const cover = path.join(core.profileDirectory(root, profile.id), 'covers', `cover${ext}`);
    fs.mkdirSync(path.dirname(cover), { recursive: true }); fs.copyFileSync(image[0].fsPath, cover);
    profile.cover_image_path = path.relative(core.profileDirectory(root, profile.id), cover).split(path.sep).join('/'); save(profile); refresh();
  });
  register('removeCover', async id => {
    const profile = profileFor(id);
    if (!profile.cover_image_path) return;
    const answer = await vscode.window.showWarningMessage('เอารูปปกของนิยายนี้ออกหรือไม่?', { modal: true }, 'เอารูปออก');
    if (answer !== 'เอารูปออก') return;
    const cover = core.containedPath(core.profileDirectory(root, profile.id), profile.cover_image_path);
    if (fs.existsSync(cover)) fs.unlinkSync(cover);
    profile.cover_image_path = null; save(profile); refresh();
  });
  register('setGoal', async id => {
    const profile = profileFor(id);
    const target = await vscode.window.showInputBox({ prompt: 'จำนวนบทในเป้าหมาย', value: String(profile.translation_goal_target || 10), validateInput: value => /^\d+$/.test(value) && Number(value) > 0 ? null : 'ใส่จำนวนเต็มตั้งแต่ 1 ขึ้นไป' });
    if (target === undefined) return;
    if (profile.translation_goal_baseline == null) profile.translation_goal_baseline = profile.chapter_state.current_chapter || 1;
    profile.translation_goal_target = Number(target); save(profile); refresh();
  });
  register('resetGoal', async id => {
    const profile = profileFor(id);
    if (!core.goalProgress(profile)) throw new Error('ยังไม่มีเป้าหมายของเรื่องนี้');
    const answer = await vscode.window.showWarningMessage(`เริ่มนับเป้าหมายใหม่จากบท ${profile.chapter_state.current_chapter}?`, { modal: true }, 'รีเซ็ต');
    if (answer !== 'รีเซ็ต') return;
    profile.translation_goal_baseline = profile.chapter_state.current_chapter; save(profile); refresh();
  });
  register('showProgress', async () => {
    const all = profiles();
    if (!all.length) { vscode.window.showInformationMessage('ยังไม่มีโปรไฟล์นิยาย'); return; }
    for (const profile of all) if (core.syncContext(profile)) save(profile);
    const days = [];
    for (let offset = 6; offset >= 0; offset -= 1) { const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - offset); days.push(core.localDay(day.getTime())); }
    const rows = all.map(profile => {
      const goal = core.goalProgress(profile);
      const activity = days.map(day => (profile.translation_daily_activity?.[day] || []).length);
      return `| ${String(profile.name).replaceAll('|', '\\|')} | ${profile.chapter_state.current_chapter || 1} | ${core.todayChapterCount(profile)} | ${activity.reduce((a, b) => a + b, 0)} | ${goal ? `${goal.completed}/${goal.target} (${goal.percentage}%)` : '—'} | ${activity.join(' · ')} |`;
    });
    const totalToday = all.reduce((sum, profile) => sum + core.todayChapterCount(profile), 0);
    const totalWeek = all.reduce((sum, profile) => sum + core.weekChapterCount(profile), 0);
    const text = [
      '# ความคืบหน้าการแปล',
      '',
      `วันนี้รวม **${totalToday} บท** · สัปดาห์นี้ **${totalWeek} บท**`,
      '',
      '| นิยาย | บทล่าสุด | วันนี้ | 7 วัน | เป้าหมาย | รายวัน (เก่า → ใหม่) |',
      '|---|---:|---:|---:|---:|---|',
      ...rows,
      '',
      'นับจากบทที่เพิ่มขึ้นในไฟล์ Context และใช้วันที่แก้ไขไฟล์ตามเวลาท้องถิ่นของเครื่อง'
    ].join('\n');
    const document = await vscode.workspace.openTextDocument({ language: 'markdown', content: text });
    await vscode.window.showTextDocument(document, { preview: false });
  });
  register('addStep', async id => {
    const profile = profileFor(id);
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อขั้นตอนใหม่', ignoreFocusOut: true });
    if (name === undefined || !name.trim()) return;
    profile.workflow.steps.push({ id: core.newId(), name: name.trim(), files: [] }); save(profile);
    await setSelection(profile, profile.workflow.steps.at(-1).id);
  });
  register('createWorkflowTemplate', async () => {
    const profile = profileFor();
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อ workflow template', value: `${profile.name} workflow`, ignoreFocusOut: true });
    if (!name?.trim()) return;
    const templates = core.loadTemplates(root);
    if (templates.some(item => item.name.toLocaleLowerCase() === name.trim().toLocaleLowerCase())) throw new Error('มี template ชื่อนี้แล้ว');
    templates.push({ name: name.trim(), workflow: cloneWorkflow(profile.workflow) });
    core.atomicWriteJson(path.join(root, 'templates.json'), templates);
    vscode.window.showInformationMessage(`บันทึก template “${name.trim()}” แล้ว`);
  });
  register('applyWorkflowTemplate', async () => {
    const profile = profileFor(); const templates = core.loadTemplates(root);
    const choice = await vscode.window.showQuickPick(templates.map(item => ({ label: item.name, description: `${item.workflow.steps.length} ขั้นตอน`, item })), { placeHolder: 'เลือก template ที่จะใช้แทน workflow ปัจจุบัน' });
    if (!choice) return;
    const answer = await vscode.window.showWarningMessage('แทนที่ workflow ปัจจุบันหรือไม่? ไฟล์ในโปรไฟล์จะไม่ถูกลบ', { modal: true }, 'แทนที่ workflow');
    if (answer !== 'แทนที่ workflow') return;
    profile.workflow = cloneWorkflow(choice.item.workflow); save(profile); await setSelection(profile);
  });
  register('renameStep', async (_node, id) => {
    const profile = profileFor(_node?.profile?.id); const step = stepFor(profile, id || _node?.step?.id);
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อขั้นตอน', value: step.name, ignoreFocusOut: true });
    if (name === undefined || !name.trim()) return;
    step.name = name.trim(); save(profile); refresh();
  });
  register('duplicateStep', async id => {
    const profile = profileFor(); const step = stepFor(profile, id);
    const duplicate = structuredClone(step); duplicate.id = core.newId(); duplicate.name = `${step.name} copy`;
    duplicate.files = duplicate.files.map(file => ({ ...file, id: core.newId() }));
    profile.workflow.steps.splice(profile.workflow.steps.indexOf(step) + 1, 0, duplicate); save(profile);
    await setSelection(profile, duplicate.id);
  });
  register('deleteStep', async id => {
    const profile = profileFor(); const step = stepFor(profile, id);
    const answer = await vscode.window.showWarningMessage(`เอาขั้นตอน “${step.name}” ออกจาก workflow หรือไม่? ไฟล์จริงจะไม่ถูกลบ`, { modal: true }, 'เอาขั้นตอนออก');
    if (answer !== 'เอาขั้นตอนออก') return;
    profile.workflow.steps = profile.workflow.steps.filter(item => item.id !== step.id); save(profile);
    await setSelection(profile, profile.workflow.steps[0]?.id);
  });
  const moveStep = delta => run(async () => {
    const profile = profileFor(); const step = stepFor(profile); const from = profile.workflow.steps.indexOf(step);
    const to = Math.max(0, Math.min(profile.workflow.steps.length - 1, from + delta));
    profile.workflow.steps.splice(to, 0, profile.workflow.steps.splice(from, 1)[0]); save(profile); await setSelection(profile, step.id);
  });
  context.subscriptions.push(vscode.commands.registerCommand('novelWorkflow.moveStepUp', moveStep(-1)));
  context.subscriptions.push(vscode.commands.registerCommand('novelWorkflow.moveStepDown', moveStep(1)));

  register('addFiles', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const files = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: true, filters: { 'Text files': ['txt', 'md', 'json'] }, openLabel: 'เพิ่มไฟล์ในขั้นตอน' });
    if (!files?.length) return;
    const profileRoot = core.profileDirectory(root, profile.id);
    let added = 0;
    for (const uri of files) {
      const file = uri.fsPath; const extension = path.extname(file).toLowerCase();
      if (!core.EXTENSIONS.has(extension)) continue;
      const inside = path.resolve(file).startsWith(`${path.resolve(profileRoot)}${path.sep}`);
      const referenceType = inside ? 'repository_file' : 'external_file';
      const storedPath = inside ? path.relative(profileRoot, file).split(path.sep).join('/') : file;
      if (step.files.some(item => item.reference_type === referenceType && item.path === storedPath)) continue;
      step.files.push({ id: core.newId(), label: path.parse(file).name, reference_type: referenceType, path: storedPath, dynamic_reference: null, file_type: path.basename(path.dirname(file)), enabled: true, order: step.files.length });
      added += 1;
    }
    save(profile); refresh(); vscode.window.showInformationMessage(`เพิ่มไฟล์ ${added} รายการ`);
  });
  register('importFile', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const file = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: false, filters: { 'Text files': ['txt', 'md', 'json'] }, openLabel: 'นำเข้าไฟล์' });
    if (!file?.[0]) return;
    const category = await vscode.window.showQuickPick(core.CATEGORIES, { placeHolder: 'เลือกหมวดเก็บไฟล์' });
    if (!category) return;
    const source = file[0].fsPath; const destination = path.join(core.profileDirectory(root, profile.id), category, path.basename(source));
    if (fs.existsSync(destination)) throw new Error('มีชื่อไฟล์นี้ในหมวดดังกล่าวแล้ว');
    fs.mkdirSync(path.dirname(destination), { recursive: true }); fs.copyFileSync(source, destination);
    step.files.push({ id: core.newId(), label: path.parse(destination).name, reference_type: 'repository_file', path: path.relative(core.profileDirectory(root, profile.id), destination).split(path.sep).join('/'), dynamic_reference: null, file_type: category, enabled: true, order: step.files.length });
    save(profile); refresh(); await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(destination));
  });
  register('createFile', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const relative = await vscode.window.showInputBox({ prompt: 'ตำแหน่งไฟล์ในโปรไฟล์', placeHolder: 'prompts/find_terms.txt', ignoreFocusOut: true, validateInput: value => core.EXTENSIONS.has(path.extname(value).toLowerCase()) ? null : 'รองรับ .txt, .md และ .json' });
    if (!relative) return;
    const target = core.containedPath(core.profileDirectory(root, profile.id), relative.replaceAll('/', path.sep));
    if (fs.existsSync(target)) throw new Error('มีไฟล์นี้อยู่แล้ว');
    fs.mkdirSync(path.dirname(target), { recursive: true }); fs.writeFileSync(target, '', { flag: 'wx' });
    const answer = await vscode.window.showQuickPick(['สร้างไฟล์อย่างเดียว', 'สร้างและเพิ่มในขั้นตอนปัจจุบัน'], { placeHolder: `ขั้นตอน: ${step.name}` });
    if (answer === 'สร้างและเพิ่มในขั้นตอนปัจจุบัน') {
      step.files.push({ id: core.newId(), label: path.parse(target).name, reference_type: 'repository_file', path: path.relative(core.profileDirectory(root, profile.id), target).split(path.sep).join('/'), dynamic_reference: null, file_type: path.basename(path.dirname(target)), enabled: true, order: step.files.length });
      save(profile); refresh();
    }
    await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target));
  });
  register('replaceStepFile', async node => {
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, node?.step?.id);
    const item = step.files.find(file => file.id === node?.file?.id);
    if (!item || item.reference_type === 'dynamic') throw new Error('เลือกไฟล์ปกติเพื่อเปลี่ยนการอ้างอิง');
    const replacement = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: false, filters: { 'Text files': ['txt', 'md', 'json'] }, openLabel: 'เลือกไฟล์ใหม่' });
    if (!replacement?.[0]) return;
    const file = replacement[0].fsPath; const profileRoot = core.profileDirectory(root, profile.id);
    const inside = path.resolve(file).startsWith(`${path.resolve(profileRoot)}${path.sep}`);
    item.reference_type = inside ? 'repository_file' : 'external_file';
    item.path = inside ? path.relative(profileRoot, file).split(path.sep).join('/') : file;
    save(profile); refresh();
  });
  register('renameFileLabel', async node => {
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, node?.step?.id);
    const item = step.files.find(file => file.id === node?.file?.id);
    if (!item) throw new Error('ไม่พบไฟล์');
    const label = await vscode.window.showInputBox({ prompt: 'ชื่อที่แสดงในขั้นตอน', value: item.label || item.path || item.dynamic_reference });
    if (label === undefined || !label.trim()) return;
    item.label = label.trim(); save(profile); refresh();
  });
  const moveFile = delta => run(async node => {
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, node?.step?.id);
    const item = step.files.find(file => file.id === node?.file?.id);
    if (!item) throw new Error('ไม่พบไฟล์');
    const from = step.files.indexOf(item); const to = Math.max(0, Math.min(step.files.length - 1, from + delta));
    step.files.splice(to, 0, step.files.splice(from, 1)[0]); step.files.forEach((file, index) => { file.order = index; });
    save(profile); refresh();
  });
  context.subscriptions.push(vscode.commands.registerCommand('novelWorkflow.moveFileUp', moveFile(-1)));
  context.subscriptions.push(vscode.commands.registerCommand('novelWorkflow.moveFileDown', moveFile(1)));
  register('searchProjectFiles', async () => {
    const profile = profileFor(); const dir = core.profileDirectory(root, profile.id);
    const files = [];
    const walk = folder => { for (const entry of fs.readdirSync(folder, { withFileTypes: true })) { const item = path.join(folder, entry.name); if (entry.isDirectory()) walk(item); else if (entry.name !== 'profile.json') files.push(item); } };
    walk(dir);
    const choice = await vscode.window.showQuickPick(files.map(file => ({ label: path.relative(dir, file).split(path.sep).join('/'), description: path.extname(file), file })), { placeHolder: `ค้นหาไฟล์ใน ${profile.name}`, matchOnDescription: true });
    if (choice) await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(choice.file));
  });
  register('deleteProjectFile', async node => {
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, node?.step?.id);
    const item = step.files.find(file => file.id === node?.file?.id);
    if (!item || item.reference_type !== 'repository_file') throw new Error('ลบได้เฉพาะไฟล์ที่อยู่ในพื้นที่ข้อมูลของโปรไฟล์');
    const file = core.resolveStepFile(root, profile, item);
    const answer = await vscode.window.showWarningMessage(`ลบไฟล์จริง ${path.basename(file)} หรือไม่?`, { modal: true }, 'ลบไฟล์จริง');
    if (answer !== 'ลบไฟล์จริง') return;
    fs.unlinkSync(file);
    for (const workflowStep of profile.workflow.steps) workflowStep.files = workflowStep.files.filter(entry => entry.reference_type !== 'repository_file' || entry.path !== item.path);
    save(profile); refresh();
  });
  register('addDynamicFile', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const choices = Object.keys(core.DYNAMIC_CATEGORY).map(reference => ({ label: reference.replaceAll('_', ' '), description: reference, reference }));
    const choice = await vscode.window.showQuickPick(choices, { placeHolder: 'เลือกไฟล์บทที่เปลี่ยนตามบทปัจจุบัน' });
    if (!choice) return;
    step.files.push({ id: core.newId(), label: choice.label, reference_type: 'dynamic', path: null, dynamic_reference: choice.reference, file_type: 'chapter', enabled: true, order: step.files.length });
    save(profile); refresh();
  });
  register('toggleFile', async (_node, stepId, fileId) => {
    const node = typeof _node === 'object' ? _node : null;
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, stepId || node?.step?.id);
    const file = step.files.find(item => item.id === (fileId || node?.file?.id));
    if (!file) throw new Error('ไม่พบรายการไฟล์ในขั้นตอน');
    file.enabled = !file.enabled; save(profile); refresh();
  });
  register('removeFile', async node => {
    const profile = profileFor(node?.profile?.id); const step = stepFor(profile, node?.step?.id);
    const file = step.files.find(item => item.id === node?.file?.id);
    if (!file) throw new Error('ไม่พบรายการไฟล์ในขั้นตอน');
    step.files = step.files.filter(item => item.id !== file.id); save(profile); refresh();
    vscode.window.setStatusBarMessage('เอารายการออกจากขั้นตอนแล้ว (ไฟล์จริงยังอยู่)', 2500);
  });
  register('openFile', async (profileId, stepId, fileId) => {
    const profile = profileFor(profileId); const step = stepFor(profile, stepId);
    const file = step.files.find(item => item.id === fileId);
    if (!file) throw new Error('ไม่พบไฟล์');
    const target = core.resolveStepFile(root, profile, file);
    if (!fs.existsSync(target)) throw new Error(`ไม่พบไฟล์: ${target}`);
    await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target));
  });
  register('copyStep', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const paths = core.enabledStepPaths(root, profile, step);
    if (!paths.length) { vscode.window.setStatusBarMessage('ขั้นตอนนี้ไม่มีไฟล์ที่เปิดใช้งาน', 3000); return; }
    copyFileDropList(paths);
    const index = profile.workflow.steps.indexOf(step);
    const next = profile.workflow.steps[(index + 1) % profile.workflow.steps.length];
    await context.workspaceState.update('novelWorkflow.stepId', next.id);
    state.stepId = next.id; refresh();
    vscode.window.setStatusBarMessage(`คัดลอกไฟล์ ${paths.length} รายการจาก “${step.name}” แล้ว · เลื่อนไป “${next.name}”`, 5000);
  });
  register('previewStep', async () => {
    const profile = profileFor(); const step = stepFor(profile);
    const current = vscode.workspace.getConfiguration('novelWorkflow');
    const text = core.assemblePreview(root, profile, step, { separator: current.get('separator'), showFilenameHeading: current.get('showFilenameHeading') });
    if (!text) { vscode.window.setStatusBarMessage('ไม่มีเนื้อหาที่เปิดใช้งานให้แสดงตัวอย่าง', 3000); return; }
    const document = await vscode.workspace.openTextDocument({ language: 'markdown', content: text });
    await vscode.window.showTextDocument(document, { preview: false });
  });
  register('importLauncher', async () => importLauncher(root, profiles, save, refresh));
  register('addGroup', async () => {
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อกลุ่มนิยาย', ignoreFocusOut: true });
    if (!name?.trim()) return;
    const all = profiles();
    if (!all.length) throw new Error('เพิ่มนิยายก่อนสร้างกลุ่ม');
    const selected = await vscode.window.showQuickPick(all.map(profile => ({ label: profile.name, profile })), { canPickMany: true, placeHolder: 'เลือกนิยายที่จะอยู่ในกลุ่ม' });
    const file = path.join(root, 'groups.json'); const groups = core.readJson(file, []);
    groups.push({ id: core.newId(), name: name.trim(), profile_ids: (selected || []).map(item => item.profile.id), description: '', order: groups.length, default_goal_chapters: null, caught_up_profile_ids: [], completed_goal_cycles: 0, last_goal_reset_at: null });
    core.atomicWriteJson(file, groups); refresh();
  });
  register('openGroup', async id => {
    const groups = core.readJson(path.join(root, 'groups.json'), []);
    const group = groups.find(item => item.id === id);
    if (!group) throw new Error('ไม่พบกลุ่มนิยาย');
    const byId = new Map(profiles().map(profile => [profile.id, profile]));
    for (const profileId of group.profile_ids || []) {
      const profile = byId.get(profileId);
      if (!profile) continue;
      if (profile.main_folder) await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(profile.main_folder), true);
      for (const target of (profile.launch_targets || []).filter(item => item.enabled)) await openTarget(target);
    }
    vscode.window.setStatusBarMessage(`เปิดกลุ่ม ${group.name} แล้ว`, 3000);
  });
  register('renameGroup', async id => {
    const file = path.join(root, 'groups.json'); const groups = core.readJson(file, []);
    const group = groups.find(item => item.id === id);
    if (!group) throw new Error('ไม่พบกลุ่มนิยาย');
    const name = await vscode.window.showInputBox({ prompt: 'ชื่อกลุ่ม', value: group.name });
    if (name === undefined || !name.trim()) return;
    group.name = name.trim(); core.atomicWriteJson(file, groups); refresh();
  });
  register('deleteGroup', async id => {
    const file = path.join(root, 'groups.json'); const groups = core.readJson(file, []);
    const group = groups.find(item => item.id === id);
    if (!group) throw new Error('ไม่พบกลุ่มนิยาย');
    const answer = await vscode.window.showWarningMessage(`ลบกลุ่ม “${group.name}” หรือไม่? นิยายในกลุ่มจะไม่ถูกลบ`, { modal: true }, 'ลบกลุ่ม');
    if (answer !== 'ลบกลุ่ม') return;
    core.atomicWriteJson(file, groups.filter(item => item.id !== id)); refresh();
  });
  register('manageGroups', async () => {
    const groups = core.readJson(path.join(root, 'groups.json'), []);
    const choice = await vscode.window.showQuickPick(groups.map(group => ({ label: group.name, description: `${(group.profile_ids || []).length} เรื่อง`, group })), { placeHolder: 'เลือกกลุ่มเพื่อจัดการ' });
    if (!choice) return;
    const action = await vscode.window.showQuickPick(['เปิดกลุ่ม', 'เปลี่ยนชื่อ', 'แก้สมาชิก', 'ลบกลุ่ม'], { placeHolder: choice.group.name });
    if (action === 'เปิดกลุ่ม') await vscode.commands.executeCommand('novelWorkflow.openGroup', choice.group.id);
    else if (action === 'เปลี่ยนชื่อ') await vscode.commands.executeCommand('novelWorkflow.renameGroup', choice.group.id);
    else if (action === 'ลบกลุ่ม') await vscode.commands.executeCommand('novelWorkflow.deleteGroup', choice.group.id);
    else if (action === 'แก้สมาชิก') {
      const all = profiles();
      const selected = await vscode.window.showQuickPick(all.map(profile => ({ label: profile.name, picked: choice.group.profile_ids.includes(profile.id), profile })), { canPickMany: true, placeHolder: 'เลือกสมาชิกของกลุ่ม' });
      if (!selected) return;
      const name = await vscode.window.showInputBox({ prompt: 'ชื่อกลุ่ม', value: choice.group.name });
      if (name === undefined || !name.trim()) return;
      const latest = core.readJson(path.join(root, 'groups.json'), []); const group = latest.find(item => item.id === choice.group.id);
      if (!group) throw new Error('กลุ่มนี้ถูกลบไปแล้ว');
      group.name = name.trim(); group.profile_ids = selected.map(item => item.profile.id);
      core.atomicWriteJson(path.join(root, 'groups.json'), latest); refresh();
    }
  });
  register('addLaunchTarget', async () => {
    const profile = profileFor();
    const kind = await vscode.window.showQuickPick(['file', 'folder', 'application', 'website'], { placeHolder: 'ชนิดรายการที่จะเปิดพร้อมนิยาย' });
    if (!kind) return;
    let target;
    if (kind === 'website') {
      target = await vscode.window.showInputBox({ prompt: 'URL (http หรือ https)', validateInput: value => /^https?:\/\//i.test(value) ? null : 'รองรับเฉพาะ URL http/https' });
    } else {
      const selection = await vscode.window.showOpenDialog({ canSelectFiles: kind !== 'folder', canSelectFolders: kind === 'folder', canSelectMany: false, filters: kind === 'application' ? { Applications: ['exe'] } : undefined });
      target = selection?.[0]?.fsPath;
    }
    if (!target) return;
    const label = await vscode.window.showInputBox({ prompt: 'ชื่อที่แสดง', value: path.basename(target) });
    if (label === undefined) return;
    profile.launch_targets ||= [];
    profile.launch_targets.push({ id: core.newId(), label: label.trim() || target, kind, target, arguments: [], enabled: true, order: profile.launch_targets.length });
    save(profile); refresh();
  });
  register('manageLaunchTargets', async id => {
    const profile = profileFor(id); profile.launch_targets ||= [];
    if (!profile.main_folder) {
      const folder = await vscode.window.showOpenDialog({ canSelectFiles: false, canSelectFolders: true, canSelectMany: false, openLabel: 'เลือกโฟลเดอร์นิยาย' });
      if (folder?.[0]) profile.main_folder = folder[0].fsPath;
    }
    const action = await vscode.window.showQuickPick(['เพิ่มรายการ', 'เปิดโฟลเดอร์หลัก', ...profile.launch_targets.map(item => `ลบ · ${item.label}`)], { placeHolder: `ตัวเปิดของ ${profile.name}` });
    if (action === 'เพิ่มรายการ') return vscode.commands.executeCommand('novelWorkflow.addLaunchTarget');
    if (action === 'เปิดโฟลเดอร์หลัก') { save(profile); return vscode.commands.executeCommand('novelWorkflow.openProfile', profile.id); }
    if (action?.startsWith('ลบ · ')) {
      const target = profile.launch_targets.find(item => `ลบ · ${item.label}` === action);
      if (target) profile.launch_targets = profile.launch_targets.filter(item => item.id !== target.id);
    }
    save(profile); refresh();
  });

  context.subscriptions.push(vscode.workspace.onDidSaveTextDocument(document => {
    try { let changed = false; for (const profile of profiles()) if (profile.context_path && path.resolve(profile.context_path).toLowerCase() === path.resolve(document.uri.fsPath).toLowerCase() && core.syncContext(profile)) { save(profile); changed = true; } if (changed) refresh(); } catch (error) { notifyError(error); }
  }));
  context.subscriptions.push(vscode.workspace.onDidRenameFiles(event => {
    try {
      const renames = event.files.map(file => ({ old: file.oldUri.fsPath, next: file.newUri.fsPath }));
      for (const profile of profiles()) {
        let changed = false;
        const profileRoot = core.profileDirectory(root, profile.id);
        for (const item of profile.workflow.steps.flatMap(step => step.files)) {
          if (!item.path || item.reference_type === 'dynamic') continue;
          const absolute = item.reference_type === 'external_file' ? path.resolve(item.path) : path.resolve(profileRoot, item.path);
          const rename = renames.find(entry => {
            const old = path.resolve(entry.old);
            return absolute.toLowerCase() === old.toLowerCase() || absolute.toLowerCase().startsWith(`${old.toLowerCase()}${path.sep}`);
          });
          if (rename) {
            const old = path.resolve(rename.old); const next = path.resolve(rename.next);
            const relativeTail = path.relative(old, absolute);
            const newAbsolute = path.join(next, relativeTail);
            item.path = item.reference_type === 'external_file' ? newAbsolute : path.relative(profileRoot, newAbsolute).split(path.sep).join('/');
            changed = true;
          }
        }
        if (profile.context_path) {
          const rename = renames.find(entry => path.resolve(profile.context_path).toLowerCase() === path.resolve(entry.old).toLowerCase());
          if (rename) { profile.context_path = rename.next; profile.translation_checkpoint_path = rename.next; changed = true; }
        }
        if (changed) save(profile);
      }
      refresh();
    } catch (error) { notifyError(error); }
  }));
  context.subscriptions.push(vscode.workspace.onDidDeleteFiles(event => {
    try {
      const deleted = event.files.map(uri => path.resolve(uri.fsPath).toLowerCase());
      for (const profile of profiles()) {
        let changed = false; const profileRoot = core.profileDirectory(root, profile.id);
        for (const step of profile.workflow.steps) {
          const before = step.files.length;
          step.files = step.files.filter(item => {
            if (!item.path || item.reference_type === 'dynamic') return true;
            const absolute = item.reference_type === 'external_file' ? path.resolve(item.path) : path.resolve(profileRoot, item.path);
            return !deleted.includes(absolute.toLowerCase());
          });
          if (step.files.length !== before) changed = true;
        }
        if (profile.context_path && deleted.includes(path.resolve(profile.context_path).toLowerCase())) { profile.context_path = null; profile.translation_checkpoint_path = null; changed = true; }
        if (changed) save(profile);
      }
      refresh();
    } catch (error) { notifyError(error); }
  }));
  context.subscriptions.push(vscode.workspace.onDidChangeConfiguration(event => {
    if (event.affectsConfiguration('novelWorkflow.dataRoot')) vscode.window.showInformationMessage('เปลี่ยนโฟลเดอร์ข้อมูลแล้ว กรุณา Reload Window เพื่อโหลดข้อมูลจากตำแหน่งใหม่', 'Reload Window').then(choice => { if (choice === 'Reload Window') vscode.commands.executeCommand('workbench.action.reloadWindow'); });
  }));

  const timer = setInterval(() => {
    try { let changed = false; for (const profile of profiles()) if (core.syncContext(profile)) { save(profile); changed = true; } if (changed) refresh(); }
    catch (error) { notifyError(error); }
  }, 10000);
  context.subscriptions.push({ dispose: () => clearInterval(timer) });

  refresh();
  try {
    const settings = core.readJson(path.join(root, 'settings.json'), {});
    const initialId = vscode.workspace.getConfiguration('novelWorkflow').get('openLastProfile') === false ? undefined : settings.last_profile_id;
    const initial = profiles().find(profile => profile.id === state.profileId) || profiles().find(profile => profile.id === initialId);
    if (initial) setSelection(initial, state.stepId && initial.workflow.steps.some(step => step.id === state.stepId) ? state.stepId : undefined);
  } catch (error) { notifyError(error); }

  async function openTarget(target) {
    if (target.kind === 'website') {
      const uri = vscode.Uri.parse(target.target);
      if (!['http', 'https'].includes(uri.scheme) || !uri.authority) throw new Error(`URL ไม่ปลอดภัย: ${target.target}`);
      await vscode.env.openExternal(uri); return;
    }
    if (target.kind === 'application') {
      if (!fs.existsSync(target.target)) throw new Error(`ไม่พบโปรแกรม: ${target.target}`);
      const child = spawn(target.target, target.arguments || [], { shell: false, detached: true, stdio: 'ignore', windowsHide: false });
      child.unref(); return;
    }
    if (!fs.existsSync(target.target)) throw new Error(`ไม่พบไฟล์หรือโฟลเดอร์: ${target.target}`);
    if (target.kind === 'folder') await vscode.commands.executeCommand('vscode.openFolder', vscode.Uri.file(target.target), true);
    else await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(target.target));
  }
}

async function importLauncher(root, profiles, save, refresh) {
  const selection = await vscode.window.showOpenDialog({ canSelectFiles: true, canSelectFolders: false, canSelectMany: false, filters: { JSON: ['json'] }, openLabel: 'นำเข้าข้อมูล' });
  if (!selection?.[0]) return;
  const raw = JSON.parse(fs.readFileSync(selection[0].fsPath, 'utf8'));
  if (!raw || !Array.isArray(raw.novels) || !raw.novels.every(item => item && typeof item === 'object')) throw new Error('ไฟล์นี้ไม่ใช่ Novel Launcher config ที่ถูกต้อง');
  if (raw.groups !== undefined && (!Array.isArray(raw.groups) || !raw.groups.every(item => item && typeof item === 'object'))) throw new Error('ข้อมูลกลุ่มในไฟล์ไม่ถูกต้อง');
  const checkpointItems = raw.translationStats?.checkpoints;
  const checkpoints = new Map((Array.isArray(checkpointItems) ? checkpointItems : []).filter(item => item && item.novelId).map(item => [String(item.novelId), item]));
  const existing = profiles();
  const folderKey = value => String(value || '').replaceAll('\\', '/').replace(/\/+$/, '').toLowerCase();
  const nameKey = value => String(value || '').replace(/[^\p{L}\p{N}]+/gu, '').toLowerCase();
  const byFolder = new Map(existing.filter(item => item.main_folder).map(item => [folderKey(item.main_folder), item]));
  const byName = new Map(); for (const item of existing) if (!byName.has(nameKey(item.name))) byName.set(nameKey(item.name), item);
  const idMap = new Map(); let made = 0; let targetCount = 0;
  for (const old of raw.novels) {
    const name = String(old.name || 'Novel').trim() || 'Novel'; const folder = String(old.mainFolder || '').trim();
    let profile = (folder && byFolder.get(folderKey(folder))) || null;
    if (!profile) {
      const candidate = byName.get(nameKey(name));
      if (candidate && (!folder || !candidate.main_folder || folderKey(candidate.main_folder) === folderKey(folder))) profile = candidate;
    }
    if (!profile) { profile = core.createProfile(name); made += 1; }
    if (folder) profile.main_folder ||= folder;
    if (old.contextPath) profile.context_path = String(old.contextPath);
    if (['translating', 'paused', 'completed'].includes(old.status)) profile.status = old.status;
    if (old.translationGoal && typeof old.translationGoal === 'object') {
      profile.translation_goal_target = old.translationGoal.targetChapters == null ? null : Number(old.translationGoal.targetChapters);
      profile.translation_goal_baseline = old.translationGoal.baselineChapter == null ? null : Number(old.translationGoal.baselineChapter);
    }
    const checkpoint = checkpoints.get(String(old.id || ''));
    const legacyContext = checkpoint?.contextPath ? String(checkpoint.contextPath) : '';
    if (!profile.context_path && legacyContext && fs.existsSync(legacyContext)) profile.context_path = legacyContext;
    if (profile.context_path && fs.existsSync(profile.context_path)) {
      const canonicalContext = path.resolve(profile.context_path);
      const sameCheckpoint = legacyContext && fs.existsSync(legacyContext) && path.resolve(legacyContext).toLowerCase() === canonicalContext.toLowerCase();
      const savedChapter = sameCheckpoint ? Number(checkpoint.latestChapter) : NaN;
      const chapter = Number.isInteger(savedChapter) && savedChapter > 0 ? savedChapter : core.latestContextChapter(fs.readFileSync(profile.context_path, 'utf8'));
      if (chapter !== null) profile.chapter_state.current_chapter = chapter;
      profile.translation_checkpoint_path = path.resolve(profile.context_path);
    }
    const sourceCover = old.coverPath;
    if (sourceCover && fs.existsSync(sourceCover)) {
      const ext = path.extname(sourceCover).toLowerCase();
      if (['.png', '.jpg', '.jpeg', '.webp', '.bmp'].includes(ext)) {
        const target = path.join(core.profileDirectory(root, profile.id), 'covers', `cover${ext}`);
        fs.mkdirSync(path.dirname(target), { recursive: true });
        if (path.resolve(sourceCover) !== path.resolve(target)) fs.copyFileSync(sourceCover, target);
        profile.cover_image_path = path.relative(core.profileDirectory(root, profile.id), target).split(path.sep).join('/');
      }
    }
    if (old.id) idMap.set(String(old.id), profile.id);
    const additions = [];
    for (const file of Array.isArray(old.files) ? old.files : []) if (file?.path) additions.push({ label: file.name || path.basename(file.path), kind: 'file', target: String(file.path), enabled: file.enabled !== false, order: Number(file.order || 0) });
    for (const app of Array.isArray(old.applications) ? old.applications : []) if (app?.executablePath) additions.push({ label: app.name || 'Application', kind: 'application', target: String(app.executablePath), arguments: Array.isArray(app.arguments) ? app.arguments.map(String) : [], enabled: app.enabled !== false, order: Number(app.order || 0) });
    for (const site of Array.isArray(old.websites) ? old.websites : []) if (site?.url) additions.push({ label: site.name || site.url, kind: 'website', target: String(site.url), enabled: site.enabled !== false, order: Number(site.order || 0) });
    profile.launch_targets ||= [];
    const keys = new Set(profile.launch_targets.map(item => `${item.kind}\0${item.target}`));
    for (const item of additions) if (!keys.has(`${item.kind}\0${item.target}`)) { profile.launch_targets.push({ ...item, id: core.newId(), order: profile.launch_targets.length }); keys.add(`${item.kind}\0${item.target}`); targetCount += 1; }
    if (folder) byFolder.set(folderKey(folder), profile); byName.set(nameKey(profile.name), profile);
    save(profile);
  }
  const groupsFile = path.join(root, 'groups.json'); const groups = core.readJson(groupsFile, []); let newGroups = 0;
  for (const old of Array.isArray(raw.groups) ? raw.groups : []) {
    const name = String(old.name || '').trim(); if (!name) continue;
    const members = [...new Set((Array.isArray(old.novelIds) ? old.novelIds : []).map(id => idMap.get(String(id))).filter(Boolean))];
    let group = groups.find(item => item.name.toLowerCase() === name.toLowerCase());
    const caughtUp = [...new Set((Array.isArray(old.caughtUpNovelIds) ? old.caughtUpNovelIds : []).map(id => idMap.get(String(id))).filter(Boolean))];
    if (group) {
      group.profile_ids = [...new Set([...(group.profile_ids || []), ...members])];
      group.caught_up_profile_ids = [...new Set([...(group.caught_up_profile_ids || []), ...caughtUp])];
      if (group.default_goal_chapters == null) group.default_goal_chapters = old.defaultGoalChapters ?? null;
      group.completed_goal_cycles = Math.max(Number(group.completed_goal_cycles || 0), Number(old.completedGoalCycles || 0));
      group.last_goal_reset_at ||= old.lastGoalResetAt || null;
      group.description ||= String(old.description || '');
    } else { group = { id: core.newId(), name, profile_ids: members, description: String(old.description || ''), order: groups.length, default_goal_chapters: old.defaultGoalChapters ?? null, caught_up_profile_ids: caughtUp, completed_goal_cycles: Number(old.completedGoalCycles || 0), last_goal_reset_at: old.lastGoalResetAt || null }; groups.push(group); newGroups += 1; }
  }
  core.atomicWriteJson(groupsFile, groups); refresh();
  vscode.window.showInformationMessage(`นำเข้าข้อมูลแล้ว · โปรไฟล์ใหม่ ${made} · กลุ่มใหม่ ${newGroups} · รายการเปิด ${targetCount} · ไฟล์ต้นทางไม่ถูกแก้`);
}

function deactivate() {}
module.exports = { activate, deactivate, NovelTreeProvider };
