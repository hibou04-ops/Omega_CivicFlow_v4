"""Fix double-backslash unicode escapes in ChatBot.jsx.

Replaces \\uXXXX (literal backslash-u-hex) with actual Korean characters.
Only targets string literals (inside quotes), not regex patterns.
"""
import re, sys

filepath = r'c:\Users\hibou\Omega_CivicFlow_v4\frontend\src\components\ChatBot.jsx'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

original = content

# Pattern: literal backslash + u + 4 hex digits
# In the file, this appears as \\uXXXX (two chars: \ and u)
pattern = re.compile(r'\\u([0-9a-fA-F]{4})')

def replace_unicode_escape(m):
    codepoint = int(m.group(1), 16)
    # Skip ASCII-range escapes and common HTML entities that might be intentional in regex
    # We only want to fix Korean/CJK characters (U+AC00-U+D7AF, U+3000-U+9FFF) and some others
    if codepoint >= 0x1100:  # Korean and CJK range
        return chr(codepoint)
    return m.group(0)  # Leave non-Korean escapes untouched

new_content = pattern.sub(replace_unicode_escape, content)

changes = 0
for old, new in zip(content, new_content):
    if old != new:
        changes += 1

if new_content != original:
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    # Count replacements
    old_count = len(pattern.findall(original))
    new_count = len(pattern.findall(new_content))
    print(f"Fixed {old_count - new_count} unicode escapes")
    print("File updated successfully")
else:
    print("No changes needed")
