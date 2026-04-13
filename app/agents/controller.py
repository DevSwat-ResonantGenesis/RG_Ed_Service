"""Multi-agent controller for orchestrating agent instances."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set
import uuid
import httpx

from ..config import settings
from ..tools import tool_registry


@dataclass
class AgentState:
    """State of an agent instance."""
    id: str
    name: str
    status: str = "idle"  # idle, thinking, executing, waiting, error
    current_task: Optional[str] = None
    workspace_id: Optional[str] = None
    tools_enabled: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    message_history: List[Dict[str, str]] = field(default_factory=list)
    last_heartbeat: Optional[datetime] = None
    total_actions: int = 0
    total_tokens: int = 0


@dataclass
class AgentTask:
    """A task assigned to an agent."""
    id: str
    agent_id: str
    description: str
    status: str = "pending"  # pending, running, completed, failed, cancelled
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class AgentController:
    """Controls multiple agent instances."""

    def __init__(self):
        self.agents: Dict[str, AgentState] = {}
        self.tasks: Dict[str, AgentTask] = {}
        self.task_queues: Dict[str, asyncio.Queue] = {}
        self.agent_workers: Dict[str, asyncio.Task] = {}
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.max_agents = settings.MAX_CONCURRENT_AGENTS

    async def create_agent(
        self,
        name: str,
        workspace_id: Optional[str] = None,
        tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
    ) -> AgentState:
        """Create a new agent instance."""
        if len(self.agents) >= self.max_agents:
            raise ValueError(f"Maximum agents ({self.max_agents}) reached")

        agent_id = str(uuid.uuid4())
        
        # Default tools if none specified
        if tools is None:
            tools = [
                "execute_code", "read_file", "write_file", "list_files",
                "search_files", "search_content", "memory_search",
                "memory_store", "ask_llm", "get_current_time",
            ]

        agent = AgentState(
            id=agent_id,
            name=name,
            workspace_id=workspace_id,
            tools_enabled=tools,
            context={
                "system_prompt": system_prompt or self._default_system_prompt(),
                "workspace_id": workspace_id,
            },
            last_heartbeat=datetime.utcnow(),
        )

        self.agents[agent_id] = agent
        self.task_queues[agent_id] = asyncio.Queue()

        # Start agent worker
        self.agent_workers[agent_id] = asyncio.create_task(
            self._agent_worker(agent_id)
        )

        await self._emit_event("agent_created", {"agent": agent})
        return agent

    def _default_system_prompt(self) -> str:
        """Default system prompt for agents."""
        return """You are a DevSwat coding agent — an autonomous AI with access to code execution, file management, and memory tools.

<execution>
- You are AUTONOMOUS. Execute the full task using available tools without asking for permission.
- Execute code in Python, JavaScript, or Bash. Read, write, and search files. Store and retrieve information from memory.
- Think step-by-step: analyze what's needed, use tools, verify results.
- Every claim must be backed by tool output. Never fabricate data or results.
- If a tool call fails, try a different approach. At least 3 strategies before reporting failure.
</execution>

