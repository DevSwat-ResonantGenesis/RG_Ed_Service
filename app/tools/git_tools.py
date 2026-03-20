"""Git operations tools for autonomous agents."""

import asyncio
import os
import shutil
from typing import Any, Dict, List, Optional

from .registry import tool_registry, ToolParameter


def register_git_tools():
    """Register all Git operation tools."""

    @tool_registry.register(
        name="git_clone",
        description="Clone a Git repository",
        category="git",
        parameters=[
            ToolParameter("url", "string", "Repository URL to clone"),
            ToolParameter("path", "string", "Local path to clone into"),
            ToolParameter("branch", "string", "Branch to checkout", required=False),
            ToolParameter("depth", "integer", "Shallow clone depth", required=False),
        ],
        returns="Clone result with path",
        requires_approval=True,
    )
    async def git_clone(
        url: str,
        path: str,
        branch: Optional[str] = None,
        depth: Optional[int] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "clone"]
            if branch:
                cmd.extend(["-b", branch])
            if depth:
                cmd.extend(["--depth", str(depth)])
            cmd.extend([url, path])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {
                    "success": True,
                    "path": path,
                    "message": stdout.decode().strip(),
                }
            return {
                "success": False,
                "error": stderr.decode().strip(),
                "exit_code": proc.returncode,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_status",
        description="Get Git repository status",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
        ],
        returns="Git status output",
    )
    async def git_status(
        path: str,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "status", "--porcelain", "-b",
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                lines = stdout.decode().strip().split("\n")
                branch = lines[0] if lines else "unknown"
                changes = lines[1:] if len(lines) > 1 else []
                
                return {
                    "success": True,
                    "branch": branch.replace("## ", ""),
                    "changes": changes,
                    "is_clean": len(changes) == 0,
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_add",
        description="Stage files for commit",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("files", "array", "Files to stage (use '.' for all)"),
        ],
        returns="Add result",
    )
    async def git_add(
        path: str,
        files: List[str],
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "add"] + files
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "files_staged": files}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_commit",
        description="Commit staged changes",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("message", "string", "Commit message"),
            ToolParameter("author", "string", "Author name and email", required=False),
        ],
        returns="Commit result with hash",
        requires_approval=True,
    )
    async def git_commit(
        path: str,
        message: str,
        author: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "commit", "-m", message]
            if author:
                cmd.extend(["--author", author])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                # Get commit hash
                hash_proc = await asyncio.create_subprocess_exec(
                    "git", "rev-parse", "HEAD",
                    cwd=path,
                    stdout=asyncio.subprocess.PIPE,
                )
                hash_out, _ = await hash_proc.communicate()
                
                return {
                    "success": True,
                    "commit_hash": hash_out.decode().strip(),
                    "message": message,
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_push",
        description="Push commits to remote",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("remote", "string", "Remote name", required=False, default="origin"),
            ToolParameter("branch", "string", "Branch to push", required=False),
            ToolParameter("force", "boolean", "Force push", required=False, default=False),
        ],
        returns="Push result",
        requires_approval=True,
    )
    async def git_push(
        path: str,
        remote: str = "origin",
        branch: Optional[str] = None,
        force: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "push", remote]
            if branch:
                cmd.append(branch)
            if force:
                cmd.append("--force")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "remote": remote, "branch": branch}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_pull",
        description="Pull changes from remote",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("remote", "string", "Remote name", required=False, default="origin"),
            ToolParameter("branch", "string", "Branch to pull", required=False),
        ],
        returns="Pull result",
    )
    async def git_pull(
        path: str,
        remote: str = "origin",
        branch: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "pull", remote]
            if branch:
                cmd.append(branch)

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

    @tool_registry.register(
        name="git_diff",
        description="Get diff of changes",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("staged", "boolean", "Show staged changes", required=False, default=False),
            ToolParameter("file", "string", "Specific file to diff", required=False),
        ],
        returns="Diff output",
    )
    async def git_diff(
        path: str,
        staged: bool = False,
        file: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--staged")
            if file:
                cmd.extend(["--", file])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {
                    "success": True,
                    "diff": stdout.decode()[:50000],  # Limit size
                    "has_changes": len(stdout) > 0,
                }
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_checkout",
        description="Checkout a branch or file",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("target", "string", "Branch name or commit hash"),
            ToolParameter("create", "boolean", "Create new branch", required=False, default=False),
        ],
        returns="Checkout result",
    )
    async def git_checkout(
        path: str,
        target: str,
        create: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "checkout"]
            if create:
                cmd.append("-b")
            cmd.append(target)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "branch": target, "created": create}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_log",
        description="Get commit history",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("limit", "integer", "Number of commits", required=False, default=10),
            ToolParameter("oneline", "boolean", "One line per commit", required=False, default=True),
        ],
        returns="Commit log",
    )
    async def git_log(
        path: str,
        limit: int = 10,
        oneline: bool = True,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "log", f"-{limit}"]
            if oneline:
                cmd.append("--oneline")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                commits = stdout.decode().strip().split("\n")
                return {"success": True, "commits": commits, "count": len(commits)}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_apply_patch",
        description="Apply a patch file or diff",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("patch", "string", "Patch content or file path"),
            ToolParameter("check", "boolean", "Only check if patch applies", required=False, default=False),
        ],
        returns="Apply result",
        requires_approval=True,
    )
    async def git_apply_patch(
        path: str,
        patch: str,
        check: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "apply"]
            if check:
                cmd.append("--check")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate(input=patch.encode())

            if proc.returncode == 0:
                return {"success": True, "applied": not check, "checked": check}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="git_stash",
        description="Stash or restore changes",
        category="git",
        parameters=[
            ToolParameter("path", "string", "Repository path"),
            ToolParameter("action", "string", "Action: push, pop, list, drop"),
            ToolParameter("message", "string", "Stash message for push", required=False),
        ],
        returns="Stash result",
    )
    async def git_stash(
        path: str,
        action: str = "push",
        message: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["git", "stash", action]
            if action == "push" and message:
                cmd.extend(["-m", message])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                return {"success": True, "action": action, "output": stdout.decode().strip()}
            return {"success": False, "error": stderr.decode().strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}
