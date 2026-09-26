'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');

test('every contributed command has a registered action and every menu command exists', () => {
  const contributed = new Set(manifest.contributes.commands.map(item => item.command));
  const actions = [];
  for (const match of source.matchAll(/register\('([^']+)'/g)) actions.push(`novelWorkflow.${match[1]}`);
  for (const match of source.matchAll(/registerCommand\('([^']+)'/g)) actions.push(match[1]);
  const registered = new Set(actions);
  assert.equal(registered.size, actions.length, 'A command is registered more than once');
  for (const command of contributed) assert.ok(registered.has(command), `No action registered for ${command}`);
  for (const menu of Object.values(manifest.contributes.menus).flat()) assert.ok(contributed.has(menu.command), `Menu references undeclared command ${menu.command}`);
  for (const binding of manifest.contributes.keybindings) assert.ok(contributed.has(binding.command), `Keybinding references undeclared command ${binding.command}`);
});

test('extension uses the existing profile storage location and declares the desktop file clipboard action', () => {
  assert.equal(manifest.engines.vscode, '^1.90.0');
  assert.equal(manifest.main, './src/extension.js');
  assert.match(source, /copyFileDropList\(paths\)/);
  assert.match(source, /novelWorkflow\.dataRoot/);
});
