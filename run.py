#!/usr/bin/env python3
"""启动 FlowGame 独立后端。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.flowgame.settings import load_flowgame_dotenv

load_flowgame_dotenv()

from src.flowgame.app import start_server

if __name__ == "__main__":
    start_server()
