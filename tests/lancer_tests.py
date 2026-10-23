"""Lance les scénarios sans pytest (si pytest n'est pas installé) : python tests/lancer_tests.py"""
import inspect, sqlite3, sys, tempfile, time, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import test_scenarios as T

tmp = Path(tempfile.mkdtemp())
ref = tmp / "ref.db"
T.charger(ref).close()
ok = 0
tests = [(n, f) for n, f in inspect.getmembers(T, inspect.isfunction) if n.startswith("test_")]
for i, (nom, f) in enumerate(tests):
    copie = tmp / f"t{i}.db"
    s, d = sqlite3.connect(ref), sqlite3.connect(copie); s.backup(d); s.close()
    t = time.perf_counter()
    try:
        f(d); ok += 1; print(f"OK    {nom}  ({time.perf_counter() - t:.1f} s)")
    except Exception:
        print(f"ÉCHEC {nom}"); traceback.print_exc()
    d.close()
print(f"\n{ok}/{len(tests)} tests réussis")
sys.exit(0 if ok == len(tests) else 1)
