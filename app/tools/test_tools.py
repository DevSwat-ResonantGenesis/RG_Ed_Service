"""Testing tools for autonomous agents - pytest, jest, linting, coverage."""

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

from .registry import tool_registry, ToolParameter


def register_test_tools():
    """Register all testing tools."""

    @tool_registry.register(
        name="run_pytest",
        description="Run Python tests with pytest",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to test file or directory"),
            ToolParameter("pattern", "string", "Test pattern to match", required=False),
            ToolParameter("verbose", "boolean", "Verbose output", required=False, default=True),
            ToolParameter("coverage", "boolean", "Run with coverage", required=False, default=False),
            ToolParameter("markers", "string", "Pytest markers to filter", required=False),
            ToolParameter("timeout", "integer", "Test timeout in seconds", required=False, default=300),
        ],
        returns="Test results with pass/fail counts",
    )
    async def run_pytest(
        path: str,
        pattern: Optional[str] = None,
        verbose: bool = True,
        coverage: bool = False,
        markers: Optional[str] = None,
        timeout: int = 300,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["python", "-m", "pytest"]
            
            if verbose:
                cmd.append("-v")
            
            if coverage:
                cmd.extend(["--cov", "--cov-report=json"])
            
            if pattern:
                cmd.extend(["-k", pattern])
            
            if markers:
                cmd.extend(["-m", markers])
            
            # JSON output for parsing
            cmd.extend(["--tb=short", "-q", "--no-header"])
            cmd.append(path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"Tests timed out after {timeout}s"}

            output = stdout.decode()
            
            # Parse results
            passed = output.count(" passed")
            failed = output.count(" failed")
            errors = output.count(" error")
            skipped = output.count(" skipped")
            
            return {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "skipped": skipped,
                "output": output[-10000:],
                "stderr": stderr.decode()[-2000:] if stderr else "",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="run_jest",
        description="Run JavaScript/TypeScript tests with Jest",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to test file or directory"),
            ToolParameter("pattern", "string", "Test pattern to match", required=False),
            ToolParameter("coverage", "boolean", "Run with coverage", required=False, default=False),
            ToolParameter("watch", "boolean", "Watch mode (not recommended for agents)", required=False, default=False),
            ToolParameter("timeout", "integer", "Test timeout in seconds", required=False, default=300),
        ],
        returns="Test results with pass/fail counts",
    )
    async def run_jest(
        path: str,
        pattern: Optional[str] = None,
        coverage: bool = False,
        watch: bool = False,
        timeout: int = 300,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            cmd = ["npx", "jest", "--json"]
            
            if coverage:
                cmd.append("--coverage")
            
            if pattern:
                cmd.extend(["-t", pattern])
            
            if not watch:
                cmd.append("--watchAll=false")
            
            cmd.append(path)

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"Tests timed out after {timeout}s"}

            output = stdout.decode()
            
            # Try to parse JSON output
            try:
                # Jest outputs JSON to stdout
                results = json.loads(output)
                return {
                    "success": results.get("success", False),
                    "numPassedTests": results.get("numPassedTests", 0),
                    "numFailedTests": results.get("numFailedTests", 0),
                    "numPendingTests": results.get("numPendingTests", 0),
                    "numTotalTests": results.get("numTotalTests", 0),
                    "testResults": [
                        {
                            "name": r.get("name"),
                            "status": r.get("status"),
                            "message": r.get("message", "")[:500],
                        }
                        for r in results.get("testResults", [])[:20]
                    ],
                }
            except json.JSONDecodeError:
                return {
                    "success": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "output": output[-10000:],
                    "stderr": stderr.decode()[-2000:],
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="run_npm_test",
        description="Run npm test script",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to project directory"),
            ToolParameter("script", "string", "Test script name", required=False, default="test"),
            ToolParameter("timeout", "integer", "Timeout in seconds", required=False, default=300),
        ],
        returns="Test output",
    )
    async def run_npm_test(
        path: str,
        script: str = "test",
        timeout: int = 300,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "npm", "run", script, "--", "--watchAll=false",
                cwd=path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "CI": "true"},
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"Tests timed out after {timeout}s"}

            return {
                "success": proc.returncode == 0,
                "exit_code": proc.returncode,
                "output": stdout.decode()[-10000:],
                "stderr": stderr.decode()[-2000:],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="run_linter",
        description="Run code linter (eslint, flake8, ruff, etc.)",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to file or directory"),
            ToolParameter("linter", "string", "Linter to use: eslint, flake8, ruff, pylint, mypy"),
            ToolParameter("fix", "boolean", "Auto-fix issues", required=False, default=False),
            ToolParameter("config", "string", "Config file path", required=False),
        ],
        returns="Linting results with issues",
    )
    async def run_linter(
        path: str,
        linter: str = "ruff",
        fix: bool = False,
        config: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            if linter == "eslint":
                cmd = ["npx", "eslint", "--format=json"]
                if fix:
                    cmd.append("--fix")
                if config:
                    cmd.extend(["-c", config])
                cmd.append(path)
            
            elif linter == "flake8":
                cmd = ["python", "-m", "flake8", "--format=json"]
                if config:
                    cmd.extend(["--config", config])
                cmd.append(path)
            
            elif linter == "ruff":
                cmd = ["ruff", "check", "--output-format=json"]
                if fix:
                    cmd.append("--fix")
                if config:
                    cmd.extend(["--config", config])
                cmd.append(path)
            
            elif linter == "pylint":
                cmd = ["python", "-m", "pylint", "--output-format=json"]
                if config:
                    cmd.extend(["--rcfile", config])
                cmd.append(path)
            
            elif linter == "mypy":
                cmd = ["python", "-m", "mypy", "--show-error-codes"]
                if config:
                    cmd.extend(["--config-file", config])
                cmd.append(path)
            
            else:
                return {"success": False, "error": f"Unknown linter: {linter}"}

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=120,
            )

            output = stdout.decode()
            
            # Try to parse JSON
            try:
                issues = json.loads(output)
                issue_count = len(issues) if isinstance(issues, list) else 0
            except json.JSONDecodeError:
                issues = output
                issue_count = output.count("\n")

            return {
                "success": proc.returncode == 0,
                "linter": linter,
                "issue_count": issue_count,
                "issues": issues if isinstance(issues, list) else output[-10000:],
                "fixed": fix and proc.returncode == 0,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Linting timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="run_type_check",
        description="Run type checker (mypy for Python, tsc for TypeScript)",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to file or directory"),
            ToolParameter("language", "string", "Language: python or typescript"),
            ToolParameter("strict", "boolean", "Strict mode", required=False, default=False),
        ],
        returns="Type checking results",
    )
    async def run_type_check(
        path: str,
        language: str = "python",
        strict: bool = False,
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            if language == "python":
                cmd = ["python", "-m", "mypy"]
                if strict:
                    cmd.append("--strict")
                cmd.append(path)
            
            elif language == "typescript":
                cmd = ["npx", "tsc", "--noEmit"]
                if strict:
                    cmd.append("--strict")
                # For single file, need to handle differently
                if path.endswith(".ts") or path.endswith(".tsx"):
                    cmd.append(path)
            
            else:
                return {"success": False, "error": f"Unknown language: {language}"}

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=120,
            )

            output = stdout.decode() + stderr.decode()
            error_count = output.count("error:")

            return {
                "success": proc.returncode == 0,
                "language": language,
                "error_count": error_count,
                "output": output[-10000:],
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": "Type checking timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="get_coverage_report",
        description="Get code coverage report",
        category="testing",
        parameters=[
            ToolParameter("path", "string", "Path to project directory"),
            ToolParameter("format", "string", "Report format: json, html, text", required=False, default="json"),
        ],
        returns="Coverage report data",
    )
    async def get_coverage_report(
        path: str,
        format: str = "json",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            # Check for Python coverage
            coverage_json = os.path.join(path, "coverage.json")
            coverage_xml = os.path.join(path, "coverage.xml")
            htmlcov = os.path.join(path, "htmlcov")
            
            if os.path.exists(coverage_json):
                with open(coverage_json, "r") as f:
                    data = json.load(f)
                    return {
                        "success": True,
                        "type": "python",
                        "total_coverage": data.get("totals", {}).get("percent_covered", 0),
                        "files": len(data.get("files", {})),
                        "data": data.get("totals", {}),
                    }
            
            # Check for Jest coverage
            jest_coverage = os.path.join(path, "coverage", "coverage-summary.json")
            if os.path.exists(jest_coverage):
                with open(jest_coverage, "r") as f:
                    data = json.load(f)
                    total = data.get("total", {})
                    return {
                        "success": True,
                        "type": "jest",
                        "lines": total.get("lines", {}).get("pct", 0),
                        "statements": total.get("statements", {}).get("pct", 0),
                        "functions": total.get("functions", {}).get("pct", 0),
                        "branches": total.get("branches", {}).get("pct", 0),
                    }
            
            return {
                "success": False,
                "error": "No coverage report found. Run tests with --coverage first.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    @tool_registry.register(
        name="validate_code_syntax",
        description="Validate code syntax without executing",
        category="testing",
        parameters=[
            ToolParameter("code", "string", "Code to validate"),
            ToolParameter("language", "string", "Language: python, javascript, typescript"),
        ],
        returns="Validation result with any syntax errors",
    )
    async def validate_code_syntax(
        code: str,
        language: str = "python",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        try:
            if language == "python":
                import ast
                try:
                    ast.parse(code)
                    return {"success": True, "valid": True, "language": "python"}
                except SyntaxError as e:
                    return {
                        "success": True,
                        "valid": False,
                        "language": "python",
                        "error": str(e),
                        "line": e.lineno,
                        "offset": e.offset,
                    }
            
            elif language in ["javascript", "typescript"]:
                # Use node to check syntax
                cmd = ["node", "--check"]
                if language == "typescript":
                    cmd = ["npx", "tsc", "--noEmit", "--allowJs"]
                
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate(input=code.encode())
                
                if proc.returncode == 0:
                    return {"success": True, "valid": True, "language": language}
                return {
                    "success": True,
                    "valid": False,
                    "language": language,
                    "error": stderr.decode()[:1000],
                }
            
            return {"success": False, "error": f"Unknown language: {language}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
