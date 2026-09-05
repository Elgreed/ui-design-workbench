"""Regressions for transient Windows locks and partial DevTools port files."""

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required")
class BrowserStartupTests(unittest.TestCase):
    def run_node(self, body):
        script = """
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { waitForDevToolsPort } = require('./scripts/smoke_preview.js');
(async () => {
""" + body + "\n})().catch(error => { console.error(error); process.exitCode = 1; });"
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_retries_transient_read_locks_and_partial_contents(self):
        self.run_node("""
const values = ['ENOENT', 'EBUSY', 'EACCES', 'EPERM', '', '92', '65536\\n/devtools/browser/test', '9222\\n/devtools/browser/test'];
fs.readFileSync = () => {
  const value = values.shift();
  if (['ENOENT', 'EBUSY', 'EACCES', 'EPERM'].includes(value)) throw Object.assign(new Error(value), {code: value});
  return value;
};
assert.equal(await waitForDevToolsPort('DevToolsActivePort', 3000), '9222');
assert.equal(values.length, 0);
""")

    def test_permanent_read_errors_are_not_hidden(self):
        self.run_node("""
const error = Object.assign(new Error('disk error'), {code: 'EIO'});
fs.readFileSync = () => { throw error; };
await assert.rejects(waitForDevToolsPort('DevToolsActivePort', 1000), candidate => candidate === error);
""")

    def test_busy_file_has_a_bounded_timeout(self):
        self.run_node("""
fs.readFileSync = () => { throw Object.assign(new Error('locked'), {code: 'EBUSY'}); };
await assert.rejects(waitForDevToolsPort('DevToolsActivePort', 10), /Timed out waiting for DevToolsActivePort/);
""")


if __name__ == "__main__":
    unittest.main()
