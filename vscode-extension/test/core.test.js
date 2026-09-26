'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const core = require('../src/core');
const { buildPowerShellCommand, copyFileDropList } = require('../src/clipboard');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'novelworkflow-extension-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

test('default data folder matches the existing Windows application', () => {
  assert.equal(core.defaultDataRoot({ LOCALAPPDATA: 'C:\\Users\\sample\\AppData\\Local' }), path.join('C:\\Users\\sample\\AppData\\Local', 'NovelTranslationWorkflowManager'));
});

test('profiles stay independent and JSON save keeps a recoverable backup', t => {
  const root = fixture(t);
  const first = core.createProfile('นิยาย A');
  const second = core.createProfile('นิยาย B');
  core.saveProfile(root, first);
  core.saveProfile(root, second);
  first.name = 'แก้เฉพาะ A';
  core.saveProfile(root, first);
  assert.equal(core.listProfiles(root).length, 2);
  assert.equal(core.listProfiles(root).find(p => p.id === second.id).name, 'นิยาย B');
  assert.equal(fs.existsSync(path.join(root, 'profiles', first.id, 'profile.json.bak')), true);
});

test('recoverable trailing-comma JSON is read without changing the source file', t => {
  const root = fixture(t);
  const file = path.join(root, 'settings.json');
  const raw = '{\n  "appearance": "Dark",\n}\n';
  fs.writeFileSync(file, raw);
  assert.deepEqual(core.readJson(file), { appearance: 'Dark' });
  assert.equal(fs.readFileSync(file, 'utf8'), raw);
});

test('ambiguous malformed JSON is reported and remains unchanged', t => {
  const root = fixture(t);
  const file = path.join(root, 'settings.json');
  const raw = '{"appearance" "Dark"}';
  fs.writeFileSync(file, raw);
  assert.throws(() => core.readJson(file), /อ่าน JSON ไม่ได้/);
  assert.equal(fs.readFileSync(file, 'utf8'), raw);
});

test('dynamic reference resolves the current chapter by number, not a fixed filename', t => {
  const root = fixture(t);
  const profile = core.createProfile('เรื่อง');
  core.saveProfile(root, profile);
  const dir = path.join(core.profileDirectory(root, profile.id), 'source');
  fs.writeFileSync(path.join(dir, 'ต้นฉบับ ตอนที่ 25.md'), 'เนื้อหา 25');
  fs.writeFileSync(path.join(dir, 'ต้นฉบับ ตอนที่ 26 ฉบับแก้.txt'), 'เนื้อหา 26');
  profile.chapter_state.current_chapter = 25;
  assert.match(core.resolveDynamicPath(root, profile, 'CURRENT_SOURCE_CHAPTER'), /ตอนที่ 25\.md$/);
  profile.chapter_state.current_chapter = 26;
  assert.match(core.resolveDynamicPath(root, profile, 'CURRENT_SOURCE_CHAPTER'), /ตอนที่ 26 ฉบับแก้\.txt$/);
});

test('preview follows order, excludes disabled files and reads edits from disk', t => {
  const root = fixture(t);
  const profile = core.createProfile('เรื่อง');
  core.saveProfile(root, profile);
  const dir = core.profileDirectory(root, profile.id);
  fs.writeFileSync(path.join(dir, 'prompts', 'prompt.txt'), 'prompt เก่า');
  fs.writeFileSync(path.join(dir, 'glossary', 'glossary.txt'), 'ศัพท์');
  fs.writeFileSync(path.join(dir, 'prompts', 'prompt.txt'), 'prompt ล่าสุด');
  const step = { files: [
    { enabled: true, order: 2, path: 'glossary/glossary.txt', label: 'คำศัพท์' },
    { enabled: true, order: 1, path: 'prompts/prompt.txt', label: 'คำสั่ง' },
    { enabled: false, order: 0, path: 'missing.txt', label: 'ปิดอยู่' }
  ] };
  const preview = core.assemblePreview(root, profile, step);
  assert.ok(preview.indexOf('prompt ล่าสุด') < preview.indexOf('ศัพท์'));
  assert.match(preview, /คำสั่ง/);
  assert.doesNotMatch(preview, /ปิดอยู่/);
});

test('unsafe profile file paths and ambiguous dynamic references fail clearly', t => {
  const root = fixture(t);
  const profile = core.createProfile('เรื่อง');
  core.saveProfile(root, profile);
  assert.throws(() => core.containedPath(core.profileDirectory(root, profile.id), '..\\outside.txt'), /ออกจากโฟลเดอร์/);
  const dir = path.join(core.profileDirectory(root, profile.id), 'source');
  fs.writeFileSync(path.join(dir, 'source_7.txt'), 'a');
  fs.writeFileSync(path.join(dir, 'rev_7.md'), 'b');
  profile.chapter_state.current_chapter = 7;
  assert.throws(() => core.resolveDynamicPath(root, profile, 'CURRENT_SOURCE_CHAPTER'), /หลายไฟล์/);
});

test('Context changes update current chapter and count new chapters once', t => {
  const root = fixture(t);
  const profile = core.createProfile('เรื่อง');
  const context = path.join(root, 'Context.md');
  fs.writeFileSync(context, 'บทที่ 130\nเนื้อหา');
  profile.context_path = context;
  profile.translation_checkpoint_path = context;
  profile.chapter_state.current_chapter = 125;
  assert.equal(core.syncContext(profile), true);
  assert.equal(profile.chapter_state.current_chapter, 130);
  assert.equal(core.todayChapterCount(profile), 5);
  assert.equal(core.syncContext(profile), false);
  assert.equal(core.todayChapterCount(profile), 5);
});

test('first Context scan establishes a baseline instead of counting old history', t => {
  const root = fixture(t);
  const profile = core.createProfile('เรื่อง');
  const context = path.join(root, 'Context.md');
  fs.writeFileSync(context, 'บทที่ 130\nเนื้อหา');
  profile.context_path = context;
  assert.equal(core.syncContext(profile), true);
  assert.equal(profile.chapter_state.current_chapter, 130);
  assert.equal(core.todayChapterCount(profile), 0);
});

test('file clipboard payload safely transports Windows paths without copying text', () => {
  const command = buildPowerShellCommand(["C:\\novels\\ชื่อ'source.txt", 'D:\\chapters\\26.md']);
  assert.ok(command.length > 100);
  let called = false;
  const count = copyFileDropList(['C:\\novels\\chapter.txt'], 'win32', (_exe, args, options) => {
    called = true;
    assert.ok(args.includes('-STA'));
    assert.equal(options.windowsHide, true);
    return { status: 0, stdout: '', stderr: '' };
  });
  assert.equal(called, true);
  assert.equal(count, 1);
  assert.throws(() => copyFileDropList(['a'], 'linux'), /Windows เท่านั้น/);
});
