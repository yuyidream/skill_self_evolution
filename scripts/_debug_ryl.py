import tempfile, subprocess, pathlib

path = pathlib.Path(r'E:\projects\skill_self_evolution\.ryl.toml')
s = 'a: 1   \nb: 2\n'

with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', encoding='utf-8', newline='\n', delete=False) as f:
    f.write(s)
    fp = f.name

content_bytes = pathlib.Path(fp).read_bytes()
print(f'File content (hex): {content_bytes.hex()}')

r = subprocess.run(
    ['e:/projects/housekeeping_ai_match/.venv/Scripts/ryl.exe', '--config-file', str(path), fp],
    capture_output=True, text=True, timeout=10
)
print(f'rc={r.returncode}')
print(f'stdout: {r.stdout!r}')
print(f'stderr: {r.stderr!r}')

# Test the filter logic
combined = r.stdout + r.stderr
for i, line in enumerate(combined.splitlines()):
    if line.strip():
        print(f'  L{i}: [{line}] has_error={"error" in line.lower()}')

pathlib.Path(fp).unlink()