<code_quality>
- Write immediately runnable code with all necessary imports and dependencies.
- Read files before editing. Verify changes after writing.
- For web apps, use modern UI frameworks (React, TailwindCSS) with beautiful, responsive design.
- Use Markdown formatting in responses: **bold** for key terms, `code` for technical values, code blocks with language tags.
- End with a clear status of what was accomplished.
</code_quality>"""

    async def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent instance."""
        if agent_id not in self.agents:
            return False

        # Cancel worker
        if agent_id in self.agent_workers:
            self.agent_workers[agent_id].cancel()
            try:
                await self.agent_workers[agent_id]
            except asyncio.CancelledError:
                pass
            del self.agent_workers[agent_id]

        # Clean up
        if agent_id in self.task_queues:
            del self.task_queues[agent_id]

        agent = self.agents.pop(agent_id)
        await self._emit_event("agent_deleted", {"agent_id": agent_id})
        return True

    async def get_agent(self, agent_id: str) -> Optional[AgentState]:
        """Get agent state."""
        return self.agents.get(agent_id)

    async def list_agents(self) -> List[AgentState]:
        """List all agents."""
        return list(self.agents.values())

    async def assign_task(
        self,
        agent_id: str,
        description: str,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> AgentTask:
        """Assign a task to an agent."""
        if agent_id not in self.agents:
            raise ValueError(f"Agent not found: {agent_id}")

        task = AgentTask(
            id=str(uuid.uuid4()),
            agent_id=agent_id,
            description=description,
            input_data=input_data or {},
        )

        self.tasks[task.id] = task
        await self.task_queues[agent_id].put(task)

        await self._emit_event("task_assigned", {"task": task})
        return task

    async def get_task(self, task_id: str) -> Optional[AgentTask]:
        """Get task status."""
        return self.tasks.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task."""
        task = self.tasks.get(task_id)
        if not task or task.status not in ["pending", "running"]:
            return False

        task.status = "cancelled"
        await self._emit_event("task_cancelled", {"task_id": task_id})
        return True

    async def _agent_worker(self, agent_id: str):
        """Worker loop for an agent."""
        queue = self.task_queues[agent_id]

        while True:
            try:
                # Wait for task
                task = await queue.get()

                if task.status == "cancelled":
                    continue

                agent = self.agents[agent_id]
                agent.status = "thinking"
                agent.current_task = task.description
                task.status = "running"

                await self._emit_event("task_started", {"task": task})

                try:
                    # Execute task
                    result = await self._execute_task(agent, task)
                    
                    task.output_data = result
                    task.status = "completed"
                    task.completed_at = datetime.utcnow()

                    await self._emit_event("task_completed", {"task": task})

                except Exception as e:
                    task.status = "failed"
                    task.error = str(e)
                    task.completed_at = datetime.utcnow()

                    await self._emit_event("task_failed", {"task": task, "error": str(e)})

                finally:
                    agent.status = "idle"
                    agent.current_task = None
                    agent.total_actions += 1

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but keep worker running
                await self._emit_event("agent_error", {"agent_id": agent_id, "error": str(e)})

    async def _execute_task(
        self, agent: AgentState, task: AgentTask
    ) -> Dict[str, Any]:
        """Execute a task using the agent's tools."""
        # Build context for tool execution
        context = {
            "agent_id": agent.id,
            "workspace_id": agent.workspace_id,
            "task_id": task.id,
        }

        # Add task to message history
        agent.message_history.append({
            "role": "user",
            "content": task.description,
        })

        # Get available tools for this agent
        available_tools = [
            tool_registry.get_tool_schema(name)
            for name in agent.tools_enabled
            if tool_registry.get_tool(name)
        ]

        # Call LLM to plan and execute
        max_iterations = 10
        results = []

        for iteration in range(max_iterations):
            agent.status = "thinking"

            # Ask LLM what to do
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{settings.LLM_SERVICE_URL}/llm/agent/run",
                        json={
                            "messages": agent.message_history,
                            "tools": available_tools,
                            "max_iterations": 1,
                        },
                        headers={"x-user-id": context.get("user_id", "")},
                        timeout=60.0,
                    )

                    if resp.status_code != 200:
                        raise Exception(f"LLM service error: {resp.status_code}")

                    llm_response = resp.json()

            except Exception as e:
                # Fallback: simple execution without LLM planning
                return await self._simple_execute(agent, task, context)

            # Check if LLM wants to use a tool
            tool_calls = llm_response.get("tool_calls", [])
            
            if not tool_calls:
                # LLM is done, return final response
                final_response = llm_response.get("content", "")
                agent.message_history.append({
                    "role": "assistant",
                    "content": final_response,
                })
                return {
                    "response": final_response,
                    "actions": results,
                    "iterations": iteration + 1,
                }

            # Execute tool calls
            agent.status = "executing"
            
            for tool_call in tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("arguments", {})

                # Check if tool requires approval
                tool = tool_registry.get_tool(tool_name)
                if tool and tool.requires_approval:
                    await self._emit_event("approval_required", {
                        "agent_id": agent.id,
                        "tool": tool_name,
                        "arguments": tool_args,
                    })
                    # For now, skip tools requiring approval
                    continue

                # Execute tool
                result = await tool_registry.execute(tool_name, tool_args, context)
                
                results.append({
                    "tool": tool_name,
                    "arguments": tool_args,
                    "result": result.output if result.success else result.error,
                    "success": result.success,
                })

                # Add to message history
                agent.message_history.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": str(result.output if result.success else result.error),
                })

                agent.total_tokens += result.duration_ms  # Approximate

        return {
            "response": "Max iterations reached",
            "actions": results,
            "iterations": max_iterations,
        }

    async def _simple_execute(
        self, agent: AgentState, task: AgentTask, context: Dict
    ) -> Dict[str, Any]:
        """Simple task execution without LLM planning."""
        # Check if task looks like code execution
        if "```" in task.description or task.description.strip().startswith("def "):
            # Extract code
            code = task.description
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0]
            elif "```" in code:
                code = code.split("```")[1].split("```")[0]

            result = await tool_registry.execute("execute_code", {"code": code}, context)
            return {
                "response": f"Executed code:\n{result.output}" if result.success else f"Error: {result.error}",
                "actions": [{"tool": "execute_code", "result": result.output, "success": result.success}],
            }

        return {
            "response": "Task received but no LLM available for planning",
            "actions": [],
        }

    def on_event(self, event_type: str, handler: Callable):
        """Register an event handler."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    async def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit an event to all handlers."""
        handlers = self.event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception:
                pass  # Don't let handler errors break the controller

    async def broadcast_to_agents(
        self, message: str, agent_ids: Optional[List[str]] = None
    ):
        """Broadcast a message to multiple agents."""
        targets = agent_ids or list(self.agents.keys())
        
        for agent_id in targets:
            if agent_id in self.agents:
                agent = self.agents[agent_id]
                agent.message_history.append({
                    "role": "system",
                    "content": f"[Broadcast] {message}",
                })

    async def get_agent_stats(self) -> Dict[str, Any]:
        """Get statistics about all agents."""
        return {
            "total_agents": len(self.agents),
            "active_agents": sum(1 for a in self.agents.values() if a.status != "idle"),
            "total_tasks": len(self.tasks),
            "pending_tasks": sum(1 for t in self.tasks.values() if t.status == "pending"),
            "completed_tasks": sum(1 for t in self.tasks.values() if t.status == "completed"),
            "failed_tasks": sum(1 for t in self.tasks.values() if t.status == "failed"),
        }


agent_controller = AgentController()
