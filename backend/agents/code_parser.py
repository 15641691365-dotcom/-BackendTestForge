"""
CodeParser Agent — Step A: Directory scanning and tech stack detection.

Strategy A reads the project directory tree (filenames only, no content),
then infers the tech stack and backend location from file patterns.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directories to exclude from scanning
EXCLUDED_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "env",
    ".env", "dist", "build", ".next", ".nuxt", "target", "bin",
    "obj", "vendor", ".idea", ".vscode", ".DS_Store", "logs",
    ".npm", ".yarn", ".cache", "tmp", "temp",
}

# File extensions to exclude (binary/media)
EXCLUDED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".mp4", ".mp3", ".avi", ".mov", ".zip", ".tar",
    ".gz", ".bz2", ".7z", ".rar", ".pdf", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".exe", ".dll", ".so", ".dylib",
    ".o", ".a", ".class", ".jar", ".war",
}

# Configuration files that reveal tech stack
TECH_STACK_INDICATORS = {
    "requirements.txt": "Python",
    "setup.py": "Python",
    "setup.cfg": "Python",
    "pyproject.toml": "Python",
    "Pipfile": "Python",
    "package.json": "Node.js",
    "yarn.lock": "Node.js",
    "pnpm-lock.yaml": "Node.js",
    "pom.xml": "Java/Maven",
    "build.gradle": "Java/Gradle",
    "build.gradle.kts": "Java/Gradle",
    "go.mod": "Go",
    "go.sum": "Go",
    "Cargo.toml": "Rust",
    "Cargo.lock": "Rust",
    "composer.json": "PHP",
    "Gemfile": "Ruby",
    "mix.exs": "Elixir",
    "Project.toml": "Julia",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "Makefile": "Make",
}

# Framework-level indicators (files/dirs that suggest specific frameworks)
FRAMEWORK_INDICATORS = {
    "routers": {"patterns": [r"routers?", r"routes?", r"controllers?", r"views?", r"endpoints?"]},
    "models": {"patterns": [r"models?", r"entities?", r"schemas?", r"types?"]},
    "services": {"patterns": [r"services?", r"usecases?", r"business?", r"logic?"]},
    "middleware": {"patterns": [r"middleware", r"middlewares"]},
}


def read_directory_tree(project_path: str, max_dirs: int = 200) -> dict:
    """
    Scans the project directory structure.
    Returns a nested dict representing the directory tree.
    Only filenames and paths — no file contents read.
    """
    root = Path(project_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Project path does not exist: {project_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Project path is not a directory: {project_path}")

    tree = _scan_dir(root, root, depth=0, max_depth=4, max_dirs=max_dirs)
    return tree


def _scan_dir(
    base: Path,
    current: Path,
    depth: int = 0,
    max_depth: int = 4,
    max_dirs: int = 200,
    count: Optional[list] = None,
) -> dict:
    """Recursively scan a directory, returning a tree structure."""
    if count is None:
        count = [0]
    if count[0] > max_dirs:
        return {"_truncated": True}

    result = {}
    try:
        entries = sorted(current.iterdir(), key=lambda x: (x.is_file(), x.name))
    except PermissionError:
        return {"_error": "permission_denied"}

    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env", ".gitignore"):
            continue
        if entry.name in EXCLUDED_DIRS:
            continue
        if entry.suffix.lower() in EXCLUDED_EXTENSIONS:
            continue

        rel_path = str(entry.relative_to(base))
        if entry.is_dir():
            if depth < max_depth:
                count[0] += 1
                subtree = _scan_dir(base, entry, depth + 1, max_depth, max_dirs, count)
                if subtree:  # only include non-empty dirs
                    result[entry.name] = subtree
        elif entry.is_file():
            # Include file with metadata
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            result[entry.name] = {"_type": "file", "_size": size}

    return result


def detect_tech_stack(directory_tree: dict, project_path: str) -> dict:
    """
    Analyze the directory tree and project files to identify the tech stack.
    Returns a structured tech stack description.
    """
    tech_stack = {
        "language": None,
        "framework": None,
        "web_server": None,
        "database": None,
        "detected_by": [],
        "confidence": "low",  # high / medium / low
        "entry_point": None,
        "backend_dir": None,
    }

    # Step 1: Check for configuration files in the project root
    root = Path(project_path)
    config_files_found = _find_config_files(root)

    for cfg_file, language in TECH_STACK_INDICATORS.items():
        if cfg_file in config_files_found:
            tech_stack["language"] = _refine_language(language, cfg_file)
            tech_stack["detected_by"].append(f"config_file:{cfg_file}")

    # Step 2: Parse config files for more detail
    if "package.json" in config_files_found:
        _analyze_package_json(root / "package.json", tech_stack)
    if "requirements.txt" in config_files_found or "Pipfile" in config_files_found or "pyproject.toml" in config_files_found:
        _analyze_python_deps(root, tech_stack)
    if "pom.xml" in config_files_found:
        tech_stack["web_server"] = "Tomcat"
    if "go.mod" in config_files_found:
        _analyze_go_mod(root / "go.mod", tech_stack)

    # Step 3: Find backend directory from directory structure
    backend_dir = _find_backend_dir(directory_tree)
    if backend_dir:
        tech_stack["backend_dir"] = backend_dir
        tech_stack["detected_by"].append("dir_structure")

    # Step 4: Find entry point
    entry_point = _find_entry_point(root, tech_stack.get("language"))
    if entry_point:
        tech_stack["entry_point"] = entry_point
        tech_stack["detected_by"].append("entry_point")

    # Determine confidence
    if tech_stack["language"] and tech_stack["entry_point"]:
        tech_stack["confidence"] = "high"
    elif tech_stack["language"]:
        tech_stack["confidence"] = "medium"

    return tech_stack


def _find_config_files(root: Path) -> set:
    """Find configuration files in the project root (depth 0-2)."""
    found = set()
    for depth in range(3):
        if depth == 0:
            search_paths = [root]
        elif depth == 1:
            search_paths = list(root.iterdir()) if root.is_dir() else []
            search_paths = [p for p in search_paths if p.is_dir() and p.name not in EXCLUDED_DIRS]
        else:
            break

        for path in search_paths:
            if path.is_file() and path.name in TECH_STACK_INDICATORS:
                found.add(path.name)
            elif path.is_dir():
                try:
                    for f in path.iterdir():
                        if f.is_file() and f.name in TECH_STACK_INDICATORS:
                            found.add(f.name)
                except PermissionError:
                    continue
    return found


def _refine_language(language: str, config_file: str) -> str:
    """Refine language detection from config file name."""
    mapping = {
        "Python": "Python",
        "Node.js": "JavaScript",
        "Java/Maven": "Java",
        "Java/Gradle": "Java",
        "Go": "Go",
        "Rust": "Rust",
        "PHP": "PHP",
        "Ruby": "Ruby",
        "Elixir": "Elixir",
    }
    for key, val in mapping.items():
        if key in language:
            return val
    return language


def _analyze_package_json(pkg_path: Path, tech_stack: dict) -> None:
    """Parse package.json for framework info."""
    try:
        with open(pkg_path) as f:
            import json as _json
            data = _json.load(f)

        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        deps_lower = {k.lower(): v for k, v in deps.items()}

        framework_map = {
            "express": ("Express", "node"),
            "fastify": ("Fastify", "node"),
            "koa": ("Koa", "node"),
            "nestjs": ("NestJS", "node"),
            "next": ("Next.js", "node"),
            "nuxt": ("Nuxt.js", "node"),
            "@nestjs/core": ("NestJS", "node"),
        }

        for dep, (fw, server) in framework_map.items():
            if dep in deps_lower or dep in deps:
                tech_stack["framework"] = fw
                tech_stack["web_server"] = server

        scripts = data.get("scripts", {})
        if "start" in scripts:
            tech_stack["start_command"] = scripts["start"]

    except (json.JSONDecodeError, OSError):
        pass


def _analyze_python_deps(root: Path, tech_stack: dict) -> None:
    """Scan Python dependency files for framework info. Searches root and common subdirs."""
    framework_keywords = {
        "fastapi": ("FastAPI", "uvicorn"),
        "flask": ("Flask", "gunicorn/werkzeug"),
        "django": ("Django", "gunicorn/uwsgi"),
        "aiohttp": ("aiohttp", "aiohttp"),
        "tornado": ("Tornado", "tornado"),
        "starlette": ("Starlette", "uvicorn"),
        "sanic": ("Sanic", "sanic"),
        "bottle": ("Bottle", "bottle"),
        "quart": ("Quart", "hypercorn"),
    }

    req_files = ["requirements.txt", "Pipfile", "pyproject.toml"]
    # Search root and common subdirectories
    search_dirs = [root] + [root / d for d in ["backend", "server", "api", "app", "src"] if (root / d).is_dir()]

    for search_dir in search_dirs:
        for req_file in req_files:
            fpath = search_dir / req_file
            if not fpath.exists():
                continue
            try:
                content = fpath.read_text().lower()
                for keyword, (fw, server) in framework_keywords.items():
                    if keyword in content:
                        tech_stack["framework"] = fw
                        tech_stack["web_server"] = server
                        return  # Found framework, stop
            except OSError:
                continue


def _analyze_go_mod(mod_path: Path, tech_stack: dict) -> None:
    """Parse go.mod for framework info."""
    try:
        content = mod_path.read_text().lower()
        framework_map = {
            "gin": ("Gin", "gin"),
            "echo": ("Echo", "echo"),
            "fiber": ("Fiber", "fiber"),
            "chi": ("Chi", "chi"),
            "mux": ("gorilla/mux", "net/http"),
            "beego": ("Beego", "beego"),
        }
        for keyword, (fw, server) in framework_map.items():
            if keyword in content:
                tech_stack["framework"] = fw
                tech_stack["web_server"] = server
                break
    except OSError:
        pass


def _find_backend_dir(tree: dict) -> Optional[str]:
    """
    Look through the directory tree for backend-related directories.
    Returns the relative path of the most likely backend dir.
    """
    # Priority-ordered backend directory names
    backend_names = [
        "backend", "server", "api", "app", "src",
        "service", "services", "rest", "graphql",
    ]

    for name in backend_names:
        if name in tree and isinstance(tree[name], dict):
            return name

    return None


def _find_entry_point(root: Path, language: Optional[str]) -> Optional[str]:
    """Find the application entry point file."""
    entry_patterns = []

    if language == "Python":
        entry_patterns = ["main.py", "app.py", "run.py", "server.py", "api.py", "__main__.py"]
    elif language in ("JavaScript", "TypeScript"):
        # Check package.json for main field
        pkg = root / "package.json"
        if pkg.exists():
            try:
                import json as _json
                data = _json.loads(pkg.read_text())
                if "main" in data:
                    return data["main"]
            except (json.JSONDecodeError, OSError):
                pass
        entry_patterns = ["index.js", "index.ts", "server.js", "server.ts", "app.js", "app.ts"]
    elif language == "Java":
        entry_patterns = ["Application.java", "Main.java", "App.java"]
    elif language == "Go":
        entry_patterns = ["main.go"]
    elif language == "Rust":
        entry_patterns = ["main.rs"]
    elif language == "PHP":
        entry_patterns = ["index.php"]
    else:
        entry_patterns = ["main.py", "app.py", "index.js", "server.js", "main.go", "main.rs"]

    # Search up to depth 3
    for depth in range(4):
        if depth == 0:
            search_dir = root
        else:
            # Search in common backend dirs
            for bd in ["backend", "server", "api", "app", "src"]:
                d = root / bd
                if d.is_dir():
                    search_dir = d
                    break
            else:
                continue

        try:
            for f in search_dir.iterdir():
                if f.is_file() and f.name in entry_patterns:
                    return str(f.relative_to(root))
        except (PermissionError, OSError):
            continue

    return None


def format_tree_for_llm(tree: dict, max_lines: int = 80) -> str:
    """Format the directory tree as a readable string for LLM consumption."""
    lines = []

    def _format(prefix: str, name: str, node, is_last: bool):
        """Recursively format tree entries."""
        if len(lines) >= max_lines:
            if not lines[-1].endswith("..."):
                lines.append(f"{'    ' * (prefix.count('│') + 1)}... (truncated)")
            return

        if isinstance(node, dict):
            if "_type" in node and node["_type"] == "file":
                size = node.get("_size", 0)
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size // 1024}KB"
                else:
                    size_str = f"{size // (1024*1024)}MB"
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{name} ({size_str})")
            elif "_error" in node:
                pass
            elif "_truncated" in node:
                lines.append(f"{prefix}└── ... (truncated)")
            else:
                connector = "└── " if is_last else "├── "
                lines.append(f"{prefix}{connector}{name}/")
                items = list(node.items())
                new_prefix = prefix + ("    " if is_last else "│   ")
                for i, (k, v) in enumerate(items):
                    _format(new_prefix, k, v, i == len(items) - 1)

    items = list(tree.items())
    for i, (k, v) in enumerate(items):
        _format("", k, v, i == len(items) - 1)

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Strategy B: grep for API route patterns
# ─────────────────────────────────────────────

def grep_api_routes(project_path: str, language: str = None) -> list[dict]:
    """
    Use grep to find route/endpoint definitions in the project.
    Returns a list of {"method": "GET", "path": "/users", "file": "routers/user.py:15"}
    """
    routes = []
    root = Path(project_path)

    # Language-specific grep patterns
    grep_patterns = []

    if language == "Python" or language is None:
        # FastAPI / Flask / Django route patterns
        grep_patterns = [
            r'@\w+\.(get|post|put|delete|patch|route)\s*\(',
            r'@\w+\.(get|post|put|delete|patch|route)\s*\([\'"]',
            r'\.add_url_rule\([\'"]',
            r'\.route\([\'"]',
            r'path\([\'"]',
            r'@app\.(get|post|put|delete|patch)\s*\(',
            r'@router\.(get|post|put|delete|patch)\s*\(',
            r'@api\.(get|post|put|delete|patch)\s*\(',
            r'@bp\.(get|post|put|delete|patch)\s*\(',
            r'include_router\(',
        ]

    elif language in ("JavaScript", "TypeScript"):
        grep_patterns = [
            r'\.(get|post|put|delete|patch)\s*\(',
            r'router\.(get|post|put|delete|patch)\s*\(',
            r'\.route\s*\(',
            r'@(Get|Post|Put|Delete|Patch)\s*\(',
        ]

    elif language == "Java":
        grep_patterns = [
            r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\s*\(',
            r'\.(get|post|put|delete|patch)\s*\(',
        ]

    elif language == "Go":
        grep_patterns = [
            r'\.(GET|POST|PUT|DELETE|PATCH)\s*\(',
            r'\.HandleFunc\(',
            r'router\.(get|post|put|delete|patch)\s*\(',
        ]

    # Determine which file types to search
    include_exts = ["*.py"]
    if language in ("JavaScript", "TypeScript"):
        include_exts = ["*.js", "*.ts", "*.jsx", "*.tsx"]
    elif language == "Java":
        include_exts = ["*.java"]
    elif language == "Go":
        include_exts = ["*.go"]
    elif language == "Rust":
        include_exts = ["*.rs"]

    # Exclude directories
    exclude_dirs = " ".join(f"--exclude-dir={d}" for d in EXCLUDED_DIRS)

    for pattern in grep_patterns:
        for ext in include_exts:
            cmd = (
                f'grep -rn --include="{ext}" {exclude_dirs} '
                f'-E \'{pattern}\' "{project_path}" 2>/dev/null | head -80'
            )
            import subprocess
            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True, timeout=10
                )
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    # Parse "file:line:content" format
                    if ":" in line:
                        parts = line.split(":", 2)
                        if len(parts) == 3:
                            file_path, line_no, content = parts
                            # Extract HTTP method
                            method = _extract_http_method(content)
                            # Extract path if possible
                            path = _extract_path(content)
                            routes.append({
                                "method": method,
                                "path": path,
                                "file": f"{file_path}:{line_no}",
                                "content_snippet": content.strip()[:120],
                            })
            except subprocess.TimeoutExpired:
                continue

    # Deduplicate by file:line
    seen = set()
    unique_routes = []
    for r in routes:
        key = r["file"]
        if key not in seen:
            seen.add(key)
            unique_routes.append(r)

    return unique_routes[:50]  # Limit to 50 routes


def _extract_http_method(content: str) -> str:
    """Extract HTTP method from route decorator/definition."""
    content_lower = content.lower()
    for method in ["post", "put", "delete", "patch", "get"]:
        # Match both @app.get( and .get( and @GetMapping(
        if re.search(rf'(?:@|\.){method}\s*\(', content_lower):
            return method.upper()
    return "GET"  # Default


def _extract_path(content: str) -> str:
    """Extract URL path from route definition."""
    # Match string literal in first argument
    match = re.search(r"""['"]([^'"]+)['"]""", content)
    if match:
        return match.group(1)
    return ""


# ─────────────────────────────────────────────
# Strategy C: Read key files for LLM analysis
# ─────────────────────────────────────────────

def find_and_read_key_files(project_path: str, tech_stack: dict, max_files: int = 20) -> list[dict]:
    """
    Find and read the most relevant files for LLM analysis.
    Prioritizes: entry point, route files, model files, config files.
    """
    root = Path(project_path)
    key_files = []
    seen = set()

    def _add_file(filepath: Path, priority: int):
        """Add a file if it exists and hasn't been added yet."""
        if not filepath.exists() or not filepath.is_file():
            return
        abs_path = str(filepath.resolve())
        if abs_path in seen:
            return
        seen.add(abs_path)
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            rel_path = str(filepath.relative_to(root))
            key_files.append({
                "path": rel_path,
                "priority": priority,
                "content": content,
                "size": len(content),
            })
        except (OSError, UnicodeDecodeError):
            pass

    def _add_python_files(dirpath: Path, priority: int, max_count: int = 10):
        """Add Python files from a directory with a given priority."""
        if not dirpath.is_dir():
            return
        count = 0
        for f in sorted(dirpath.iterdir()):
            if f.is_file() and f.suffix == ".py":
                _add_file(f, priority)
                count += 1
                if count >= max_count:
                    break

    # Priority 1: Entry point (always included)
    if tech_stack.get("entry_point"):
        _add_file(root / tech_stack["entry_point"], 1)

    # Priority 2: Route/routers directories
    backend_dir = tech_stack.get("backend_dir")
    for route_dir_name in ["routers", "routes", "controllers", "endpoints", "views", "api"]:
        if backend_dir:
            _add_python_files(root / backend_dir / route_dir_name, 2)
        _add_python_files(root / route_dir_name, 2)

    # Priority 3: Main app files
    for fname in ["main.py", "app.py", "server.py", "application.py", "__init__.py"]:
        if backend_dir:
            _add_file(root / backend_dir / fname, 3)
        _add_file(root / fname, 3)

    # Priority 4: Model/schema files
    for model_dir_name in ["models", "schemas", "entities", "types"]:
        if backend_dir:
            _add_python_files(root / backend_dir / model_dir_name, 4, max_count=5)
        _add_python_files(root / model_dir_name, 4, max_count=5)

    # Priority 5: Config files
    for cfg in ["requirements.txt", "package.json", "pyproject.toml", "setup.py", "config.py", "settings.py"]:
        if backend_dir:
            _add_file(root / backend_dir / cfg, 5)
        _add_file(root / cfg, 5)

    # Sort by priority, then by size (smaller first, for LLM context)
    key_files.sort(key=lambda x: (x["priority"], x["size"]))

    # Enforce max_files limit, keep highest priority
    if len(key_files) > max_files:
        # Keep all priority 1-3, then trim lower priorities
        high_priority = [f for f in key_files if f["priority"] <= 3]
        low_priority = [f for f in key_files if f["priority"] > 3]
        low_priority.sort(key=lambda x: x["size"])
        key_files = high_priority + low_priority[:max_files - len(high_priority)]

    return key_files[:max_files]


