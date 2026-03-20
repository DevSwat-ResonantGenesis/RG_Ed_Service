"""Sandbox code execution engine with Docker isolation."""

import asyncio
import hashlib
import os
import subprocess
import tempfile
import time
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple
import uuid
import logging

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of code execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    error: Optional[str] = None
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution."""
    language: str = "python"
    timeout_seconds: int = 60
    memory_limit_mb: int = 256
    cpu_limit: float = 0.5
    network_enabled: bool = False
    env_vars: Dict[str, str] = field(default_factory=dict)
    working_dir: Optional[str] = None
    allowed_imports: Optional[List[str]] = None
    read_only_fs: bool = True
    max_output_size: int = 1024 * 1024  # 1MB


class SandboxExecutor:
    """Executes code in isolated Docker sandboxes."""

    def __init__(self):
        self.active_containers: Dict[str, str] = {}  # session_id -> container_id
        self.language_configs = {
            "python": {
                "extension": ".py",
                "command": ["python3", "-u"],  # -u for unbuffered output
                "image": "python:3.11-alpine",
                "workdir": "/sandbox",
            },
            "javascript": {
                "extension": ".js",
                "command": ["node"],
                "image": "node:18-alpine",
                "workdir": "/sandbox",
            },
            "typescript": {
                "extension": ".ts",
                "command": ["npx", "ts-node"],
                "image": "node:18-alpine",
                "workdir": "/sandbox",
            },
            "bash": {
                "extension": ".sh",
                "command": ["sh"],  # Use sh instead of bash for alpine
                "image": "alpine:3.19",
                "workdir": "/sandbox",
            },
        }

    async def _create_sandbox_container(
        self,
        code: str,
        config: SandboxConfig,
        lang_config: Dict[str, Any],
        session_id: str,
    ) -> str:
        """Create an isolated Docker container for code execution."""
        
        # Create temporary directory for code
        temp_dir = tempfile.mkdtemp(prefix=f"sandbox_{session_id}_")
        code_file = os.path.join(temp_dir, f"main{lang_config['extension']}")
        
        with open(code_file, 'w') as f:
            f.write(code)
        
        # Build docker run command with security constraints
        docker_cmd = [
            "docker", "run",
            "-d",  # Detached
            "--rm",  # Auto-remove on exit
            f"--name=sandbox_{session_id}",
            
            # Resource limits
            f"--memory={config.memory_limit_mb}m",
            f"--memory-swap={config.memory_limit_mb}m",  # No swap
            f"--cpus={config.cpu_limit}",
            "--pids-limit=50",  # Limit processes
            
            # Security constraints
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",  # Drop all capabilities
            "--user=nobody",  # Run as non-root
            
            # Filesystem
            f"--workdir={lang_config['workdir']}",
            f"-v={temp_dir}:{lang_config['workdir']}:ro",  # Read-only code mount
        ]
        
        # Network isolation
        if not config.network_enabled:
            docker_cmd.append("--network=none")
        
        # Read-only root filesystem
        if config.read_only_fs:
            docker_cmd.extend([
                "--read-only",
                "--tmpfs=/tmp:rw,noexec,nosuid,size=10m",  # Small writable tmp
            ])
        
        # Environment variables (sanitized)
        for key, value in config.env_vars.items():
            if not key.startswith('_'):  # Skip internal vars
                docker_cmd.append(f"-e={key}={value}")
        
        # Image and command
        docker_cmd.append(lang_config["image"])
        docker_cmd.append("sleep")
        docker_cmd.append(str(config.timeout_seconds + 5))  # Keep alive for execution
        
        logger.info(f"Creating sandbox container for session {session_id}")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                raise RuntimeError(f"Failed to create container: {stderr.decode()}")
            
            container_id = stdout.decode().strip()
            self.active_containers[session_id] = container_id
            
            logger.info(f"Created container {container_id[:12]} for session {session_id}")
            return container_id
            
        except Exception as e:
            # Cleanup temp dir on failure
            try:
                os.system(f"rm -rf {temp_dir}")
            except:
                pass
            raise

    async def _execute_in_container(
        self,
        container_id: str,
        lang_config: Dict[str, Any],
        config: SandboxConfig,
    ) -> Tuple[int, str, str]:
        """Execute code inside the container."""
        
        # Build exec command
        exec_cmd = [
            "docker", "exec",
            container_id,
        ] + lang_config["command"] + [f"{lang_config['workdir']}/main{lang_config['extension']}"]
        
        logger.info(f"Executing code in container {container_id[:12]}")
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=config.timeout_seconds,
                )
                
                # Truncate output if too large
                stdout_str = stdout.decode("utf-8", errors="replace")[:config.max_output_size]
                stderr_str = stderr.decode("utf-8", errors="replace")[:config.max_output_size]
                
                return proc.returncode, stdout_str, stderr_str
                
            except asyncio.TimeoutError:
                # Kill the container on timeout
                await self._kill_container(container_id)
                raise
                
        except Exception as e:
            logger.error(f"Execution failed in container {container_id[:12]}: {e}")
            raise

    async def _kill_container(self, container_id: str) -> None:
        """Forcefully kill a container."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "kill", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info(f"Killed container {container_id[:12]}")
        except Exception as e:
            logger.warning(f"Failed to kill container {container_id[:12]}: {e}")

    async def _cleanup_container(self, container_id: str, session_id: str) -> None:
        """Clean up container and temporary files."""
        try:
            # Stop container (will auto-remove due to --rm flag)
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "-t", "2", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            
            # Remove from active containers
            self.active_containers.pop(session_id, None)
            
            # Clean up temp directory
            temp_dir = f"/tmp/sandbox_{session_id}_*"
            os.system(f"rm -rf {temp_dir}")
            
            logger.info(f"Cleaned up container {container_id[:12]} and session {session_id}")
            
        except Exception as e:
            logger.warning(f"Cleanup failed for container {container_id[:12]}: {e}")

    async def execute(
        self,
        code: str,
        config: Optional[SandboxConfig] = None,
        session_id: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute code in an isolated Docker sandbox."""
        config = config or SandboxConfig()
        session_id = session_id or str(uuid.uuid4())
        
        lang_config = self.language_configs.get(config.language)
        if not lang_config:
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Unsupported language: {config.language}",
                duration_ms=0,
                error=f"Unsupported language: {config.language}",
            )

        start_time = time.time()
        container_id = None

        try:
            # Create isolated container
            container_id = await self._create_sandbox_container(
                code, config, lang_config, session_id
            )
            
            # Execute code in container
            exit_code, stdout, stderr = await self._execute_in_container(
                container_id, lang_config, config
            )
            
            duration_ms = int((time.time() - start_time) * 1000)
            
            return ExecutionResult(
                success=exit_code == 0,
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
            
        except asyncio.TimeoutError:
            duration_ms = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=f"Execution timed out after {config.timeout_seconds} seconds",
                duration_ms=duration_ms,
                error="Execution timed out",
            )
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Sandbox execution failed for session {session_id}: {e}")
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=duration_ms,
                error=str(e),
            )
            
        finally:
            # Always cleanup container
            if container_id:
                await self._cleanup_container(container_id, session_id)

    async def execute_stream(
        self,
        code: str,
        config: Optional[SandboxConfig] = None,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[Tuple[str, str], None]:
        """Execute code and stream output."""
        config = config or SandboxConfig()
        session_id = session_id or str(uuid.uuid4())

        lang_config = self.language_configs.get(config.language)
        if not lang_config:
            yield ("stderr", f"Unsupported language: {config.language}")
            return

        # Create temporary file for code
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=lang_config["extension"],
            delete=False,
        ) as f:
            f.write(code)
            code_file = f.name

        try:
            cmd = lang_config["command"] + [code_file]
            env = os.environ.copy()
            env.update(config.env_vars)

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=config.working_dir,
            )

            self.active_executions[session_id] = process

            async def read_stream(stream, name):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    yield (name, line.decode("utf-8", errors="replace"))

            # Read both streams concurrently
            stdout_task = asyncio.create_task(
                self._collect_stream(process.stdout, "stdout")
            )
            stderr_task = asyncio.create_task(
                self._collect_stream(process.stderr, "stderr")
            )

            # Yield lines as they come
            while not stdout_task.done() or not stderr_task.done():
                done, pending = await asyncio.wait(
                    [stdout_task, stderr_task],
                    timeout=0.1,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    for stream_name, line in task.result():
                        yield (stream_name, line)

            await process.wait()
            self.active_executions.pop(session_id, None)

            yield ("system", f"Process exited with code {process.returncode}")

        finally:
            try:
                os.unlink(code_file)
            except:
                pass

    async def _collect_stream(
        self, stream, name: str
    ) -> List[Tuple[str, str]]:
        """Collect all lines from a stream."""
        lines = []
        while True:
            line = await stream.readline()
            if not line:
                break
            lines.append((name, line.decode("utf-8", errors="replace")))
        return lines

    async def cancel(self, session_id: str) -> bool:
        """Cancel a running execution."""
        container_id = self.active_containers.get(session_id)
        if container_id:
            await self._kill_container(container_id)
            await self._cleanup_container(container_id, session_id)
            return True
        return False

    def get_active_sessions(self) -> List[str]:
        """Get list of active execution sessions."""
        return list(self.active_containers.keys())
    
    async def get_container_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get resource usage stats for a container."""
        container_id = self.active_containers.get(session_id)
        if not container_id:
            return None
        
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stats", "--no-stream", "--format", "{{json .}}", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            
            if proc.returncode == 0:
                return json.loads(stdout.decode())
            return None
            
        except Exception as e:
            logger.warning(f"Failed to get stats for container {container_id[:12]}: {e}")
            return None

    async def validate_code(
        self, code: str, language: str = "python"
    ) -> Tuple[bool, Optional[str]]:
        """Validate code syntax without executing."""
        if language == "python":
            try:
                compile(code, "<string>", "exec")
                return True, None
            except SyntaxError as e:
                return False, f"Syntax error at line {e.lineno}: {e.msg}"
        
        # For other languages, we'd need language-specific validators
        return True, None


sandbox_executor = SandboxExecutor()
