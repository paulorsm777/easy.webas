#!/usr/bin/env python3
import json

# Simular o JSON que chega na API
json_data = '{"script": "async def main():\\n    return {\\"test\\": \\"hello\\"}", "timeout": 60, "priority": 3}'

print("JSON string:")
print(json_data)

# Parse JSON
parsed = json.loads(json_data)
print("\nParsed script:")
print(repr(parsed['script']))

# Test validation
import re

script = parsed['script']
main_function_patterns = [
    r'def\s+main\s*\(',  # Regular main function
    r'async\s+def\s+main\s*\(',  # Async main function
]

for pattern in main_function_patterns:
    match = re.search(pattern, script, re.MULTILINE | re.DOTALL)
    print(f"Pattern {pattern}: {match}")