# ─────────────────────────────────────────────
# Feature filtering: narrow routes to a specific feature
# ─────────────────────────────────────────────

def filter_routes_by_feature(routes: list[dict], feature_name: str) -> list[dict]:
    """
    Filter API routes to only those related to a specific feature.
    Supports both Chinese and English keywords.
    """
    if not feature_name or not routes:
        return routes

    # Chinese → English keyword mapping for common backend features
    CN_EN_MAP = {
        "登录": "login",
        "注册": "register|signup|sign_up",
        "用户": "user",
        "订单": "order",
        "支付": "pay|payment",
        "商品": "product|item|goods",
        "购物车": "cart",
        "管理员": "admin",
        "权限": "permission|role|auth",
        "角色": "role",
        "搜索": "search",
        "推荐": "recommend|rec",
        "评论": "review|comment|rating",
        "收藏": "favorite|fav|collect",
        "通知": "notification|notify|message",
        "文件": "file|upload|download",
        "图片": "image|photo|img|picture",
        "报表": "report|analytics|statistic|dashboard",
        "健康检查": "health|ping",
        "配置": "config|setting",
        "日志": "log|audit",
        "缓存": "cache|redis",
        "紧急": "emergency|alert",
    }

    # Build keyword set: original + Chinese mapped + split parts
    raw = feature_name.lower().replace("-", " ").replace("_", " ")
    keywords = set(raw.split())

    # Add mapped English keywords
    for cn, en_pattern in CN_EN_MAP.items():
        if cn in raw:
            for ek in en_pattern.split("|"):
                keywords.add(ek.strip())

    # Also add the full original phrase
    keywords.add(feature_name.lower())

    if not keywords:
        return routes

    matched = []
    seen = set()

    for route in routes:
        path = (route.get("path") or "").lower()
        file_path = (route.get("file") or "").lower()
        content = (route.get("content_snippet") or "").lower()
        method = (route.get("method") or "").lower()
        route_file_name = file_path.split("/")[-1] if "/" in file_path else file_path

        # Score: how many keywords match this route
        score = 0
        for kw in keywords:
            if kw in path:
                score += 3
            if kw in file_path:
                score += 2
            if kw in route_file_name:
                score += 2
            if kw in content:
                score += 1

        if score > 0:
            dedup_key = f"{method}:{path}"
            if dedup_key not in seen:
                seen.add(dedup_key)
                route["_feature_score"] = score
                matched.append(route)

    # Sort by score descending
    matched.sort(key=lambda x: x.get("_feature_score", 0), reverse=True)

    if matched:
        logger.info(f"Feature '{feature_name}': matched {len(matched)}/{len(routes)} routes")
        return matched

    # Fallback: no match, return all routes with a note
    logger.warning(f"Feature '{feature_name}': no routes matched, using all {len(routes)} routes")
    return routes


