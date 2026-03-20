"""Docker container management tools for autonomous agents."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from .registry import tool_registry, ToolParameter


def register_docker_tools():
    """Register all Docker operation tools."""

    @tool_registry.register(
        name="docker_build",
        description="Build a Docker image from a Dockerfile",
        category="docker",
        parameters=[
            ToolParameter("path", "string", "Path to build context (directory with Dockerfile)"),
            ToolParameter("tag", "string", "Image tag (e.g., myapp:latest)"),
            ToolParameter("dockerfile", "string", "Dockerfile name", required=False, default="Dockerfile"),
            ToolParameter("build_args", "object", "Build arguments", required=False),
            ToolParameter("no_cache", "boolean", "Build without cache", required=False, default=False),
        ],
        returns="Build result with image ID",
        requires_approval=True,
    )
    async def docker_build(
        path: str,
        tag: str,
        dockerfile: str = "Dockerfile",
        build_args: Optional[Dict[str, str]] = None,
        no_cache: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "build", "-t", tag, "-f", dockerfile]
            
            if no_cache:
                cmd.append("--no-cache")
            
            if build_args:
                for key, value in build_args.items():
                    cmd.extend(["--build-arg", f"{key}={value}"])
            
            cmd.append(path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=600,  # 10 minute timeout for builds
            )

            if proc.returncode == 0:
                # Get image ID
                id_proc = await asyncio.create_subprocess_exec(
                    "docker", "images", "-q", tag,
                    stdout=asyncio.subprocess.PIPE,
                )
                id_out, _ = await id_proc.communicate()
                
                return {
                    "success": True,
                    "tag": tag,
                    "image_id": id_out.decode().strip(),
                    "output": stdout.decode()[-2000:],  # Last 2000 chars
                }
            return {
                "success": False,
                "error": stderr.decode()[-2000:],
                "exit_code": proc.returncode,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Build timed out after 10 minutes"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_run",
        description="Run a Docker container",
        category="docker",
        parameters=[
            ToolParameter("image", "string", "Image name or ID"),
            ToolParameter("name", "string", "Container name", required=False),
            ToolParameter("command", "string", "Command to run", required=False),
            ToolParameter("ports", "object", "Port mappings (host:container)", required=False),
            ToolParameter("volumes", "array", "Volume mounts", required=False),
            ToolParameter("env", "object", "Environment variables", required=False),
            ToolParameter("detach", "boolean", "Run in background", required=False, default=True),
            ToolParameter("remove", "boolean", "Remove after exit", required=False, default=False),
        ],
        returns="Container ID and status",
        requires_approval=True,
    )
    async def docker_run(
        image: str,
        name: Optional[str] = None,
        command: Optional[str] = None,
        ports: Optional[Dict[str, str]] = None,
        volumes: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        detach: bool = True,
        remove: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "run"]
            
            if detach:
                cmd.append("-d")
            if remove:
                cmd.append("--rm")
            if name:
                cmd.extend(["--name", name])
            
            if ports:
                for host_port, container_port in ports.items():
                    cmd.extend(["-p", f"{host_port}:{container_port}"])
            
            if volumes:
                for vol in volumes:
                    cmd.extend(["-v", vol])
            
            if env:
                for key, value in env.items():
                    cmd.extend(["-e", f"{key}={value}"])
            
            cmd.append(image)
            
            if command:
                cmd.extend(command.split())

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                container_id = stdout.decode().strip()
                return {
                    "success": True,
                    "container_id": container_id[:12],
                    "name": name,
                    "detached": detach,
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_stop",
        description="Stop a running container",
        category="docker",
        parameters=[
            ToolParameter("container", "string", "Container name or ID"),
            ToolParameter("timeout", "integer", "Seconds to wait before killing", required=False, default=10),
        ],
        returns="Stop result",
    )
    async def docker_stop(
        container: str,
        timeout: int = 10,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", "-t", str(timeout), container,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "container": container, "stopped": True}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_logs",
        description="Get container logs",
        category="docker",
        parameters=[
            ToolParameter("container", "string", "Container name or ID"),
            ToolParameter("tail", "integer", "Number of lines from end", required=False, default=100),
            ToolParameter("follow", "boolean", "Follow log output", required=False, default=False),
        ],
        returns="Container logs",
    )
    async def docker_logs(
        container: str,
        tail: int = 100,
        follow: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "logs", "--tail", str(tail)]
            if not follow:
                # Don't follow for API calls
                pass
            cmd.append(container)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30,
            )

            # Docker logs go to both stdout and stderr
            logs = stdout.decode() + stderr.decode()
            
            return {
                "success": True,
                "container": container,
                "logs": logs[-20000:],  # Limit size
                "lines": len(logs.split("\n")),
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Log fetch timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_exec",
        description="Execute a command in a running container",
        category="docker",
        parameters=[
            ToolParameter("container", "string", "Container name or ID"),
            ToolParameter("command", "string", "Command to execute"),
            ToolParameter("workdir", "string", "Working directory", required=False),
            ToolParameter("user", "string", "User to run as", required=False),
        ],
        returns="Command output",
        requires_approval=True,
    )
    async def docker_exec(
        container: str,
        command: str,
        workdir: Optional[str] = None,
        user: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "exec"]
            
            if workdir:
                cmd.extend(["-w", workdir])
            if user:
                cmd.extend(["-u", user])
            
            cmd.append(container)
            cmd.extend(command.split())

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=300,  # 5 minute timeout
            )

            return {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": stdout.decode()[-10000:],
                "stderr": stderr.decode()[-5000:],
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timed out after 5 minutes"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_ps",
        description="List Docker containers",
        category="docker",
        parameters=[
            ToolParameter("all", "boolean", "Show all containers (including stopped)", required=False, default=False),
            ToolParameter("filter", "string", "Filter by name or status", required=False),
        ],
        returns="List of containers",
    )
    async def docker_ps(
        all: bool = False,
        filter: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "ps", "--format", "{{json .}}"]
            if all:
                cmd.append("-a")
            if filter:
                cmd.extend(["--filter", filter])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                containers = []
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        try:
                            containers.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                
                return {
                    "success": True,
                    "containers": containers,
                    "count": len(containers),
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_images",
        description="List Docker images",
        category="docker",
        parameters=[
            ToolParameter("filter", "string", "Filter by name", required=False),
        ],
        returns="List of images",
    )
    async def docker_images(
        filter: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "images", "--format", "{{json .}}"]
            if filter:
                cmd.append(filter)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                images = []
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        try:
                            images.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                
                return {
                    "success": True,
                    "images": images,
                    "count": len(images),
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_rm",
        description="Remove a container",
        category="docker",
        parameters=[
            ToolParameter("container", "string", "Container name or ID"),
            ToolParameter("force", "boolean", "Force remove running container", required=False, default=False),
            ToolParameter("volumes", "boolean", "Remove associated volumes", required=False, default=False),
        ],
        returns="Remove result",
        requires_approval=True,
    )
    async def docker_rm(
        container: str,
        force: bool = False,
        volumes: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker", "rm"]
            if force:
                cmd.append("-f")
            if volumes:
                cmd.append("-v")
            cmd.append(container)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "container": container, "removed": True}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_compose_up",
        description="Start services with docker-compose",
        category="docker",
        parameters=[
            ToolParameter("path", "string", "Path to docker-compose.yml directory"),
            ToolParameter("services", "array", "Specific services to start", required=False),
            ToolParameter("detach", "boolean", "Run in background", required=False, default=True),
            ToolParameter("build", "boolean", "Build images before starting", required=False, default=False),
        ],
        returns="Compose up result",
        requires_approval=True,
    )
    async def docker_compose_up(
        path: str,
        services: Optional[List[str]] = None,
        detach: bool = True,
        build: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker-compose", "up"]
            if detach:
                cmd.append("-d")
            if build:
                cmd.append("--build")
            if services:
                cmd.extend(services)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=600,
            )

            if proc.returncode == 0:
                return {
                    "success": True,
                    "services": services or "all",
                    "output": stdout.decode()[-2000:],
                }
            return {"success": False, "error": stderr.decode()[-2000:]}
        except asyncio.TimeoutError:
            return {"success": False, "error": "Compose up timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="docker_compose_down",
        description="Stop and remove docker-compose services",
        category="docker",
        parameters=[
            ToolParameter("path", "string", "Path to docker-compose.yml directory"),
            ToolParameter("volumes", "boolean", "Remove volumes", required=False, default=False),
            ToolParameter("remove_orphans", "boolean", "Remove orphan containers", required=False, default=True),
        ],
        returns="Compose down result",
    )
    async def docker_compose_down(
        path: str,
        volumes: bool = False,
        remove_orphans: bool = True,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["docker-compose", "down"]
            if volumes:
                cmd.append("-v")
            if remove_orphans:
                cmd.append("--remove-orphans")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "output": stdout.decode().strip()}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}
