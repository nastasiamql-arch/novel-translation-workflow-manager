'use strict';

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

const PROFILE_ID = /^[a-f0-9]{32}$/i;
const EXTENSIONS = new Set(['.txt', '.md', '.json']);
const DYNAMIC_CATEGORY = Object.freeze({
  CURRENT_SOURCE_CHAPTER: 'source',
  CURRENT_TRANSLATED_CHAPTER: 'translated',
  CURRENT_REVIEWED_CHAPTER: 'reviewed'
});
const DEFAULT_SEPARATOR = '==============================\n{FILE_NAME}\n==============================';
const DEFAULT_STEP_NAMES = ['หาศัพท์', 'แปล', 'ตรวจคำแปล'];
const CATEGORIES = ['prompts', 'glossary', 'characters', 'style', 'source', 'translated', 'reviewed', 'notes', 'reference', 'custom'];

function defaultDataRoot(env = process.env, home = os.homedir()) {
  const local = env.LOCALAPPDATA || path.join(home, 'AppData', 'Local');
  return path.join(local, 'NovelTranslationWorkflowManager');
}

function profileDirectory(root, id) {
  if (!PROFILE_ID.test(String(id || ''))) throw new Error('รหัสโปรไฟล์ไม่ถูกต้อง');
  return path.join(root, 'profiles', id);
}

function readJson(file, fallback) {
  if (!fs.existsSync(file)) return fallback;
  const raw = fs.readFileSync(file, 'utf8');
  try {
    return JSON.parse(raw);
  } catch (firstError) {
    const repaired = raw.replace(/,\s*([}\]])/g, '$1');
    if (repaired === raw) throw new Error(`อ่าน JSON ไม่ได้: ${file} (${firstError.message})`);
    try {
      return JSON.parse(repaired);
    } catch (secondError) {
      throw new Error(`กู้ JSON อย่างปลอดภัยไม่ได้: ${file} (${secondError.message})`);
    }
  }
}

function atomicWriteJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${crypto.randomUUID()}.tmp`);
  try {
    fs.writeFileSync(temp, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    if (fs.existsSync(file)) fs.copyFileSync(file, `${file}.bak`);
    fs.renameSync(temp, file);
  } finally {
    try { fs.unlinkSync(temp); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}

function validateProfile(value, directoryId) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('ข้อมูลโปรไฟล์ต้องเป็น JSON object');
  if (!PROFILE_ID.test(String(value.id || '')) || value.id !== directoryId) throw new Error('รหัสโปรไฟล์ไม่ตรงกับชื่อโฟลเดอร์');
  if (typeof value.name !== 'string') throw new Error('ข้อมูลโปรไฟล์ไม่มีชื่อเรื่องที่ถูกต้อง');
  if (value.workflow == null) value.workflow = { steps: [] };
  if (typeof value.workflow !== 'object' || Array.isArray(value.workflow)) throw new Error(`โปรไฟล์ ${value.name} มี workflow ที่ไม่ถูกต้อง`);
  if (value.workflow.steps == null) value.workflow.steps = [];
  if (!Array.isArray(value.workflow.steps)) throw new Error(`โปรไฟล์ ${value.name} ไม่มี workflow.steps ที่ถูกต้อง`);
  value.workflow.steps.forEach((step, index) => {
    if (!step || typeof step !== 'object' || Array.isArray(step)) throw new Error(`ขั้นตอนลำดับ ${index + 1} ใน ${value.name} ไม่ถูกต้อง`);
    if (!step.id) step.id = newId();
    if (typeof step.name !== 'string') throw new Error(`ชื่อขั้นตอนลำดับ ${index + 1} ใน ${value.name} ไม่ถูกต้อง`);
    if (step.files == null) step.files = [];
    if (!Array.isArray(step.files)) throw new Error(`รายการไฟล์ในขั้นตอน ${step.name} ไม่ถูกต้อง`);
    step.files.forEach((file, fileIndex) => {
      if (!file || typeof file !== 'object' || Array.isArray(file)) throw new Error(`รายการไฟล์ลำดับ ${fileIndex + 1} ในขั้นตอน ${step.name} ไม่ถูกต้อง`);
      if (!file.id) file.id = newId();
      if (file.enabled == null) file.enabled = true;
      if (typeof file.enabled !== 'boolean') throw new Error(`สถานะไฟล์ ${file.label || fileIndex + 1} ไม่ถูกต้อง`);
      if (file.order == null) file.order = fileIndex;
      if (!Number.isFinite(Number(file.order))) throw new Error(`ลำดับไฟล์ ${file.label || fileIndex + 1} ไม่ถูกต้อง`);
      if (!file.reference_type) file.reference_type = 'repository_file';
    });
  });
  if (value.chapter_state == null) value.chapter_state = { current_chapter: 1, statuses: {} };
  if (typeof value.chapter_state !== 'object' || Array.isArray(value.chapter_state)) throw new Error(`chapter_state ของ ${value.name} ไม่ถูกต้อง`);
  if (value.chapter_state.current_chapter == null) value.chapter_state.current_chapter = 1;
  if (!Number.isInteger(Number(value.chapter_state.current_chapter)) || Number(value.chapter_state.current_chapter) < 1) throw new Error(`บทปัจจุบันของ ${value.name} ไม่ถูกต้อง`);
  value.chapter_state.current_chapter = Number(value.chapter_state.current_chapter);
  if (value.launch_targets == null) value.launch_targets = [];
  if (!Array.isArray(value.launch_targets)) throw new Error(`รายการ Launcher ของ ${value.name} ไม่ถูกต้อง`);
  return value;
}

function listProfiles(root) {
  const dir = path.join(root, 'profiles');
  if (!fs.existsSync(dir)) return [];
  const profiles = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || !PROFILE_ID.test(entry.name)) continue;
    const file = path.join(dir, entry.name, 'profile.json');
    if (!fs.existsSync(file)) continue;
    profiles.push(validateProfile(readJson(file), entry.name));
  }
  return profiles.sort((a, b) => a.name.localeCompare(b.name, 'th'));
}

function saveProfile(root, profile) {
  validateProfile(profile, profile.id);
  const folder = profileDirectory(root, profile.id);
  for (const category of CATEGORIES) fs.mkdirSync(path.join(folder, category), { recursive: true });
  atomicWriteJson(path.join(folder, 'profile.json'), profile);
}

function containedPath(root, relativePath) {
  if (!relativePath || path.isAbsolute(relativePath)) throw new Error('path ในโปรไฟล์ต้องเป็น relative path');
  const base = path.resolve(root);
  const resolved = path.resolve(base, relativePath);
  if (resolved !== base && !resolved.startsWith(`${base}${path.sep}`)) throw new Error('path ออกจากโฟลเดอร์โปรไฟล์');
  const realBase = fs.realpathSync(base);
  let ancestor = resolved;
  while (!fs.existsSync(ancestor) && ancestor !== path.dirname(ancestor)) ancestor = path.dirname(ancestor);
  const realAncestor = fs.realpathSync(ancestor);
  const realTarget = path.resolve(realAncestor, path.relative(ancestor, resolved));
  const actualRelative = path.relative(realBase, realTarget);
  if (actualRelative === '..' || actualRelative.startsWith(`..${path.sep}`) || path.isAbsolute(actualRelative)) throw new Error('path ออกจากโฟลเดอร์โปรไฟล์ผ่าน symbolic link');
  return resolved;
}

function resolveDynamicPath(root, profile, reference) {
  const category = DYNAMIC_CATEGORY[reference];
  if (!category) throw new Error(`ไม่รู้จัก dynamic reference: ${reference}`);
  const chapter = Number(profile.chapter_state?.current_chapter || 1);
  const dir = path.join(profileDirectory(root, profile.id), category);
  if (!fs.existsSync(dir)) throw new Error(`ไม่มีโฟลเดอร์ ${category} สำหรับบท ${chapter}`);
  const matches = fs.readdirSync(dir, { withFileTypes: true })
    .filter(entry => entry.isFile() && EXTENSIONS.has(path.extname(entry.name).toLowerCase()))
    .map(entry => path.join(dir, entry.name))
    .filter(file => new RegExp(`(?<!\\d)${chapter}(?!\\d)`).test(path.basename(file, path.extname(file))));
  const exact = matches.filter(file => path.basename(file, path.extname(file)).toLowerCase() === `chapter_${chapter}`);
  const selected = exact.length ? exact : matches;
  if (!selected.length) throw new Error(`ไม่พบไฟล์ ${category} ที่มีเลขบท ${chapter}`);
  if (selected.length > 1) throw new Error(`พบไฟล์ ${category} หลายไฟล์สำหรับบท ${chapter}: ${selected.map(file => path.basename(file)).join(', ')}`);
  return selected[0];
}

function resolveStepFile(root, profile, item) {
  if (item.reference_type === 'dynamic') return resolveDynamicPath(root, profile, item.dynamic_reference);
  if (item.reference_type === 'external_file') {
    if (!item.path) throw new Error(`ไม่มี path ของไฟล์ ${item.label || ''}`);
    return path.resolve(item.path);
  }
  if (!item.path) throw new Error(`ไม่มี path ของไฟล์ ${item.label || ''}`);
  return containedPath(profileDirectory(root, profile.id), item.path);
}

function enabledStepPaths(root, profile, step) {
  const paths = [];
  for (const item of [...step.files].sort((a, b) => Number(a.order || 0) - Number(b.order || 0))) {
    if (!item.enabled) continue;
    const file = resolveStepFile(root, profile, item);
    if (!fs.statSync(file).isFile()) throw new Error(`ไม่ใช่ไฟล์: ${file}`);
    if (!paths.includes(file)) paths.push(file);
  }
  return paths;
}

function assemblePreview(root, profile, step, options = {}) {
  const separator = options.separator ?? DEFAULT_SEPARATOR;
  const showHeading = options.showFilenameHeading ?? true;
  const blocks = [];
  for (const item of [...step.files].sort((a, b) => Number(a.order || 0) - Number(b.order || 0))) {
    if (!item.enabled) continue;
    const file = resolveStepFile(root, profile, item);
    if (!fs.statSync(file).isFile()) throw new Error(`ไม่ใช่ไฟล์: ${file}`);
    const content = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '').trim();
    if (!content) continue;
    blocks.push(showHeading ? `${separator.replaceAll('{FILE_NAME}', item.label || path.basename(file))}\n${content}` : content);
  }
  return blocks.join('\n\n');
}

function newId() { return crypto.randomUUID().replaceAll('-', ''); }
function defaultWorkflow() { return { steps: DEFAULT_STEP_NAMES.map(name => ({ id: newId(), name, files: [] })) }; }
function createProfile(name, workflow = defaultWorkflow()) {
  return { id: newId(), name: String(name || '').trim() || 'นิยายใหม่', workflow, chapter_state: { current_chapter: 1, statuses: {} }, main_folder: '', launch_targets: [], context_path: null, status: 'translating', translation_goal_target: null, translation_goal_baseline: null, translation_checkpoint_path: null, translation_daily_activity: {}, cover_image_path: null };
}

function loadTemplates(root) {
  const file = path.join(root, 'templates.json');
  if (!fs.existsSync(file)) {
    const templates = [{ name: 'Novel Translation Basic', workflow: defaultWorkflow() }];
    atomicWriteJson(file, templates);
    return templates;
  }
  const templates = readJson(file, []);
  if (!Array.isArray(templates) || !templates.every(item => item && typeof item.name === 'string' && item.workflow && Array.isArray(item.workflow.steps))) {
    throw new Error('ไฟล์ templates.json มีโครงสร้างไม่ถูกต้อง');
  }
  return templates;
}

function goalProgress(profile) {
  const target = Number(profile.translation_goal_target);
  const baseline = Number(profile.translation_goal_baseline);
  if (!Number.isFinite(target) || target <= 0 || !Number.isFinite(baseline)) return null;
  const completed = Math.max(0, Number(profile.chapter_state?.current_chapter || 1) - baseline);
  return { completed, target, percentage: Math.min(100, Math.round(completed * 100 / target)) };
}

function latestContextChapter(text) {
  const matches = [...String(text).matchAll(/^\s*บทที่\s*(\d+)\b/gim)];
  return matches.length ? Number(matches[matches.length - 1][1]) : null;
}

function localDay(timestamp) {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function syncContext(profile) {
  if (!profile.context_path || !fs.existsSync(profile.context_path)) return false;
  const file = path.resolve(profile.context_path);
  if (!fs.statSync(file).isFile()) return false;
  const latest = latestContextChapter(fs.readFileSync(file, 'utf8'));
  if (latest === null) return false;
  const canonical = process.platform === 'win32' ? file.toLowerCase() : file;
  const old = profile.translation_checkpoint_path;
  const sameFile = old == null || (process.platform === 'win32' ? path.resolve(old).toLowerCase() : path.resolve(old)) === canonical;
  const previous = Number(profile.chapter_state?.current_chapter || 1);
  if ((old && !sameFile) || latest < previous) {
    profile.chapter_state.current_chapter = latest;
    profile.translation_checkpoint_path = canonical;
    return true;
  }
  let changed = false;
  const canCount = Boolean(old) || previous > 1;
  if (latest > previous && canCount) {
    const activity = profile.translation_daily_activity || (profile.translation_daily_activity = {});
    const day = localDay(fs.statSync(file).mtimeMs);
    const seen = new Set(activity[day] || []);
    for (let n = previous + 1; n <= latest; n += 1) seen.add(n);
    activity[day] = [...seen].sort((a, b) => a - b);
    changed = true;
  }
  if (latest !== previous) { profile.chapter_state.current_chapter = latest; changed = true; }
  if (old !== canonical) { profile.translation_checkpoint_path = canonical; changed = true; }
  return changed;
}

function todayChapterCount(profile, now = Date.now()) {
  return (profile.translation_daily_activity?.[localDay(now)] || []).length;
}

function weekChapterCount(profile, now = Date.now()) {
  const date = new Date(now);
  const day = (date.getDay() + 6) % 7;
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - day);
  const start = localDay(date.getTime());
  const end = localDay(now);
  return Object.entries(profile.translation_daily_activity || {})
    .filter(([dateKey]) => dateKey >= start && dateKey <= end)
    .reduce((total, [, chapters]) => total + (Array.isArray(chapters) ? chapters.length : 0), 0);
}

module.exports = {
  PROFILE_ID, EXTENSIONS, DYNAMIC_CATEGORY, DEFAULT_SEPARATOR, DEFAULT_STEP_NAMES, CATEGORIES,
  defaultDataRoot, profileDirectory, readJson, atomicWriteJson, validateProfile, listProfiles, saveProfile,
  containedPath, resolveDynamicPath, resolveStepFile, enabledStepPaths, assemblePreview, newId,
  defaultWorkflow, createProfile, latestContextChapter, localDay, syncContext, todayChapterCount,
  loadTemplates, goalProgress, weekChapterCount
};
