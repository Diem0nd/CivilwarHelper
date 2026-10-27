# 문법/pyflakes 체크 + 토큰 없이 전체 모듈 import 확인
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

files = [ROOT / "bot.py"]
for folder in (SRC, ROOT / "scripts", ROOT / "tests"):
    files.extend(sorted(folder.rglob("*.py")))

for path in files:
    compile(path.read_text(encoding="utf-8"), str(path), "exec")

res = subprocess.run([sys.executable, "-m", "pyflakes", *map(str, files)])
if res.returncode:
    sys.exit(res.returncode)

modules = sorted(
    ".".join(p.relative_to(SRC).with_suffix("").parts).removesuffix(".__init__")
    for p in (SRC / "civilwarhelper").rglob("*.py")
    if p.name != "__main__.py"
)
env = {**os.environ, "DISCORD_TOKEN": "", "PYTHONPATH": str(SRC)}
code = "import importlib, sys\nfor m in sys.argv[1:]: importlib.import_module(m)\n"
res = subprocess.run([sys.executable, "-c", code, *modules], cwd=ROOT, env=env)
if res.returncode:
    sys.exit(res.returncode)

print(f"ok ({len(files)} files, {len(modules)} modules)")
