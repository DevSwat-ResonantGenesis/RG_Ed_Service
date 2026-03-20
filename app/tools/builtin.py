"""Built-in tools for agents."""

from typing import Any, Dict, List, Optional
import httpx

from .registry import tool_registry, ToolParameter
from ..sandbox import sandbox_executor, SandboxConfig
from ..filesystem import fs_manager
from ..config import settings


def register_builtin_tools():
    """Register all built-in tools."""

    # ============== CODE EXECUTION TOOLS ==============

    @tool_registry.register(
        name="execute_code",
        description="Execute code in a sandboxed environment",
        category="code",
        parameters=[
            ToolParameter("code", "string", "The code to execute"),
            ToolParameter("language", "string", "Programming language (python, javascript, bash)", default="python"),
            ToolParameter("timeout", "integer", "Execution timeout in seconds", required=False, default=60),
        ],
        returns="Execution result with stdout, stderr, and exit code",
    )
    async def execute_code(
        code: str,
        language: str = "python",
        timeout: int = 60,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        config = SandboxConfig(
            language=language,
            timeout_seconds=timeout,
        )
        
        if context and context.get("workspace_id"):
            config.working_dir = str(fs_manager.workspace_root / context["workspace_id"])

        result = await sandbox_executor.execute(code, config)
        
        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
        }

    @tool_registry.register(
        name="validate_code",
        description="Validate code syntax without executing",
        category="code",
        parameters=[
            ToolParameter("code", "string", "The code to validate"),
            ToolParameter("language", "string", "Programming language", default="python"),
        ],
        returns="Validation result with any syntax errors",
    )
    async def validate_code(code: str, language: str = "python") -> Dict[str, Any]:
        valid, error = await sandbox_executor.validate_code(code, language)
        return {"valid": valid, "error": error}

    # ============== FILE SYSTEM TOOLS ==============

    @tool_registry.register(
        name="read_file",
        description="Read contents of a file",
        category="file",
        parameters=[
            ToolParameter("path", "string", "Path to the file"),
        ],
        returns="File contents as string",
    )
    async def read_file(path: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        result = await fs_manager.read_file(workspace_id, path)
        if result:
            return {
                "success": True,
                "content": result.content,
                "size": result.size_bytes,
            }
        return {"success": False, "error": "File not found"}

    @tool_registry.register(
        name="write_file",
        description="Write content to a file",
        category="file",
        parameters=[
            ToolParameter("path", "string", "Path to the file"),
            ToolParameter("content", "string", "Content to write"),
        ],
        returns="Success status",
    )
    async def write_file(
        path: str, content: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        success, error = await fs_manager.write_file(workspace_id, path, content)
        return {"success": success, "error": error}

    @tool_registry.register(
        name="list_files",
        description="List files in a directory",
        category="file",
        parameters=[
            ToolParameter("path", "string", "Directory path", required=False, default=""),
            ToolParameter("recursive", "boolean", "List recursively", required=False, default=False),
        ],
        returns="List of files with metadata",
    )
    async def list_files(
        path: str = "",
        recursive: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        files = await fs_manager.list_directory(workspace_id, path, recursive)
        return {
            "success": True,
            "files": [
                {
                    "path": f.path,
                    "name": f.name,
                    "is_directory": f.is_directory,
                    "size": f.size_bytes,
                }
                for f in files
            ],
        }

    @tool_registry.register(
        name="search_files",
        description="Search for files by name pattern",
        category="file",
        parameters=[
            ToolParameter("pattern", "string", "Glob pattern to match (e.g., '*.py')"),
            ToolParameter("path", "string", "Directory to search in", required=False, default=""),
        ],
        returns="List of matching files",
    )
    async def search_files(
        pattern: str,
        path: str = "",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        files = await fs_manager.search_files(workspace_id, pattern, path)
        return {
            "success": True,
            "files": [{"path": f.path, "name": f.name} for f in files],
        }

    @tool_registry.register(
        name="search_content",
        description="Search file contents for a string",
        category="file",
        parameters=[
            ToolParameter("query", "string", "Text to search for"),
            ToolParameter("path", "string", "Directory to search in", required=False, default=""),
        ],
        returns="List of matches with file path and line number",
    )
    async def search_content(
        query: str,
        path: str = "",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        results = await fs_manager.search_content(workspace_id, query, path)
        return {"success": True, "matches": results}

    @tool_registry.register(
        name="delete_file",
        description="Delete a file or directory",
        category="file",
        parameters=[
            ToolParameter("path", "string", "Path to delete"),
        ],
        returns="Success status",
        requires_approval=True,
    )
    async def delete_file(path: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        workspace_id = context.get("workspace_id") if context else None
        if not workspace_id:
            return {"success": False, "error": "No workspace context"}

        success, error = await fs_manager.delete_file(workspace_id, path)
        return {"success": success, "error": error}

    # ============== MEMORY TOOLS ==============

    @tool_registry.register(
        name="memory_search",
        description="Search memories for relevant information",
        category="memory",
        parameters=[
            ToolParameter("query", "string", "Search query"),
            ToolParameter("limit", "integer", "Maximum results", required=False, default=5),
        ],
        returns="List of relevant memories",
    )
    async def memory_search(
        query: str,
        limit: int = 5,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.MEMORY_SERVICE_URL}/memory/retrieve",
                    json={"query": query, "limit": limit},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"success": True, "memories": resp.json()}
                return {"success": False, "error": f"Memory service error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="memory_store",
        description="Store information in memory",
        category="memory",
        parameters=[
            ToolParameter("content", "string", "Content to store"),
            ToolParameter("source", "string", "Source identifier", required=False, default="agent"),
        ],
        returns="Stored memory ID",
    )
    async def memory_store(
        content: str,
        source: str = "agent",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.MEMORY_SERVICE_URL}/memory/ingest",
                    json={"content": content, "source": source},
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"success": True, "memory": resp.json()}
                return {"success": False, "error": f"Memory service error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============== WORKFLOW TOOLS ==============

    @tool_registry.register(
        name="trigger_workflow",
        description="Trigger a workflow by ID",
        category="workflow",
        parameters=[
            ToolParameter("workflow_id", "string", "ID of the workflow to trigger"),
            ToolParameter("input_data", "object", "Input data for the workflow", required=False),
        ],
        returns="Workflow run ID and status",
    )
    async def trigger_workflow(
        workflow_id: str,
        input_data: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.WORKFLOW_SERVICE_URL}/workflow/workflows/{workflow_id}/run",
                    json={"input_data": input_data or {}},
                    timeout=30.0,
                )
                if resp.status_code in [200, 201]:
                    return {"success": True, "run": resp.json()}
                return {"success": False, "error": f"Workflow service error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============== LLM TOOLS ==============

    @tool_registry.register(
        name="ask_llm",
        description="Ask the LLM a question or request completion",
        category="llm",
        parameters=[
            ToolParameter("prompt", "string", "The prompt or question"),
            ToolParameter("system_prompt", "string", "System prompt for context", required=False),
            ToolParameter("max_tokens", "integer", "Maximum tokens in response", required=False, default=1000),
        ],
        returns="LLM response",
    )
    async def ask_llm(
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1000,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.LLM_SERVICE_URL}/llm/chat/completions",
                    json={
                        "messages": messages,
                        "max_tokens": max_tokens,
                    },
                    timeout=60.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "success": True,
                        "response": data.get("content", ""),
                        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
                    }
                return {"success": False, "error": f"LLM service error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============== COGNITIVE TOOLS ==============

    @tool_registry.register(
        name="log_insight",
        description="Log a cognitive insight or observation",
        category="cognitive",
        parameters=[
            ToolParameter("kind", "string", "Type of insight"),
            ToolParameter("content", "string", "Insight content"),
        ],
        returns="Logged tick ID",
    )
    async def log_insight(
        kind: str,
        content: str,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{settings.COGNITIVE_SERVICE_URL}/cognitive/ticks",
                    json={
                        "kind": kind,
                        "payload": content,
                        "auto_analyze": True,
                    },
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    return {"success": True, "tick": resp.json()}
                return {"success": False, "error": f"Cognitive service error: {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============== UTILITY TOOLS ==============

    @tool_registry.register(
        name="get_current_time",
        description="Get the current date and time",
        category="utility",
        parameters=[],
        returns="Current timestamp",
    )
    async def get_current_time(context: Optional[Dict] = None) -> Dict[str, Any]:
        from datetime import datetime
        now = datetime.utcnow()
        return {
            "success": True,
            "timestamp": now.isoformat(),
            "unix": int(now.timestamp()),
        }

    @tool_registry.register(
        name="http_request",
        description="Make an HTTP request to an external API",
        category="utility",
        parameters=[
            ToolParameter("url", "string", "URL to request"),
            ToolParameter("method", "string", "HTTP method", required=False, default="GET"),
            ToolParameter("headers", "object", "Request headers", required=False),
            ToolParameter("body", "object", "Request body for POST/PUT", required=False),
        ],
        returns="HTTP response",
        requires_approval=True,
    )
    async def http_request(
        url: str,
        method: str = "GET",
        headers: Optional[Dict] = None,
        body: Optional[Dict] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=body if method.upper() in ["POST", "PUT", "PATCH"] else None,
                    timeout=30.0,
                )
                return {
                    "success": True,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": resp.text[:10000],  # Limit response size
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
