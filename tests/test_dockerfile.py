"""Guard the lightweight runtime image and its deployment entrypoint."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DockerfileTests(unittest.TestCase):
    def test_build_tools_stay_in_builder_and_entrypoint_stays_compatible(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        builder, runtime = dockerfile.split('FROM python:3.11-slim-bookworm AS runtime')
        self.assertIn('FROM python:3.11-slim-bookworm AS builder', builder)
        self.assertIn('install -y --no-install-recommends gcc', builder)
        self.assertIn('pip install --no-cache-dir -r requirements.txt', builder)
        self.assertIn('pip check', builder)
        self.assertNotIn('apt-get', runtime)
        self.assertIn('COPY --from=builder /opt/venv /opt/venv', runtime)
        self.assertIn('COPY . .', runtime)
        self.assertIn('CMD ["python", "bot.py"]', runtime)

    def test_sensitive_files_and_local_environments_excluded(self):
        ignore = set((ROOT / '.dockerignore').read_text().splitlines())
        self.assertTrue({'.git', '.venv', 'venv', '.env', '.env.*', '*.session'} <= ignore)
