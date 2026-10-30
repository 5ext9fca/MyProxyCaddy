import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / '.env'
        self.output = self.root / 'output'
        self.env.write_text('PUBLIC_HOST="8.8.8.8" # 测试占位，不执行部署\n')

    def run_script(self, *args, overrides=None):
        env = {key: value for key, value in os.environ.items()
               if key not in ('PUBLIC_HOST', 'CADDY_NETWORK', 'CADDY_DATA_VOLUME', 'CADDY_CONFIG_VOLUME')}
        env.update(overrides or {})
        return subprocess.run(
            [sys.executable, str(ROOT / 'scripts/configure.py'), '--env-file', str(self.env),
             '--output-dir', str(self.output), *args],
            env=env, capture_output=True, text=True)

    def test_render_idempotence_and_backup(self):
        self.assertEqual(self.run_script().returncode, 0)
        target = self.output / 'conf/Caddyfile'
        self.assertIn('default_sni 8.8.8.8', target.read_text())
        self.assertIn('https://8.8.8.8', (self.output / 'generated/mycollab.env').read_text())
        before = target.stat().st_mtime_ns
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(target.stat().st_mtime_ns, before)
        target.write_text('custom config')
        self.assertEqual(self.run_script().returncode, 0)
        backup, = target.parent.glob('Caddyfile.bak.*')
        self.assertEqual(backup.read_text(), 'custom config')

    def test_environment_precedence_and_dry_run(self):
        self.assertEqual(self.run_script('--dry-run').returncode, 0)
        self.assertFalse(self.output.exists())
        result = self.run_script(overrides={'PUBLIC_HOST': '1.1.1.1', 'CADDY_NETWORK': 'custom-net'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('default_sni 1.1.1.1', (self.output / 'conf/Caddyfile').read_text())
        self.assertIn('CADDY_NETWORK=custom-net', (self.output / 'generated/clash.env').read_text())

    def test_reject_invalid_before_writing(self):
        for host in ('', '127.0.0.1', '192.168.1.2', '100.64.0.1', '203.0.113.10',
                     '224.0.0.1', 'https://8.8.8.8', '8.8.8.8:443', '::1', '$(touch /tmp/nope)'):
            with self.subTest(host=host):
                self.assertNotEqual(self.run_script(overrides={'PUBLIC_HOST': host}).returncode, 0)
                self.assertFalse(self.output.exists())
        self.assertNotEqual(self.run_script(overrides={'CADDY_NETWORK': '${UNSET}'}).returncode, 0)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
