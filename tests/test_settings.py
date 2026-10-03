import tempfile
import unittest
from pathlib import Path

from settings import DEFAULT_SETTINGS, SettingsManager


class SettingsManagerTests(unittest.TestCase):
    def test_window_position_is_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            manager = SettingsManager(
                path=settings_path
            )
            settings = DEFAULT_SETTINGS.copy()
            settings["window_x"] = "321"
            settings["window_y"] = "222"

            manager.save(settings)
            loaded_settings = manager.load()

        self.assertEqual(
            loaded_settings["window_x"],
            "321"
        )
        self.assertEqual(
            loaded_settings["window_y"],
            "222"
        )


if __name__ == "__main__":
    unittest.main()
