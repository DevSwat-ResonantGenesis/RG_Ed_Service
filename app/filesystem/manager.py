"""File system manager for workspaces."""

import asyncio
import hashlib
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import aiofiles
import aiofiles.os

from ..config import settings


@dataclass
class FileInfo:
    """Information about a file."""
    path: str
    name: str
    extension: Optional[str]
    size_bytes: int
    is_directory: bool
    content_hash: Optional[str]
    created_at: Optional[datetime]
    modified_at: Optional[datetime]


@dataclass
class FileContent:
    """File content with metadata."""
    path: str
    content: str
    encoding: str = "utf-8"
    size_bytes: int = 0
    content_hash: Optional[str] = None


class FileSystemManager:
    """Manages virtual file systems for workspaces."""

    def __init__(self):
        self.workspace_root = Path(settings.WORKSPACE_ROOT)
        self.max_file_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        self.allowed_extensions = set(settings.ALLOWED_EXTENSIONS.split(","))

    async def init_workspace(self, workspace_id: str) -> Path:
        """Initialize a new workspace directory."""
        workspace_path = self.workspace_root / workspace_id
        await aiofiles.os.makedirs(workspace_path, exist_ok=True)
        return workspace_path

    async def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace and all its contents."""
        workspace_path = self.workspace_root / workspace_id
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
            return True
        return False

    def _get_full_path(self, workspace_id: str, relative_path: str) -> Path:
        """Get full path and validate it's within workspace."""
        workspace_path = self.workspace_root / workspace_id
        full_path = (workspace_path / relative_path).resolve()
        
        # Security: ensure path is within workspace
        if not str(full_path).startswith(str(workspace_path.resolve())):
            raise ValueError("Path traversal detected")
        
        return full_path

    def _validate_extension(self, filename: str) -> bool:
        """Check if file extension is allowed."""
        ext = Path(filename).suffix.lower()
        return ext in self.allowed_extensions or not self.allowed_extensions

    async def read_file(
        self, workspace_id: str, path: str
    ) -> Optional[FileContent]:
        """Read a file from workspace."""
        try:
            full_path = self._get_full_path(workspace_id, path)
            
            if not full_path.exists() or full_path.is_dir():
                return None

            async with aiofiles.open(full_path, "r", encoding="utf-8") as f:
                content = await f.read()

            stat = full_path.stat()
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            return FileContent(
                path=path,
                content=content,
                size_bytes=stat.st_size,
                content_hash=content_hash,
            )
        except Exception as e:
            return None

    async def write_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
        create_dirs: bool = True,
    ) -> Tuple[bool, Optional[str]]:
        """Write content to a file."""
        try:
            if not self._validate_extension(path):
                return False, f"File extension not allowed"

            if len(content.encode()) > self.max_file_size:
                return False, f"File exceeds maximum size of {settings.MAX_FILE_SIZE_MB}MB"

            full_path = self._get_full_path(workspace_id, path)

            if create_dirs:
                await aiofiles.os.makedirs(full_path.parent, exist_ok=True)

            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)

            return True, None
        except Exception as e:
            return False, str(e)

    async def delete_file(
        self, workspace_id: str, path: str
    ) -> Tuple[bool, Optional[str]]:
        """Delete a file from workspace."""
        try:
            full_path = self._get_full_path(workspace_id, path)
            
            if not full_path.exists():
                return False, "File not found"

            if full_path.is_dir():
                shutil.rmtree(full_path)
            else:
                full_path.unlink()

            return True, None
        except Exception as e:
            return False, str(e)

    async def move_file(
        self,
        workspace_id: str,
        source_path: str,
        dest_path: str,
    ) -> Tuple[bool, Optional[str]]:
        """Move/rename a file."""
        try:
            source = self._get_full_path(workspace_id, source_path)
            dest = self._get_full_path(workspace_id, dest_path)

            if not source.exists():
                return False, "Source file not found"

            await aiofiles.os.makedirs(dest.parent, exist_ok=True)
            shutil.move(str(source), str(dest))

            return True, None
        except Exception as e:
            return False, str(e)

    async def copy_file(
        self,
        workspace_id: str,
        source_path: str,
        dest_path: str,
    ) -> Tuple[bool, Optional[str]]:
        """Copy a file."""
        try:
            source = self._get_full_path(workspace_id, source_path)
            dest = self._get_full_path(workspace_id, dest_path)

            if not source.exists():
                return False, "Source file not found"

            await aiofiles.os.makedirs(dest.parent, exist_ok=True)

            if source.is_dir():
                shutil.copytree(str(source), str(dest))
            else:
                shutil.copy2(str(source), str(dest))

            return True, None
        except Exception as e:
            return False, str(e)

    async def list_directory(
        self,
        workspace_id: str,
        path: str = "",
        recursive: bool = False,
    ) -> List[FileInfo]:
        """List files in a directory."""
        try:
            full_path = self._get_full_path(workspace_id, path)
            
            if not full_path.exists():
                return []

            files = []
            
            if recursive:
                for item in full_path.rglob("*"):
                    files.append(await self._get_file_info(workspace_id, item))
            else:
                for item in full_path.iterdir():
                    files.append(await self._get_file_info(workspace_id, item))

            return files
        except Exception:
            return []

    async def _get_file_info(self, workspace_id: str, path: Path) -> FileInfo:
        """Get file information."""
        workspace_path = self.workspace_root / workspace_id
        relative_path = str(path.relative_to(workspace_path))
        stat = path.stat()

        content_hash = None
        if path.is_file() and stat.st_size < 1024 * 1024:  # Hash files < 1MB
            try:
                async with aiofiles.open(path, "rb") as f:
                    content = await f.read()
                    content_hash = hashlib.sha256(content).hexdigest()
            except:
                pass

        return FileInfo(
            path=relative_path,
            name=path.name,
            extension=path.suffix.lower() if path.suffix else None,
            size_bytes=stat.st_size,
            is_directory=path.is_dir(),
            content_hash=content_hash,
            created_at=datetime.fromtimestamp(stat.st_ctime),
            modified_at=datetime.fromtimestamp(stat.st_mtime),
        )

    async def search_files(
        self,
        workspace_id: str,
        pattern: str,
        path: str = "",
    ) -> List[FileInfo]:
        """Search for files matching a pattern."""
        try:
            full_path = self._get_full_path(workspace_id, path)
            
            if not full_path.exists():
                return []

            files = []
            for item in full_path.rglob(pattern):
                files.append(await self._get_file_info(workspace_id, item))

            return files
        except Exception:
            return []

    async def search_content(
        self,
        workspace_id: str,
        query: str,
        path: str = "",
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """Search file contents for a string."""
        try:
            full_path = self._get_full_path(workspace_id, path)
            
            if not full_path.exists():
                return []

            results = []
            workspace_path = self.workspace_root / workspace_id

            for item in full_path.rglob("*"):
                if item.is_file() and item.stat().st_size < self.max_file_size:
                    try:
                        async with aiofiles.open(item, "r", encoding="utf-8") as f:
                            content = await f.read()
                            
                        lines = content.split("\n")
                        for i, line in enumerate(lines):
                            if query.lower() in line.lower():
                                results.append({
                                    "path": str(item.relative_to(workspace_path)),
                                    "line_number": i + 1,
                                    "line": line.strip(),
                                    "match": query,
                                })
                                
                                if len(results) >= max_results:
                                    return results
                    except:
                        continue

            return results
        except Exception:
            return []

    async def get_file_tree(
        self, workspace_id: str, max_depth: int = 5
    ) -> Dict[str, Any]:
        """Get file tree structure."""
        workspace_path = self.workspace_root / workspace_id
        
        if not workspace_path.exists():
            return {"name": workspace_id, "type": "directory", "children": []}

        return await self._build_tree(workspace_path, workspace_path, max_depth)

    async def _build_tree(
        self, path: Path, root: Path, max_depth: int, current_depth: int = 0
    ) -> Dict[str, Any]:
        """Recursively build file tree."""
        node = {
            "name": path.name,
            "path": str(path.relative_to(root)) if path != root else "",
            "type": "directory" if path.is_dir() else "file",
        }

        if path.is_dir() and current_depth < max_depth:
            children = []
            try:
                for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
                    children.append(
                        await self._build_tree(item, root, max_depth, current_depth + 1)
                    )
            except PermissionError:
                pass
            node["children"] = children
        elif path.is_file():
            node["size"] = path.stat().st_size
            node["extension"] = path.suffix.lower() if path.suffix else None

        return node


fs_manager = FileSystemManager()
