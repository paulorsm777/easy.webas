import ast
import re
from typing import List, Tuple, Dict, Any
from .models import ValidationResult
from .logger import Logger

logger = Logger("validation")


class ScriptValidator:
    def __init__(self):
        # Dangerous imports/functions to block
        self.blacklisted_imports = {
            "os",
            "subprocess",
            "sys",
            "eval",
            "exec",
            "__import__",
            "open",
            "file",
            "input",
            "raw_input",
            "compile",
            "globals",
            "locals",
            "vars",
            "dir",
            "hasattr",
            "getattr",
            "setattr",
            "delattr",
            "breakpoint",
            "help",
            "exit",
            "quit",
        }

        # Dangerous function calls
        self.blacklisted_functions = {
            "eval",
            "exec",
            "compile",
            "__import__",
            "open",
            "file",
        }

        # Common complexity indicators
        self.complexity_patterns = {
            "high": [
                r"for.*in.*range\([0-9]{4,}\)",  # Large loops
                r"while.*True",  # Infinite loops
                r"time\.sleep\([0-9]{2,}\)",  # Long sleeps
                r"requests\.get.*timeout=None",  # No timeout requests
            ],
            "medium": [
                r"for.*in.*range\([0-9]{2,3}\)",  # Medium loops
                r"await.*\n.*await.*\n.*await",  # Multiple awaits
                r"\.click\(\).*\n.*\.click\(\)",  # Multiple clicks
            ],
            "low": [
                r"page\.goto\(",  # Simple navigation
                r"page\.title\(\)",  # Simple property access
                r"page\.text_content\(",  # Simple text extraction
            ],
        }

    async def validate_script(self, script: str) -> ValidationResult:
        """Validate a Playwright script for security and complexity"""
        errors = []
        warnings = []

        try:
            # Parse the script
            tree = ast.parse(script)

            # Security validation
            security_errors = self._check_security(tree, script)
            errors.extend(security_errors)

            # Syntax and structure validation
            structure_errors = self._check_structure(tree, script)
            errors.extend(structure_errors)

            # Performance warnings
            performance_warnings = self._check_performance(script)
            warnings.extend(performance_warnings)

            # Estimate complexity
            complexity = self._estimate_complexity(script)

            # Estimate duration
            duration = self._estimate_duration(script, complexity)

            # Detect operations
            operations = self._detect_operations(script)

            is_valid = len(errors) == 0

            if is_valid:
                logger.info(
                    "script_validation_success",
                    complexity=complexity,
                    estimated_duration=duration,
                    operations=operations,
                    warnings_count=len(warnings),
                )
            else:
                logger.warning(
                    "script_validation_failed", errors=errors, warnings=warnings
                )

            return ValidationResult(
                is_valid=is_valid,
                errors=errors,
                warnings=warnings,
                estimated_complexity=complexity,
                estimated_duration=duration,
                detected_operations=operations,
            )

        except SyntaxError as e:
            errors.append(f"Syntax error: {str(e)}")
            logger.error("script_syntax_error", error=str(e))

            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                estimated_complexity="unknown",
                estimated_duration=60,
                detected_operations=[],
            )

    def _check_security(self, tree: ast.AST, script: str) -> List[str]:
        """Check for security issues"""
        errors = []

        class SecurityVisitor(ast.NodeVisitor):
            def __init__(self, validator):
                self.validator = validator
                self.errors = []

            def visit_Import(self, node):
                for alias in node.names:
                    if alias.name in self.validator.blacklisted_imports:
                        self.errors.append(f"Forbidden import: {alias.name}")
                self.generic_visit(node)

            def visit_ImportFrom(self, node):
                if node.module in self.validator.blacklisted_imports:
                    self.errors.append(f"Forbidden import: {node.module}")
                for alias in node.names:
                    if alias.name in self.validator.blacklisted_imports:
                        self.errors.append(f"Forbidden import: {alias.name}")
                self.generic_visit(node)

            def visit_Call(self, node):
                # Check function calls
                if isinstance(node.func, ast.Name):
                    if node.func.id in self.validator.blacklisted_functions:
                        self.errors.append(f"Forbidden function call: {node.func.id}")
                elif isinstance(node.func, ast.Attribute):
                    # Check for dynamic eval patterns
                    if node.func.attr in ["eval", "exec"]:
                        self.errors.append(f"Forbidden method call: {node.func.attr}")

                self.generic_visit(node)

            def visit_Attribute(self, node):
                # Check for file system access
                if isinstance(node.value, ast.Name) and node.attr in [
                    "open",
                    "read",
                    "write",
                ]:
                    self.errors.append(f"File system access not allowed: {node.attr}")
                self.generic_visit(node)

        visitor = SecurityVisitor(self)
        visitor.visit(tree)
        errors.extend(visitor.errors)

        # Check for dynamic code patterns
        dangerous_patterns = [
            r"eval\s*\(",
            r"exec\s*\(",
            r"__import__\s*\(",
            r"compile\s*\(",
            r"open\s*\(",
            r"file\s*\(",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, script, re.IGNORECASE):
                errors.append(f"Potentially dangerous pattern detected: {pattern}")

        return errors

    def _check_structure(self, tree: ast.AST, script: str) -> List[str]:
        """Check script structure and requirements"""
        errors = []

        # Check if main function exists
        has_main_function = False

        class StructureVisitor(ast.NodeVisitor):
            def __init__(self):
                self.has_main = False
                self.async_main = False

            def visit_FunctionDef(self, node):
                if node.name == "main":
                    self.has_main = True
                self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node):
                if node.name == "main":
                    self.has_main = True
                    self.async_main = True
                self.generic_visit(node)

        visitor = StructureVisitor()
        visitor.visit(tree)

        if not visitor.has_main:
            errors.append("Script must contain a 'main' function")

        if visitor.has_main and not visitor.async_main:
            errors.append("The 'main' function must be async (async def main)")

        # Check script size
        if len(script) > 50000:
            errors.append("Script size exceeds maximum limit (50KB)")

        return errors

    def _check_performance(self, script: str) -> List[str]:
        """Check for performance issues"""
        warnings = []

        # Check for potential performance issues
        performance_patterns = [
            (r"time\.sleep\([0-9]+\)", "Long sleep detected - consider shorter delays"),
            (r"for.*in.*range\([0-9]{3,}\)", "Large loop detected - may cause timeout"),
            (r"while\s+True:", "Infinite loop detected - ensure proper exit condition"),
            (r"requests\.get.*timeout=None", "Request without timeout - may hang"),
            (r"page\.wait_for_timeout\([0-9]{4,}\)", "Long wait_for_timeout detected"),
        ]

        for pattern, message in performance_patterns:
            if re.search(pattern, script, re.IGNORECASE):
                warnings.append(message)

        return warnings

    def _estimate_complexity(self, script: str) -> str:
        """Estimate script complexity based on patterns"""

        # Count complexity indicators
        high_score = 0
        medium_score = 0
        low_score = 0

        for pattern in self.complexity_patterns["high"]:
            high_score += len(re.findall(pattern, script, re.IGNORECASE))

        for pattern in self.complexity_patterns["medium"]:
            medium_score += len(re.findall(pattern, script, re.IGNORECASE))

        for pattern in self.complexity_patterns["low"]:
            low_score += len(re.findall(pattern, script, re.IGNORECASE))

        # Simple scoring
        if high_score > 0:
            return "high"
        elif medium_score > 2 or len(script) > 20000:
            return "high"
        elif medium_score > 0 or len(script) > 5000:
            return "medium"
        else:
            return "low"

    def _estimate_duration(self, script: str, complexity: str) -> int:
        """Estimate execution duration in seconds"""
        base_duration = {"low": 15, "medium": 45, "high": 120}.get(complexity, 60)

        # Adjust based on specific operations
        duration_modifiers = [
            (r"page\.goto\(", 3),  # Each navigation
            (r"page\.wait_for_selector\(", 2),  # Each wait
            (r"page\.screenshot\(", 1),  # Each screenshot
            (r"page\.pdf\(", 2),  # PDF generation
            (r"time\.sleep\(([0-9]+)\)", lambda m: int(m.group(1))),  # Sleep duration
        ]

        for pattern, modifier in duration_modifiers:
            matches = re.finditer(pattern, script, re.IGNORECASE)
            for match in matches:
                if callable(modifier):
                    base_duration += modifier(match)
                else:
                    base_duration += modifier

        return min(base_duration, 300)  # Cap at 5 minutes

    def _detect_operations(self, script: str) -> List[str]:
        """Detect what operations the script performs"""
        operations = []

        operation_patterns = {
            "navigation": [r"page\.goto\(", r"page\.go_back\(", r"page\.go_forward\("],
            "form_filling": [r"page\.fill\(", r"page\.type\(", r"page\.check\("],
            "clicking": [r"page\.click\(", r"page\.double_click\("],
            "data_extraction": [
                r"page\.text_content\(",
                r"page\.inner_text\(",
                r"page\.query_selector",
            ],
            "screenshots": [r"page\.screenshot\(", r"page\.pdf\("],
            "file_upload": [r"page\.set_input_files\("],
            "waiting": [r"page\.wait_for_", r"time\.sleep\("],
            "javascript": [r"page\.evaluate\(", r"page\.add_script_tag\("],
            "authentication": [r"page\.set_extra_http_headers\(", r"context\.set_"],
            "network": [r"page\.route\(", r"page\.unroute\("],
        }

        for operation, patterns in operation_patterns.items():
            for pattern in patterns:
                if re.search(pattern, script, re.IGNORECASE):
                    operations.append(operation)
                    break

        return list(set(operations))  # Remove duplicates


# Global validator instance
validator = ScriptValidator()
