#!/usr/bin/env python3
import re

script = "async def main():\n    return {\"test\": \"hello\"}"
print(f"Script: {repr(script)}")

main_function_patterns = [
    r'def\s+main\s*\(',  # Regular main function
    r'async\s+def\s+main\s*\(',  # Async main function
]

for pattern in main_function_patterns:
    match = re.search(pattern, script, re.MULTILINE | re.DOTALL)
    print(f"Pattern {pattern}: {match}")

# Test with more lenient patterns
lenient_patterns = [
    r'async\s+def\s+main',
    r'def\s+main',
    r'main\(',
]

for pattern in lenient_patterns:
    match = re.search(pattern, script, re.MULTILINE | re.DOTALL)
    print(f"Lenient pattern {pattern}: {match}")