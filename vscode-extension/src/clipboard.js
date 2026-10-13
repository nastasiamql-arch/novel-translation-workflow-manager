'use strict';

const { spawnSync } = require('node:child_process');

function buildPowerShellCommand(paths) {
  const payload = Buffer.from(JSON.stringify(paths), 'utf8').toString('base64');
  const script = [
    "$ErrorActionPreference = 'Stop'",
    'Add-Type -AssemblyName System.Windows.Forms',
    `$json = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${payload}'))`,
    '$paths = @(ConvertFrom-Json -InputObject $json)',
    '$files = New-Object System.Collections.Specialized.StringCollection',
    'foreach ($item in $paths) { [void]$files.Add([string]$item) }',
    '[System.Windows.Forms.Clipboard]::SetFileDropList($files)'
  ].join('\n');
  return Buffer.from(script, 'utf16le').toString('base64');
}

function copyFileDropList(paths, platform = process.platform, spawn = spawnSync) {
  if (platform !== 'win32') throw new Error('การคัดลอกรายการไฟล์ไปยัง clipboard รองรับ Windows เท่านั้น');
  if (!Array.isArray(paths) || paths.length === 0) throw new Error('ไม่มีไฟล์ให้คัดลอก');
  const args = ['-NoLogo', '-NoProfile', '-NonInteractive', '-STA', '-EncodedCommand', buildPowerShellCommand(paths)];
  const result = spawn('powershell.exe', args, { encoding: 'utf8', windowsHide: true, timeout: 15000, maxBuffer: 1024 * 1024 });
  if (result.error) throw new Error(`เรียก Windows Clipboard ไม่สำเร็จ: ${result.error.message}`);
  if (result.status !== 0) throw new Error((result.stderr || result.stdout || 'Windows ปฏิเสธการคัดลอกไฟล์').trim());
  return paths.length;
}

module.exports = { buildPowerShellCommand, copyFileDropList };
