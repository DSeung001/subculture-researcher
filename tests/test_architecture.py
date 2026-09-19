"""The package layout's dependency rules, checked from the imports alone (offline)."""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "subculture"
CONTEXTS = ("collection", "library", "drafts")
LAYERS = ("domain", "application", "infrastructure", "interface")

# A domain layer is plain Python: no I/O libraries.
FORBIDDEN_IN_DOMAIN = {
    "sqlalchemy", "alembic", "firebase_admin", "google", "flask", "requests", "yaml", "bs4",
    "feedparser", "dotenv", "playwright",
}


def modules():
    """(dotted module name, its imported dotted names) for every file in the package."""
    for path in sorted(PACKAGE.rglob("*.py")):
        name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        if name.endswith(".__init__"):
            name = name[: -len(".__init__")]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.append(node.module)
                # `from subculture.library import x` may import a submodule.
                imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
        yield name, imported


def place(name):
    """('collection', 'domain') for subculture.collection.domain.x; (None, None) for shared/web."""
    parts = name.split(".")
    context = parts[1] if len(parts) > 1 and parts[1] in CONTEXTS else None
    layer = parts[2] if context and len(parts) > 2 and parts[2] in LAYERS else None
    return context, layer


class ArchitectureTests(unittest.TestCase):
    def violations(self, rule):
        found = []
        for name, imported in modules():
            for target in imported:
                message = rule(name, target)
                if message:
                    found.append(f"{name} imports {target}: {message}")
        return found

    def test_every_context_has_the_four_layers(self):
        for context in CONTEXTS:
            for layer in LAYERS:
                self.assertTrue((PACKAGE / context / layer / "__init__.py").is_file(), f"{context}/{layer}")

    def test_domain_layers_stay_free_of_io_and_outer_layers(self):
        def rule(name, target):
            if place(name)[1] != "domain":
                return None
            if target.split(".")[0] in FORBIDDEN_IN_DOMAIN:
                return "a domain layer must not use I/O libraries"
            context, layer = place(target) if target.startswith("subculture.") else (None, None)
            if layer in ("application", "infrastructure", "interface"):
                return "a domain layer must not depend on outer layers"
            if target.startswith("subculture.web"):
                return "a domain layer must not depend on the web layer"
            if context and context != place(name)[0]:
                return "a domain layer only depends on its own context and the shared kernel"
            return None

        self.assertEqual(self.violations(rule), [])

    def test_infrastructure_does_not_depend_on_application_or_interface(self):
        def rule(name, target):
            if place(name)[1] != "infrastructure" or not target.startswith("subculture."):
                return None
            if place(target)[1] in ("application", "interface") or target.startswith("subculture.web"):
                return "infrastructure must not depend on application or interface code"
            return None

        self.assertEqual(self.violations(rule), [])

    def test_context_dependencies_point_one_way(self):
        # Below the interface layer: library depends on nobody; collection may only start a
        # library sync; drafts may use library. Interface modules (CLIs, screens) compose contexts.
        def rule(name, target):
            context, importer_layer = place(name)
            other, layer = place(target) if target.startswith("subculture.") else (None, None)
            if not context or not other or other == context or importer_layer == "interface":
                return None
            if context == "library":
                return "library must not depend on other contexts"
            if context == "collection" and (other != "library" or layer != "application"):
                return "collection may only call library.application (sync)"
            if context == "drafts" and other != "library":
                return "drafts may only depend on library"
            return None

        self.assertEqual(self.violations(rule), [])

    def test_shared_kernel_and_contexts_do_not_depend_on_web(self):
        def rule(name, target):
            if name.startswith("subculture.web"):
                return None
            if target.startswith("subculture.web"):
                return "only the web layer may import the web layer"
            if name.startswith("subculture.shared") and place(target)[0]:
                return "the shared kernel must not depend on a context"
            return None

        self.assertEqual(self.violations(rule), [])


if __name__ == "__main__":
    unittest.main()
