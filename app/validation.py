import ast
import re
from typing import List, Dict, Any, Optional
from app.models import ScriptAnalysis
from app.config import settings
import structlog

logger = structlog.get_logger()


class ScriptValidator:
    """Advanced script validation and security analysis"""

    # Forbidden imports that could be used maliciously
    FORBIDDEN_IMPORTS = {
        'os', 'subprocess', 'sys', 'eval', 'exec', '__import__',
        'open', 'file', 'input', 'raw_input', 'compile', 'globals',
        'locals', 'vars', 'dir', 'getattr', 'setattr', 'delattr',
        'hasattr', 'isinstance', 'issubclass', 'callable', 'classmethod',
        'staticmethod', 'property', 'super', 'type', 'object'
    }

    # Dangerous built-in functions
    DANGEROUS_FUNCTIONS = {
        'eval', 'exec', 'compile', '__import__', 'getattr', 'setattr',
        'delattr', 'globals', 'locals', 'vars', 'open', 'file'
    }

    # Dangerous string patterns
    DANGEROUS_PATTERNS = [
        r'__.*__',  # Dunder methods
        r'\.system\(',  # System calls
        r'\.popen\(',  # Process opening
        r'\.call\(',  # Subprocess calls
        r'import\s+os',  # OS module import
        r'from\s+os',  # OS module from import
        r'subprocess',  # Subprocess usage
        r'eval\s*\(',  # Eval calls
        r'exec\s*\(',  # Exec calls
    ]

    # Allowed Playwright operations
    PLAYWRIGHT_OPERATIONS = {
        'navigation': ['goto', 'go_back', 'go_forward', 'reload', 'navigate'],
        'interaction': ['click', 'dblclick', 'tap', 'fill', 'clear', 'type', 'press', 'key'],
        'form_filling': ['fill', 'check', 'uncheck', 'select_option', 'set_input_files'],
        'waiting': ['wait_for_selector', 'wait_for_load_state', 'wait_for_timeout', 'wait_for_event', 'wait_for_function'],
        'data_extraction': ['text_content', 'inner_text', 'inner_html', 'get_attribute', 'input_value'],
        'capture': ['screenshot', 'pdf', 'video'],
        'evaluation': ['evaluate', 'evaluate_handle', 'query_selector', 'query_selector_all'],
        'network': ['set_extra_http_headers', 'set_user_agent', 'route', 'unroute']
    }

    def __init__(self):
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.DANGEROUS_PATTERNS]

    def validate_script(self, script: str) -> ScriptAnalysis:
        """Comprehensive script validation"""
        warnings = []
        detected_operations = []
        complexity = "low"

        # Basic size check
        if len(script) > settings.MAX_SCRIPT_SIZE:
            warnings.append(f"Script too large: {len(script)} bytes (max: {settings.MAX_SCRIPT_SIZE})")

        # Pattern-based security checks
        security_warnings = self._check_security_patterns(script)
        warnings.extend(security_warnings)

        # AST-based analysis
        try:
            tree = ast.parse(script)
            ast_warnings, ast_operations, ast_complexity = self._analyze_ast(tree)
            warnings.extend(ast_warnings)
            detected_operations.extend(ast_operations)
            complexity = max(complexity, ast_complexity, key=lambda x: ['low', 'medium', 'high'].index(x))

        except SyntaxError as e:
            warnings.append(f"Syntax error: {str(e)}")
            complexity = "high"  # Unparseable scripts are risky

        # Function definition analysis
        function_warnings = self._check_function_definitions(script)
        warnings.extend(function_warnings)

        # Performance analysis
        performance_warnings = self._analyze_performance_patterns(script)
        warnings.extend(performance_warnings)

        return ScriptAnalysis(
            estimated_complexity=complexity,
            detected_operations=list(set(detected_operations)),
            security_warnings=warnings
        )

    def _check_security_patterns(self, script: str) -> List[str]:
        """Check for dangerous patterns using regex"""
        warnings = []

        for pattern in self.compiled_patterns:
            matches = pattern.findall(script)
            if matches:
                warnings.append(f"Dangerous pattern detected: {pattern.pattern}")

        # Check for forbidden strings
        script_lower = script.lower()
        for forbidden in ['import os', 'import sys', 'import subprocess', '__import__']:
            if forbidden in script_lower:
                warnings.append(f"Forbidden import pattern: {forbidden}")

        return warnings

    def _analyze_ast(self, tree: ast.AST) -> tuple[List[str], List[str], str]:
        """Analyze AST for security and complexity"""
        warnings = []
        operations = []
        complexity = "low"

        node_count = 0
        loop_count = 0
        function_count = 0
        import_count = 0

        for node in ast.walk(tree):
            node_count += 1

            # Check imports
            if isinstance(node, ast.Import):
                import_count += 1
                for alias in node.names:
                    if alias.name in self.FORBIDDEN_IMPORTS:
                        warnings.append(f"Forbidden import: {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                import_count += 1
                if node.module in self.FORBIDDEN_IMPORTS:
                    warnings.append(f"Forbidden module: {node.module}")

            # Check function calls
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                    if func_name in self.DANGEROUS_FUNCTIONS:
                        warnings.append(f"Dangerous function call: {func_name}")

                # Detect Playwright operations
                elif isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                    self._categorize_playwright_operation(method_name, operations)

            # Count control structures
            elif isinstance(node, (ast.For, ast.While)):
                loop_count += 1

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1

            # Check for dangerous attribute access
            elif isinstance(node, ast.Attribute):
                if node.attr.startswith('__') and node.attr.endswith('__'):
                    warnings.append(f"Dunder attribute access: {node.attr}")

        # Determine complexity based on counts
        if node_count > 200 or loop_count > 10 or function_count > 5:
            complexity = "high"
        elif node_count > 100 or loop_count > 5 or function_count > 2:
            complexity = "medium"

        if import_count > 5:
            warnings.append(f"Too many imports: {import_count}")

        return warnings, operations, complexity

    def _categorize_playwright_operation(self, method_name: str, operations: List[str]):
        """Categorize Playwright method calls"""
        for category, methods in self.PLAYWRIGHT_OPERATIONS.items():
            if method_name in methods:
                operations.append(category)
                return

    def _check_function_definitions(self, script: str) -> List[str]:
        """Check function definitions for potential issues"""
        warnings = []

        # Check for async/await usage
        if 'async def' not in script and 'await ' in script:
            warnings.append("Using 'await' without 'async def' - this will cause errors")

        # Check for main function using regex to handle newlines and whitespace
        main_function_patterns = [
            r'def\s+main\s*\(',  # Regular main function
            r'async\s+def\s+main\s*\(',  # Async main function
        ]

        has_main_function = any(re.search(pattern, script, re.MULTILINE | re.DOTALL)
                               for pattern in main_function_patterns)

        logger.info("Main function validation",
                   script_preview=script[:100],
                   has_main_function=has_main_function,
                   patterns_tested=main_function_patterns)

        if not has_main_function:
            warnings.append("Script must contain an async main() function")

        # Check for infinite loops patterns
        infinite_patterns = [
            r'while\s+True\s*:',
            r'while\s+1\s*:',
            r'for\s+.*\s+in\s+itertools\.count\(',
        ]

        for pattern in infinite_patterns:
            if re.search(pattern, script, re.IGNORECASE):
                warnings.append(f"Potential infinite loop detected: {pattern}")

        return warnings

    def _analyze_performance_patterns(self, script: str) -> List[str]:
        """Analyze script for performance issues"""
        warnings = []

        # Check for potential performance issues
        performance_patterns = [
            (r'time\.sleep\(\s*\d+\s*\)', "Using time.sleep() - consider page.wait_for_timeout()"),
            (r'while.*not.*selector', "Busy waiting for selector - use wait_for_selector()"),
            (r'\.screenshot\(.*full_page\s*=\s*True', "Full page screenshots can be slow"),
            (r'\.pdf\(', "PDF generation can be resource intensive"),
            (r'for.*in.*range\(\s*\d{3,}', "Large loops may cause timeouts"),
        ]

        for pattern, message in performance_patterns:
            if re.search(pattern, script, re.IGNORECASE):
                warnings.append(f"Performance concern: {message}")

        # Check for excessive selectors
        selector_count = len(re.findall(r'query_selector|wait_for_selector|click|fill', script, re.IGNORECASE))
        if selector_count > 50:
            warnings.append(f"High number of selector operations: {selector_count}")

        return warnings

    def estimate_execution_time(self, script: str) -> float:
        """Estimate script execution time in seconds"""
        base_time = 5.0  # Base execution time

        # Factor in script complexity
        try:
            tree = ast.parse(script)
            node_count = len(list(ast.walk(tree)))
            complexity_factor = min(node_count / 50, 3.0)  # Max 3x multiplier
            base_time *= (1 + complexity_factor)

        except SyntaxError:
            base_time *= 2.0  # Syntax errors make execution unpredictable

        # Factor in specific operations
        operation_factors = {
            r'\.goto\(': 2.0,  # Navigation is slow
            r'\.screenshot\(': 1.5,  # Screenshots take time
            r'\.pdf\(': 3.0,  # PDF generation is slow
            r'wait_for_selector': 2.0,  # Waiting operations
            r'time\.sleep': 1.0,  # Direct sleep
            r'\.fill\(': 0.5,  # Form filling
            r'\.click\(': 0.3,  # Clicking
        }

        for pattern, factor in operation_factors.items():
            matches = len(re.findall(pattern, script, re.IGNORECASE))
            base_time += matches * factor

        return min(base_time, 300.0)  # Cap at 5 minutes

    def validate_script_for_execution(self, script: str) -> Dict[str, Any]:
        """Complete validation for script execution"""
        analysis = self.validate_script(script)
        estimated_time = self.estimate_execution_time(script)

        # Determine if script should be allowed to execute
        critical_warnings = [
            w for w in analysis.security_warnings
            if any(keyword in w.lower() for keyword in ['forbidden', 'dangerous', 'syntax error', 'main()'])
        ]

        return {
            "analysis": analysis,
            "estimated_time": estimated_time,
            "is_safe": len(critical_warnings) == 0,
            "critical_warnings": critical_warnings,
            "recommendation": self._get_execution_recommendation(analysis, estimated_time)
        }

    def _get_execution_recommendation(self, analysis: ScriptAnalysis, estimated_time: float) -> str:
        """Get execution recommendation based on analysis"""
        if analysis.security_warnings:
            return "REJECT - Security concerns detected"

        if estimated_time > 180:  # 3 minutes
            return "REVIEW - Long execution time estimated"

        if analysis.estimated_complexity == "high":
            return "REVIEW - High complexity script"

        if len(analysis.detected_operations) > 8:
            return "REVIEW - Many operations detected"

        return "APPROVE - Script appears safe for execution"


# Global validator instance
script_validator = ScriptValidator()