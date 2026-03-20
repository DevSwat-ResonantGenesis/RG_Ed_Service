"""ED Service database models."""

from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from .db import Base


class ExecutionSession(Base):
    """A code execution session/sandbox."""
    __tablename__ = "execution_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    agent_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    workspace_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    
    name = Column(String(255), nullable=True)
    language = Column(String(32), default="python")
    status = Column(String(32), default="pending")  # pending, running, completed, failed, timeout
    
    container_id = Column(String(128), nullable=True)
    sandbox_config = Column(JSON, nullable=True)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    exit_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExecutionLog(Base):
    """Logs from code execution."""
    __tablename__ = "execution_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    stream = Column(String(16), default="stdout")  # stdout, stderr, system
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Workspace(Base):
    """Virtual file system workspace."""
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    agent_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    root_path = Column(String(512), nullable=False)
    
    settings = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WorkspaceFile(Base):
    """Files in a workspace."""
    __tablename__ = "workspace_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    
    path = Column(String(1024), nullable=False)  # Relative path within workspace
    name = Column(String(255), nullable=False)
    extension = Column(String(32), nullable=True)
    
    content_hash = Column(String(64), nullable=True)  # SHA-256
    size_bytes = Column(Integer, default=0)
    
    is_directory = Column(Boolean, default=False)
    parent_id = Column(UUID(as_uuid=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentInstance(Base):
    """Running agent instances."""
    __tablename__ = "agent_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_definition_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    user_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    workspace_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    
    name = Column(String(255), nullable=False)
    status = Column(String(32), default="idle")  # idle, thinking, executing, waiting, error
    
    current_task = Column(Text, nullable=True)
    context = Column(JSON, nullable=True)  # Agent's working memory
    
    tools_enabled = Column(JSON, nullable=True)  # List of enabled tool IDs
    
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    total_actions = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AgentAction(Base):
    """Actions taken by agents."""
    __tablename__ = "agent_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), index=True, nullable=False)
    session_id = Column(UUID(as_uuid=True), index=True, nullable=True)
    
    action_type = Column(String(64), nullable=False)  # execute_code, read_file, write_file, search, etc.
    tool_name = Column(String(128), nullable=True)
    
    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)
    
    status = Column(String(32), default="pending")  # pending, running, completed, failed
    error_message = Column(Text, nullable=True)
    
    duration_ms = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ToolDefinition(Base):
    """Registered tools available to agents."""
    __tablename__ = "tool_definitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    name = Column(String(128), unique=True, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(64), nullable=True)  # code, file, search, api, etc.
    
    parameters_schema = Column(JSON, nullable=True)  # JSON Schema for parameters
    returns_schema = Column(JSON, nullable=True)  # JSON Schema for return value
    
    handler_type = Column(String(32), default="builtin")  # builtin, plugin, remote
    handler_config = Column(JSON, nullable=True)
    
    is_enabled = Column(Boolean, default=True)
    requires_approval = Column(Boolean, default=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
