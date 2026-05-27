"""Tinyflow 工作流编排（可独立部署）。"""
from src.flowgame.app import app as flowgame_app
from src.flowgame.constants import API_PREFIX
from src.flowgame.registry import register_routes
from src.flowgame.router import flowgame_router
from src.flowgame.service import FlowGameExecuteService, flow_game_execute_service
from src.flowgame.tinyflow import Tinyflow

__all__ = [
    "API_PREFIX",
    "Tinyflow",
    "FlowGameExecuteService",
    "flow_game_execute_service",
    "flowgame_router",
    "flowgame_app",
    "register_routes",
]
