import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_ROOTS = (REPO_ROOT / "magazyn", REPO_ROOT / "scripts", REPO_ROOT / "migrations")
PRODUCTION_ROOTS = (REPO_ROOT / "magazyn", REPO_ROOT / "scripts")

FORBIDDEN_IMPORTS = {
    "magazyn.models": None,
    "magazyn.agent": None,
    "magazyn.orders": {"sync_order_from_data", "add_order_status", "_dispatch_status_email"},
    "magazyn.price_reports": {"change_price", "recheck_item"},
    "magazyn.returns": {"restore_stock_for_return", "check_refund_eligibility", "process_refund"},
    "magazyn.print_agent": {
        "AgentConfig",
        "ApiError",
        "ConfigError",
        "PrintError",
        "ShipmentExpiredError",
        "PRINT_QUEUE_OLDEST_AGE_SECONDS",
        "PRINT_QUEUE_SIZE",
        "calculate_cod_amount",
        "parse_time_str",
        "parse_product_info",
        "consume_order_stock",
        "get_sales_summary",
        "send_report",
        "shorten_product_name",
    },
}

FORBIDDEN_MODULE_IMPORTS = {"magazyn.agent"}
ROUTE_MODULES = {
    "magazyn.app",
    "magazyn.discussions",
    "magazyn.orders",
    "magazyn.price_reports",
    "magazyn.products",
}
ROUTE_IMPORT_ALLOWLIST = {
    Path("magazyn/factory.py"),
}
FORBIDDEN_PRINT_AGENT_ATTRIBUTES = FORBIDDEN_IMPORTS["magazyn.print_agent"] | {
    "LabelAgent",
    "load_config",
    "settings",
}
ROOT_MODULE_LINE_LIMIT = 450
LEGACY_ROOT_MODULE_BUDGETS = {
    Path("magazyn/app.py"): 620,
    Path("magazyn/db.py"): 490,
    Path("magazyn/label_agent.py"): 750,
    Path("magazyn/settings_store.py"): 600,
}


def _iter_python_files():
    ignored_parts = {".git", ".venv", ".ci-venv", "__pycache__"}
    for root in CHECKED_ROOTS:
        for path in root.rglob("*.py"):
            if ignored_parts.intersection(path.parts):
                continue
            yield path


def _iter_production_python_files():
    ignored_parts = {".git", ".venv", ".ci-venv", "__pycache__", "tests"}
    for root in PRODUCTION_ROOTS:
        for path in root.rglob("*.py"):
            if ignored_parts.intersection(path.parts):
                continue
            yield path


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPO_ROOT).with_suffix("")
    return ".".join(relative.parts)


def _resolve_import_from(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = _module_name(path).split(".")[:-1]
    base_parts = package_parts[: len(package_parts) - node.level + 1]
    module_parts = node.module.split(".") if node.module else []
    return ".".join(base_parts + module_parts)


def test_no_legacy_facade_imports():
    violations = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print_agent_aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_MODULE_IMPORTS:
                        rel_path = path.relative_to(REPO_ROOT)
                        violations.append(f"{rel_path}:{node.lineno} -> import {alias.name}")
                    if alias.name == "magazyn.print_agent" and alias.asname:
                        print_agent_aliases.add(alias.asname)
                continue

            if not isinstance(node, ast.ImportFrom):
                continue

            module = _resolve_import_from(path, node)
            if module == "magazyn":
                for alias in node.names:
                    if alias.name == "print_agent":
                        print_agent_aliases.add(alias.asname or alias.name)

            forbidden_names = FORBIDDEN_IMPORTS.get(module)
            if module not in FORBIDDEN_IMPORTS:
                continue

            imported_names = {alias.name for alias in node.names}
            if forbidden_names is None:
                matched_names = imported_names
            else:
                matched_names = imported_names.intersection(forbidden_names)

            if matched_names:
                rel_path = path.relative_to(REPO_ROOT)
                names = ", ".join(sorted(matched_names))
                violations.append(f"{rel_path}:{node.lineno} -> {module}: {names}")

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            if node.value.id not in print_agent_aliases:
                continue
            if node.attr not in FORBIDDEN_PRINT_AGENT_ATTRIBUTES:
                continue
            rel_path = path.relative_to(REPO_ROOT)
            violations.append(
                f"{rel_path}:{node.lineno} -> magazyn.print_agent.{node.attr}"
            )

    assert not violations, "Stare importy fasad:\n" + "\n".join(violations)


def test_route_modules_are_not_used_as_service_dependencies():
    violations = []
    for path in _iter_production_python_files():
        relative_path = path.relative_to(REPO_ROOT)
        if relative_path in ROUTE_IMPORT_ALLOWLIST:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                module = _resolve_import_from(path, node)
                imported_modules = {module} if module else set()
            else:
                continue

            matched = imported_modules.intersection(ROUTE_MODULES)
            if matched:
                modules = ", ".join(sorted(matched))
                violations.append(f"{relative_path}:{node.lineno} -> {modules}")

    assert not violations, "Moduly route uzyte jako zaleznosci serwisowe:\n" + "\n".join(violations)


def test_print_agent_stays_a_thin_bootstrap():
    path = REPO_ROOT / "magazyn" / "print_agent.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defined_blocks = [
        node.name for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    exported_names = None
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if isinstance(node.value, ast.List):
            exported_names = [
                item.value for item in node.value.elts
                if isinstance(item, ast.Constant)
            ]

    assert defined_blocks == []
    assert exported_names == ["agent", "logger"]


def test_root_modules_stay_within_size_budget():
    violations = []
    for path in (REPO_ROOT / "magazyn").glob("*.py"):
        relative_path = path.relative_to(REPO_ROOT)
        budget = LEGACY_ROOT_MODULE_BUDGETS.get(relative_path, ROOT_MODULE_LINE_LIMIT)
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > budget:
            violations.append(f"{relative_path}: {line_count} linii > budzet {budget}")

    assert not violations, "Moduly glowne przekroczyly budzet rozmiaru:\n" + "\n".join(violations)