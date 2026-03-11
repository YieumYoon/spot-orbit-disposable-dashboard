from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import load_config


class ConfigTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_loads_values_from_dotenv_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "ORBIT_USE_FIXTURES=true",
                        "TIMEZONE=America/Indiana/Indianapolis",
                        "DASHBOARD_PORT=9090",
                    ]
                ),
                encoding="utf-8",
            )
            os.environ["DASHBOARD_ENV_FILE"] = str(env_path)

            config = load_config()

            self.assertTrue(config.fixture_mode)
            self.assertEqual(config.timezone, "America/Indiana/Indianapolis")
            self.assertEqual(config.dashboard_port, 9090)

    def test_real_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("TIMEZONE=UTC\n", encoding="utf-8")
            os.environ["DASHBOARD_ENV_FILE"] = str(env_path)
            os.environ["TIMEZONE"] = "America/Indiana/Indianapolis"

            config = load_config()

            self.assertEqual(config.timezone, "America/Indiana/Indianapolis")


if __name__ == "__main__":
    unittest.main()