# ─────────────────────────────────────────────
# LLM semantic filter: understand user intent
# ─────────────────────────────────────────────

async def llm_filter_routes(
    routes: list[dict],
    feature_name: str,
    tech_stack: dict,
    llm_client=None,
) -> list[dict]:
    """
    Use LLM to semantically match routes to user's testing intent.

    Two-stage strategy:
    1. LLM 语义精筛（准确度高） — 理解用户意图，精准匹配路由
    2. 无 LLM 时降级到关键词匹配

    相比纯关键词匹配的优势：
    - 理解中文近义词（"预约"≈"appointment"、"排班"≈"schedule"）
    - 排除语义不符但关键词命中的路由（"用户删除"≠"用户信息查询"）
    - 不需要维护中文→英文映射表
    """
    if not feature_name or not routes:
        return routes

    if not llm_client:
        logger.info("llm_filter_routes: no LLM client, falling back to keyword filter")
        return filter_routes_by_feature(routes, feature_name)

    # Build concise route summary for LLM
    route_lines = []
    for i, r in enumerate(routes):
        method = r.get("method", "GET")
        path = r.get("path", "/")
        file_loc = r.get("file", "").split(":")[0] if r.get("file") else ""
        route_lines.append(f"  [{i}] {method} {path}  ({file_loc})")

    route_summary = "\n".join(route_lines)
    language = tech_stack.get("language", "unknown")
    framework = tech_stack.get("framework", "unknown")

    prompt = f"""You are a backend API analyzer. Given a user's testing intent and a list of API routes, identify which routes are RELEVANT to the user's intent.

## User's Testing Intent
{feature_name}

## Tech Stack
Language: {language}
Framework: {framework}

## Available API Routes
{route_summary}

## Rules
- Include only routes DIRECTLY related to the user's intent
- Understand intent with semantic matching, not just keywords
  Example: "预约" → appointment/schedule/booking routes
  Example: "登录" → login/signin/auth routes
  Example: "用户管理" → user CRUD routes
- Exclude routes that are semantically unrelated, even if keywords overlap
  Example: intent="查询用户信息" → exclude DELETE /api/user/{{id}}
- For read-heavy intents ("查询"/"查看"/"展示"), prefer GET routes
- For write-heavy intents ("创建"/"注册"/"提交"), include POST routes
- Include ALL relevant routes, not just the most obvious ones

## Output Format
ONLY output a valid JSON object with this structure (no markdown, no code blocks):
{{"matched_route_indices": [0, 2, 5], "reasoning": "brief explanation"}}

Return an empty array if no routes match: {{"matched_route_indices": [], "reasoning": "..."}}"""

    try:
        result_json = await llm_client.chat_json([
            {"role": "system", "content": "You are a backend API route analyzer. Output ONLY valid JSON. No markdown, no code fences."},
            {"role": "user", "content": prompt},
        ])

        if isinstance(result_json, dict) and "matched_route_indices" in result_json:
            indices = result_json["matched_route_indices"]
            matched = [routes[i] for i in indices if isinstance(i, int) and 0 <= i < len(routes)]
            reasoning = result_json.get("reasoning", "")
            logger.info(
                f"LLM filter: {len(matched)}/{len(routes)} routes matched "
                f"for '{feature_name}': {reasoning[:120]}"
            )
            if matched:
                return matched

        # LLM returned empty or unexpected format — fallback
        logger.warning(
            f"LLM filter returned no matches or unexpected format for "
            f"'{feature_name}', falling back to keyword filter"
        )
        return filter_routes_by_feature(routes, feature_name)

    except Exception as e:
        logger.warning(f"LLM filter failed: {e}, falling back to keyword filter")
        return filter_routes_by_feature(routes, feature_name)


