# Agent tools module
from .registry import ToolRegistry, tool_registry
from .builtin import register_builtin_tools
from .git_tools import register_git_tools
from .docker_tools import register_docker_tools
from .test_tools import register_test_tools

__all__ = [
    "ToolRegistry",
    "tool_registry",
    "register_builtin_tools",
    "register_git_tools",
    "register_docker_tools",
    "register_test_tools",
]


def register_all_tools():
    """Register all available tools."""
    register_builtin_tools()
    register_git_tools()
    register_docker_tools()
    register_test_tools()
