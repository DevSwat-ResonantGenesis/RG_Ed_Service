# RG Ed Service

> **Part of the [ResonantGenesis](https://dev-swat.com) platform** — Execution Director service for orchestrating agent tool execution.

[![Status: Production](https://img.shields.io/badge/Status-Production-brightgreen.svg)]()
[![Port: 8000](https://img.shields.io/badge/Port-8000-orange.svg)]()
[![Database: PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-336791.svg)]()
[![License: RG Source Available](https://img.shields.io/badge/License-RG%20Source%20Available-blue.svg)](LICENSE.txt)

Execution Director — orchestrates agent tool execution including builtin tools, git operations, Docker container management, and test execution. Manages sandboxed environments with filesystem access and WebSocket communication.

## Features

- **Builtin tools** — File operations, search, code analysis
- **Git tools** — Clone, commit, push, branch management
- **Docker tools** — Container lifecycle management
- **Test tools** — Test execution and result reporting
- **WebSocket** — Real-time execution status updates
- **Sandbox** — Isolated execution environments

## Quick Start

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Deployment Status

- **Extracted from**: `genesis2026_production_backend/ed_service/`
- **Server path**: `/home/deploy/RG_Ed_Service`
- **Docker service**: `ed_service`

---
**Organization**: [DevSwat-ResonantGenesis](https://github.com/DevSwat-ResonantGenesis) | **Platform**: [dev-swat.com](https://dev-swat.com)
