"""runtime_space 工作目录创建。"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.flowgame.runtime_space import (
    BLACKBOARD_RUN_ID,
    BLACKBOARD_RUNTIME_SPACE,
    create_team_runtime_dir,
    get_runtime_space_root,
)


class RuntimeSpaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="fg_runtime_")
        self._old = os.environ.get("FLOWGAME_RUNTIME_SPACE_DIR")
        os.environ["FLOWGAME_RUNTIME_SPACE_DIR"] = self._tmpdir

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("FLOWGAME_RUNTIME_SPACE_DIR", None)
        else:
            os.environ["FLOWGAME_RUNTIME_SPACE_DIR"] = self._old
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_team_runtime_dir(self):
        root = get_runtime_space_root()
        self.assertEqual(root, Path(self._tmpdir).resolve())
        run_id, path = create_team_runtime_dir("qbhq-1")
        self.assertTrue(path.is_dir())
        self.assertTrue(path.is_relative_to(root) or str(path).startswith(str(root)))
        self.assertTrue((path / "README.txt").is_file())
        self.assertEqual(len(run_id), 12)
        self.assertIn(BLACKBOARD_RUNTIME_SPACE, ("runtimeSpace",))
        self.assertIn(BLACKBOARD_RUN_ID, ("runId",))


if __name__ == "__main__":
    unittest.main()
