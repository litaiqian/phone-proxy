import py_compile, sys, os

files = [
    r'D:\采购管理\媽媽5\moutai_client_worker.py',
    r'D:\采购管理\媽媽5\main.py',
    r'D:\采购管理\媽媽5\moutai_automation.py',
]

all_ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f'[OK] {os.path.basename(f)}')
    except py_compile.PyCompileError as e:
        print(f'[ERROR] {os.path.basename(f)}: {e}')
        all_ok = False

if all_ok:
    print()
    print('=== All syntax checks passed ===')
    sys.exit(0)
else:
    print()
    print('=== Syntax errors found ===')
    sys.exit(1)
