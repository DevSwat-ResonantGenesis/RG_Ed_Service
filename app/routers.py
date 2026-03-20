"""ED Service API routers."""

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import (
    ExecutionSession, ExecutionLog, Workspace, WorkspaceFile,
    AgentInstance, AgentAction, ToolDefinition,
)
from .sandbox import sandbox_executor, SandboxConfig
from .filesystem import fs_manager
from .tools import tool_registry, register_builtin_tools
from .agents import agent_controller
from .websocket import ws_manager, execution_channel, agent_channel, workspace_channel


router = APIRouter(prefix="/ed", tags=["ed"])

# Register built-in tools on startup
register_builtin_tools()


# ============== Request/Response Models ==============

class ExecuteCodeRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: int = 60
    workspace_id: Optional[str] = None


class ExecuteCodeResponse(BaseModel):
    session_id: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    root_path: str
    is_active: bool


class FileOperationRequest(BaseModel):
    path: str
    content: Optional[str] = None


class FileResponse(BaseModel):
    path: str
    name: str
    content: Optional[str] = None
    size: int = 0
    is_directory: bool = False


class CreateAgentRequest(BaseModel):
    name: str
    workspace_id: Optional[str] = None
    tools: Optional[List[str]] = None
    system_prompt: Optional[str] = None


class AgentResponse(BaseModel):
    id: str
    name: str
    status: str
    workspace_id: Optional[str]
    tools_enabled: List[str]
    total_actions: int


class AssignTaskRequest(BaseModel):
    description: str
    input_data: Optional[Dict[str, Any]] = None


class TaskResponse(BaseModel):
    id: str
    agent_id: str
    description: str
    status: str
    output_data: Optional[Dict[str, Any]]
    error: Optional[str]


# ============== Execution Endpoints ==============