# ─────────────────────────────────────────────
# Orchestrator: Full parse pipeline
# ─────────────────────────────────────────────

async def parse_project(project_path: str, llm_client=None) -> dict:
    """
    Full 4-step parse pipeline:
    A. Scan directory tree + detect tech stack
    B. Grep for API routes
    C. Read key files
    D. Call LLM for detailed analysis (if llm_client provided)

    Returns a rich ParseResult dict.
    """
    # Step A
    tree = read_directory_tree(project_path)
    tech_stack = detect_tech_stack(tree, project_path)

    # Step B
    routes = grep_api_routes(project_path, tech_stack.get("language"))

    # Step C
    key_files = find_and_read_key_files(project_path, tech_stack, max_files=20)

    result = {
        "tech_stack": tech_stack,
        "routes_from_grep": routes,
        "key_files_count": len(key_files),
        "key_files": [
            {"path": f["path"], "size": f["size"], "priority": f["priority"]}
            for f in key_files
        ],
    }

    # Step D: LLM analysis (if client provided)
    if llm_client:
        try:
            llm_result = await _call_llm_analysis(llm_client, tech_stack, key_files, routes)
            result["llm_analysis"] = llm_result
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            result["llm_analysis"] = {"error": str(e)}

    return result


async def _call_llm_analysis(llm_client, tech_stack: dict, key_files: list, routes: list) -> dict:
    """Call LLM to analyze the project and extract structured information."""
    # Build a concise context for the LLM
    files_summary = []
    for f in key_files:
        content = f["content"]
        # Truncate very long files
        if len(content) > 3000:
            content = content[:3000] + f"\n... (truncated, total {len(content)} chars)"
        files_summary.append(f"### {f['path']}\n```python\n{content}\n```")

    routes_summary = []
    for r in routes[:20]:  # Limit routes in prompt
        routes_summary.append(f"- {r['method']} {r['path']} ({r['file']})")

    prompt = f"""Analyze this backend project and extract structured information.

## Tech Stack (detected)
- Language: {tech_stack.get('language', 'unknown')}
- Framework: {tech_stack.get('framework', 'unknown')}
- Entry Point: {tech_stack.get('entry_point', 'unknown')}
- Web Server: {tech_stack.get('web_server', 'unknown')}

## Grepped Routes (grep results)
{chr(10).join(routes_summary) if routes_summary else "No routes detected by grep."}

## Source Files (key files)
{chr(10).join(files_summary[:10])}

Based on the above, output a JSON object with:
1. "tech_stack" — confirmed language, framework, database, web_server
2. "api_endpoints" — array of {{method, path, file, description}} objects. Include all found routes.
3. "entry_point" — the confirmed entry point file
4. "startup_hint" — how to start this service (e.g. "uvicorn main:app", "npm start")
5. "has_openapi" — boolean, whether /openapi.json or /docs exists
6. "notes" — any important observations about the project structure
"""

    result_json = await llm_client.chat_json([
        {"role": "system", "content": "You are a backend code analysis expert. Output only valid JSON."},
        {"role": "user", "content": prompt},
    ])

    return result_json
