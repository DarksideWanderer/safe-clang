#!/usr/bin/env python3
import json
import pathlib
import subprocess
import sys
import tempfile
clang, plugin, root = sys.argv[1:]
with tempfile.TemporaryDirectory(prefix='module-safety-graph-') as tmp:
    tmp = pathlib.Path(tmp)
    (tmp/'part.cppm').write_text('export module p:detail; export unsigned id(unsigned n) { return n; }')
    (tmp/'p.cppm').write_text('export module p; export import :detail; export unsigned helper();')
    (tmp/'impl.cpp').write_text('module p; unsigned helper() { return id(2u); }')
    (tmp/'q.cppm').write_text('/* import fake; */ export module q; import p; const char* text=R"test(import fake;)test"; export unsigned f() { return helper(); }')
    manifest = tmp/'modules.json'
    config = {'modules': [
        {'name': 'q', 'mode': 'safe', 'interface': 'q.cppm'},
        {'name': 'p', 'mode': 'safe', 'interface': 'p.cppm', 'partitions': [{'name': 'detail', 'interface': 'part.cppm'}], 'implementations': ['impl.cpp']},
    ]}
    command = [sys.executable, root+'/tools/build_modules.py', str(manifest), '--clang', clang, '--plugin', plugin, '--output', str(tmp/'out')]
    manifest.write_text(json.dumps(config))
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode: raise AssertionError(result.stderr)
    main = tmp/'main.cpp'; main.write_text('import q; int main() { return f()==2u ? 0 : 1; }')
    subprocess.run([clang, '-std=c++20', '-fprebuilt-module-path='+str(tmp/'out'), str(main)]+[str(p) for p in (tmp/'out').glob('*.o')]+['-o', str(tmp/'program')], check=True)
    subprocess.run([str(tmp/'program')], check=True)
    verify = [sys.executable, root+'/tools/verify_build.py', str(tmp/'out')]
    subprocess.run(verify, check=True, capture_output=True)
    published = (tmp/'out').resolve()
    # A source rejected after an earlier interface compiled must not replace
    # any file in the last successful generation.
    old = (tmp/'q.cppm').read_text()
    (tmp/'q.cppm').write_text(old+' unsigned broken(unsigned* p){return *p;}')
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode != 0 and (tmp/'out').resolve() == published, result.stderr
    (tmp/'q.cppm').write_text(old)
    subprocess.run(verify, check=True, capture_output=True)
    # Actual preprocessing decides dependencies, not text inside inactive #if.
    (tmp/'q.cppm').write_text(old+'\n#if 0\nimport absent;\n#endif\n')
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0 and (tmp/'out').resolve() != published, result.stderr
    assert published.is_dir(), 'previous generation disappeared'
    subprocess.run(verify, check=True, capture_output=True)
    obj = tmp/'out/q.o'
    original = obj.read_bytes()
    obj.write_bytes(original+b'corruption')
    result = subprocess.run(verify, text=True, capture_output=True)
    assert result.returncode != 0 and 'artifact mismatch' in result.stderr, result.stderr
    obj.write_bytes(original)
    subprocess.run(verify, check=True, capture_output=True)
    config['modules'][1]['partitions'][0]['mode'] = 'unsafe'
    manifest.write_text(json.dumps(config))
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0 or 'partition mode conflicts' not in result.stderr: raise AssertionError(result.stderr)
    del config['modules'][1]['partitions'][0]['mode']
    config['modules'][0]['name'] = 'wrong'
    manifest.write_text(json.dumps(config))
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode == 0 or 'manifest expects wrong' not in result.stderr: raise AssertionError(result.stderr)
print('Dependency graph, preprocessing, atomic publication, failed-build isolation, integrity verification, linking and manifest validation passed')
