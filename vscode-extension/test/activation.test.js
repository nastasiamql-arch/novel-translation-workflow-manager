'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const Module = require('node:module');

class FakeEventEmitter {
  constructor() { this.event = () => ({ dispose() {} }); }
  fire() {}
}
class FakeTreeItem {
  constructor(label, collapsibleState) { this.label = label; this.collapsibleState = collapsibleState; }
}
class FakeThemeIcon { constructor(id) { this.id = id; } }

test('extension activates once and registers each contributed command', t => {
  const dataRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'novelworkflow-activation-'));
  t.after(() => fs.rmSync(dataRoot, { recursive: true, force: true }));
  const commands = new Map();
  const subscriptions = [];
  t.after(() => { for (const item of subscriptions) item?.dispose?.(); });
  const config = { dataRoot, openLastProfile: false, separator: '--- {FILE_NAME} ---', showFilenameHeading: true };
  const disposable = { dispose() {} };
  const vscode = {
    EventEmitter: FakeEventEmitter,
    TreeItem: FakeTreeItem,
    ThemeIcon: FakeThemeIcon,
    TreeItemCollapsibleState: { None: 0, Expanded: 1 },
    StatusBarAlignment: { Left: 1, Right: 2 },
    Uri: { file: fsPath => ({ fsPath }) },
    window: {
      createTreeView: () => ({ dispose() {} }),
      createStatusBarItem: () => ({ show() {}, hide() {}, dispose() {} }),
      showErrorMessage: message => { throw new Error(message); },
      showInformationMessage: async () => undefined,
      setStatusBarMessage: () => disposable
    },
    workspace: {
      getConfiguration: () => ({ get: (name, fallback) => Object.hasOwn(config, name) ? config[name] : fallback }),
      onDidSaveTextDocument: () => disposable,
      onDidRenameFiles: () => disposable,
      onDidDeleteFiles: () => disposable,
      onDidChangeConfiguration: () => disposable
    },
    commands: {
      registerCommand: (name, handler) => {
        assert.equal(commands.has(name), false, `duplicate registration: ${name}`);
        commands.set(name, handler); return disposable;
      },
      executeCommand: async () => undefined
    }
  };
  const oldLoad = Module._load;
  Module._load = function(request, parent, isMain) {
    if (request === 'vscode') return vscode;
    return oldLoad.call(this, request, parent, isMain);
  };
  const extensionPath = require.resolve('../src/extension');
  delete require.cache[extensionPath];
  try {
    const extension = require(extensionPath);
    extension.activate({ workspaceState: { get: () => undefined, update: async () => undefined }, subscriptions });
  } finally {
    Module._load = oldLoad;
  }
  assert.ok(commands.has('novelWorkflow.copyStep'));
  assert.ok(commands.has('novelWorkflow.createProfile'));
  assert.ok(commands.has('novelWorkflow.importLauncher'));
  assert.ok(fs.existsSync(path.join(dataRoot, 'profiles')));
  for (const item of subscriptions) item?.dispose?.();
});
