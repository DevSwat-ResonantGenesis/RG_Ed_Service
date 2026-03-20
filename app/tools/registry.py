"""Tool registry for agent tools."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import asyncio
import inspect


@dataclass
class ToolParameter:
    """Parameter definition for a tool."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    """Definition of an agent tool."""
    name: str
    description: str
    category: str
    parameters: List[ToolParameter]
    returns: str
    handler: Callable
    requires_approval: bool = False
    is_async: bool = True


@dataclass
class ToolResult:
    """Result of tool execution."""
    success: bool
    output: Any
    error: Optional[str] = None
    duration_ms: int = 0


class ToolRegistry:
    """Registry for agent tools."""

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self.categories: Dict[str, List[str]] = {}

    def register(
        self,
        name: str,
        description: str,
        category: str,
        parameters: List[ToolParameter],
        returns: str,
        requires_approval: bool = False,
    ):
        """Decorator to register a tool."""
        def decorator(func: Callable):
            is_async = asyncio.iscoroutinefunction(func)
            
            tool = ToolDefinition(
                name=name,
                description=description,
                category=category,
                parameters=parameters,
                returns=returns,
                handler=func,
                requires_approval=requires_approval,
                is_async=is_async,
            )
            
            self.tools[name] = tool
            
            if category not in self.categories:
                self.categories[category] = []
            self.categories[category].append(name)
            
            return func
        return decorator

    def register_tool(self, tool: ToolDefinition):
        """Register a tool directly."""
        self.tools[tool.name] = tool
        
        if tool.category not in self.categories:
            self.categories[tool.category] = []
        self.categories[tool.category].append(tool.name)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self, category: Optional[str] = None) -> List[ToolDefinition]:
        """List all tools, optionally filtered by category."""
        if category:
            tool_names = self.categories.get(category, [])
            return [self.tools[name] for name in tool_names]
        return list(self.tools.values())

    def list_categories(self) -> List[str]:
        """List all tool categories."""
        return list(self.categories.keys())

    async def execute(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        """Execute a tool."""
        import time
        start_time = time.time()

        tool = self.tools.get(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool not found: {tool_name}",
            )

        try:
            # Validate required parameters
            for param in tool.parameters:
                if param.required and param.name not in parameters:
                    return ToolResult(
                        success=False,
                        output=None,
                        error=f"Missing required parameter: {param.name}",
                    )

            # Add context if handler accepts it
            sig = inspect.signature(tool.handler)
            if "context" in sig.parameters:
                parameters["context"] = context

            # Execute handler
            if tool.is_async:
                result = await tool.handler(**parameters)
            else:
                result = tool.handler(**parameters)

            duration_ms = int((time.time() - start_time) * 1000)

            return ToolResult(
                success=True,
                output=result,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=False,
                output=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get JSON schema for a tool (for LLM function calling)."""
        tool = self.tools.get(tool_name)
        if not tool:
            return None

        properties = {}
        required = []

        for param in tool.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                properties[param.name]["default"] = param.default
            if param.required:
                required.append(param.name)

        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get schemas for all tools."""
        return [
            self.get_tool_schema(name)
            for name in self.tools
        ]


tool_registry = ToolRegistry()