@router.post("/execute", response_model=ExecuteCodeResponse)
async def execute_code(
    payload: ExecuteCodeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Execute code in a sandbox."""
    user_id = request.headers.get("x-user-id")
    session_id = str(uuid.uuid4())

    # Create execution session record
    exec_session = ExecutionSession(
        id=session_id,
        user_id=user_id,
        workspace_id=payload.workspace_id,
        language=payload.language,
        status="running",
        started_at=datetime.utcnow(),
    )
    session.add(exec_session)
    await session.commit()

    # Configure sandbox
    config = SandboxConfig(
        language=payload.language,
        timeout_seconds=payload.timeout,
    )
    
    if payload.workspace_id:
        config.working_dir = str(fs_manager.workspace_root / payload.workspace_id)

    # Execute code
    result = await sandbox_executor.execute(payload.code, config, session_id)

    # Update session record
    exec_session.status = "completed" if result.success else "failed"
    exec_session.exit_code = result.exit_code
    exec_session.error_message = result.error
    exec_session.completed_at = datetime.utcnow()
    await session.commit()

    # Log output
    if result.stdout:
        log = ExecutionLog(session_id=session_id, stream="stdout", content=result.stdout)
        session.add(log)
    if result.stderr:
        log = ExecutionLog(session_id=session_id, stream="stderr", content=result.stderr)
        session.add(log)
    await session.commit()

    # Broadcast to WebSocket subscribers
    await ws_manager.broadcast_to_channel(execution_channel(session_id), {
        "type": "execution_complete",
        "session_id": session_id,
        "success": result.success,
        "exit_code": result.exit_code,
    })

    return ExecuteCodeResponse(
        session_id=session_id,
        success=result.success,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        duration_ms=result.duration_ms,
    )


@router.get("/execute/{session_id}/logs")
async def get_execution_logs(
    session_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Get logs for an execution session."""
    result = await session.execute(
        select(ExecutionLog)
        .where(ExecutionLog.session_id == session_id)
        .order_by(ExecutionLog.timestamp)
    )
    logs = result.scalars().all()
    
    return {
        "session_id": session_id,
        "logs": [
            {"stream": log.stream, "content": log.content, "timestamp": log.timestamp.isoformat()}
            for log in logs
        ],
    }


@router.post("/execute/{session_id}/cancel")
async def cancel_execution(session_id: str):
    """Cancel a running execution."""
    cancelled = await sandbox_executor.cancel(session_id)
    return {"cancelled": cancelled}


@router.post("/validate")
async def validate_code(payload: ExecuteCodeRequest):
    """Validate code syntax without executing."""
    valid, error = await sandbox_executor.validate_code(payload.code, payload.language)
    return {"valid": valid, "error": error}


# ============== Workspace Endpoints ==============

@router.post("/workspaces", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: CreateWorkspaceRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a new workspace."""
    user_id = request.headers.get("x-user-id")
    workspace_id = str(uuid.uuid4())

    # Initialize filesystem
    root_path = await fs_manager.init_workspace(workspace_id)

    # Create database record
    workspace = Workspace(
        id=workspace_id,
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        root_path=str(root_path),
    )
    session.add(workspace)
    await session.commit()

    return WorkspaceResponse(
        id=str(workspace.id),
        name=workspace.name,
        description=workspace.description,
        root_path=workspace.root_path,
        is_active=workspace.is_active,
    )


@router.get("/workspaces", response_model=List[WorkspaceResponse])
async def list_workspaces(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List user's workspaces."""
    user_id = request.headers.get("x-user-id")
    
    stmt = select(Workspace).where(Workspace.is_active == True)
    if user_id:
        stmt = stmt.where(Workspace.user_id == user_id)
    
    result = await session.execute(stmt)
    workspaces = result.scalars().all()

    return [
        WorkspaceResponse(
            id=str(w.id),
            name=w.name,
            description=w.description,
            root_path=w.root_path,
            is_active=w.is_active,
        )
        for w in workspaces
    ]


@router.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: str,
    path: str = "",
    recursive: bool = False,
):
    """List files in a workspace."""
    files = await fs_manager.list_directory(workspace_id, path, recursive)
    return {
        "workspace_id": workspace_id,
        "path": path,
        "files": [
            {
                "path": f.path,
                "name": f.name,
                "is_directory": f.is_directory,
                "size": f.size_bytes,
                "extension": f.extension,
            }
            for f in files
        ],
    }


@router.get("/workspaces/{workspace_id}/tree")
async def get_workspace_tree(workspace_id: str, max_depth: int = 5):
    """Get file tree for a workspace."""
    tree = await fs_manager.get_file_tree(workspace_id, max_depth)
    return {"workspace_id": workspace_id, "tree": tree}


@router.get("/workspaces/{workspace_id}/files/{path:path}")
async def read_file(workspace_id: str, path: str):
    """Read a file from workspace."""
    content = await fs_manager.read_file(workspace_id, path)
    if not content:
        raise HTTPException(status_code=404, detail="File not found")
    
    return {
        "path": content.path,
        "content": content.content,
        "size": content.size_bytes,
        "hash": content.content_hash,
    }


@router.put("/workspaces/{workspace_id}/files/{path:path}")
async def write_file(
    workspace_id: str,
    path: str,
    payload: FileOperationRequest,
):
    """Write a file to workspace."""
    if payload.content is None:
        raise HTTPException(status_code=400, detail="Content required")

    success, error = await fs_manager.write_file(workspace_id, path, payload.content)
    if not success:
        raise HTTPException(status_code=400, detail=error)

    # Broadcast file change
    await ws_manager.broadcast_to_channel(workspace_channel(workspace_id), {
        "type": "file_changed",
        "path": path,
        "action": "write",
    })

    return {"success": True, "path": path}


@router.delete("/workspaces/{workspace_id}/files/{path:path}")
async def delete_file(workspace_id: str, path: str):
    """Delete a file from workspace."""
    success, error = await fs_manager.delete_file(workspace_id, path)
    if not success:
        raise HTTPException(status_code=400, detail=error)

    # Broadcast file change
    await ws_manager.broadcast_to_channel(workspace_channel(workspace_id), {
        "type": "file_changed",
        "path": path,
        "action": "delete",
    })

    return {"success": True}


@router.post("/workspaces/{workspace_id}/search")
async def search_workspace(
    workspace_id: str,
    query: str,
    search_content: bool = False,
    path: str = "",
):
    """Search files in workspace."""
    if search_content:
        results = await fs_manager.search_content(workspace_id, query, path)
        return {"type": "content", "matches": results}
    else:
        files = await fs_manager.search_files(workspace_id, query, path)
        return {
            "type": "files",
            "files": [{"path": f.path, "name": f.name} for f in files],
        }


# ============== Agent Endpoints ==============

@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: CreateAgentRequest, request: Request):
    """Create a new agent instance."""
    user_id = request.headers.get("x-user-id")

    try:
        agent = await agent_controller.create_agent(
            name=payload.name,
            workspace_id=payload.workspace_id,
            tools=payload.tools,
            system_prompt=payload.system_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        workspace_id=agent.workspace_id,
        tools_enabled=agent.tools_enabled,
        total_actions=agent.total_actions,
    )


