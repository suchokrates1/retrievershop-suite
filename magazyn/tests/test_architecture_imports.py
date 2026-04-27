import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_ROOTS = (REPO_ROOT / "magazyn", REPO_ROOT / "scripts", REPO_ROOT / "migrations")

FORBIDDEN_IMPORTS = {
    "magazyn.models": None,
    "magazyn.agent": None,
    "magazyn.orders": {"sync_order_from_data", "add_order_status", "_dispatch_status_email"},
    "magazyn.price_reports": {"change_price", "recheck_item"},
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
FORBIDDEN_PRINT_AGENT_ATTRIBUTES = FORBIDDEN_IMPORTS["magazyn.print_agent"] | {
    "LabelAgent",
    "load_config",
    "settings",
}


def _iter_python_files():
    ignored_parts = {".git", ".venv", ".ci-venv", "__pycache__"}
    for root in CHECKED_ROOTS:
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