@router.get("/agents", response_model=List[AgentResponse])
async def list_agents():
    """List all agents."""
    agents = await agent_controller.list_agents()
    return [
        AgentResponse(
            id=a.id,
            name=a.name,
            status=a.status,
            workspace_id=a.workspace_id,
            tools_enabled=a.tools_enabled,
            total_actions=a.total_actions,
        )
        for a in agents
    ]


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str):
    """Get agent details."""
    agent = await agent_controller.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        workspace_id=agent.workspace_id,
        tools_enabled=agent.tools_enabled,
        total_actions=agent.total_actions,
    )


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Delete an agent."""
    deleted = await agent_controller.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"deleted": True}


@router.post("/agents/{agent_id}/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def assign_task(agent_id: str, payload: AssignTaskRequest):
    """Assign a task to an agent."""
    try:
        task = await agent_controller.assign_task(
            agent_id=agent_id,
            description=payload.description,
            input_data=payload.input_data,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return TaskResponse(
        id=task.id,
        agent_id=task.agent_id,
        description=task.description,
        status=task.status,
        output_data=task.output_data,
        error=task.error,
    )


@router.get("/agents/{agent_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task(agent_id: str, task_id: str):
    """Get task status."""
    task = await agent_controller.get_task(task_id)
    if not task or task.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=task.id,
        agent_id=task.agent_id,
        description=task.description,
        status=task.status,
        output_data=task.output_data,
        error=task.error,
    )


@router.get("/agents/stats")
async def get_agent_stats():
    """Get agent statistics."""
    return await agent_controller.get_agent_stats()


# ============== Tool Endpoints ==============

@router.get("/tools")
async def list_tools(category: Optional[str] = None):
    """List available tools."""
    tools = tool_registry.list_tools(category)
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "requires_approval": t.requires_approval,
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "description": p.description,
                        "required": p.required,
                    }
                    for p in t.parameters
                ],
            }
            for t in tools
        ],
        "categories": tool_registry.list_categories(),
    }


@router.get("/tools/schemas")
async def get_tool_schemas():
    """Get JSON schemas for all tools (for LLM function calling)."""
    return {"schemas": tool_registry.get_all_schemas()}


@router.post("/tools/{tool_name}/execute")
async def execute_tool(
    tool_name: str,
    parameters: Dict[str, Any],
    request: Request,
):
    """Execute a tool directly."""
    user_id = request.headers.get("x-user-id")
    workspace_id = parameters.pop("workspace_id", None)

    context = {
        "user_id": user_id,
        "workspace_id": workspace_id,
    }

    result = await tool_registry.execute(tool_name, parameters, context)
    
    return {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


# ============== WebSocket Endpoint ==============

@router.websocket("/ws/{connection_id}")
async def websocket_endpoint(websocket: WebSocket, connection_id: str):
    """WebSocket endpoint for real-time updates."""
    user_id = websocket.query_params.get("user_id")
    
    connected = await ws_manager.connect(websocket, connection_id, user_id)
    if not connected:
        return

    try:
        while True:
            data = await websocket.receive_json()
            await ws_manager.handle_message(connection_id, data)
    except WebSocketDisconnect:
        await ws_manager.disconnect(connection_id)
    except Exception:
        await ws_manager.disconnect(connection_id)


# ============== Health Endpoint ==============

@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "service": "ed",
        "status": "ok",
        "active_executions": len(sandbox_executor.get_active_sessions()),
        "active_agents": len(await agent_controller.list_agents()),
        "ws_connections": ws_manager.get_connection_count(),
    }
