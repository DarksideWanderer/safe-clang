#!/usr/bin/env python3
"""Validate and build a C++20 module graph with one safety mode per module."""
import argparse
import json
import pathlib
import re
import subprocess
import shlex
import shutil
from build_artifacts import digest, generation, verify

NAME = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*')
# Ignore comments, string/character literals (including raw strings), and
# preprocessing directives, so declarations mentioned there are not edges.
TOKEN = re.compile(r'R"(?P<rawdelim>[^ ()\\\t\r\n]{0,16})\([\s\S]*?\)(?P=rawdelim)"|/\*[\s\S]*?\*/|//[^\n]*|^[ \t]*\#[^\n]*(?:\\\n[^\n]*)*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[A-Za-z_][A-Za-z_0-9]*|[^\s]', re.MULTILINE)

def declarations(path, preprocess=None):
    source = path.read_text()
    if preprocess:
        result = subprocess.run(preprocess + [str(path)], text=True, capture_output=True)
        if result.returncode:
            raise ValueError(f"{path}: dependency preprocessing failed\n{result.stderr}")
        source = result.stdout
    tokens = []
    for match in TOKEN.finditer(source):
        value = match.group()
        if value.startswith(('R"', '/*', '//', '"', "'")) or value.lstrip().startswith('#'):
            continue
        tokens.append(value)
    declared, interface, imports = None, False, []
    depth = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == '{': depth += 1
        elif token == '}': depth -= 1
        if depth == 0 and token in ('module', 'import'):
            j = i + 1
            while j < len(tokens) and tokens[j] != ';': j += 1
            name = ''.join(tokens[i+1:j])
            if token == 'module' and name and name != ':private':
                if declared is not None: raise ValueError(f'{path}: multiple named module declarations')
                declared, interface = name, i > 0 and tokens[i-1] == 'export'
            elif token == 'import' and name: imports.append(name)
            i = j
        i += 1
    if not declared: raise ValueError(f'{path}: no literal named module declaration')
    primary = declared.split(':', 1)[0]
    return declared, interface, [primary+imp if imp.startswith(':') else imp for imp in imports]

def plan(manifest, preprocess=None):
    root = manifest.resolve().parent
    config = json.loads(manifest.read_text())
    if not isinstance(config, dict) or set(config) != {'modules'} or not isinstance(config['modules'], list) or not config['modules']:
        raise ValueError('manifest must contain a nonempty modules list')
    providers, implementations, modes = {}, [], {}
    sources = set()
    def unit(name, mode, source, interface):
        path = (root/source).resolve()
        if not path.is_file(): raise ValueError(f'missing source: {path}')
        if path in sources: raise ValueError(f'duplicate source: {path}')
        sources.add(path)
        declared, is_interface, imports = declarations(path, preprocess)
        if declared != name: raise ValueError(f'{path}: declares {declared}, manifest expects {name}')
        if is_interface != interface: raise ValueError(f'{path}: incorrect interface/implementation kind')
        return {'name': name, 'mode': mode, 'path': path, 'imports': imports}
    for item in config['modules']:
        if not isinstance(item, dict) or set(item) - {'name', 'mode', 'interface', 'partitions', 'implementations'}:
            raise ValueError('unknown module manifest field')
        name, mode = item['name'], item['mode']
        if not NAME.fullmatch(name): raise ValueError(f'invalid primary module name: {name}')
        if mode not in ('safe', 'unsafe'): raise ValueError(f'{name}: invalid mode {mode}')
        if name in modes: raise ValueError(f'duplicate module {name}')
        modes[name] = mode
        providers[name] = unit(name, mode, item['interface'], True)
        for part in item.get('partitions', []):
            if not isinstance(part, dict) or set(part) - {'name', 'mode', 'interface'}:
                raise ValueError('unknown partition manifest field')
            partname = part['name']
            if not NAME.fullmatch(partname): raise ValueError(f'invalid partition name: {partname}')
            full = name+':'+partname
            if full in providers: raise ValueError(f'duplicate partition {full}')
            # Partition mode is inherited; a conflicting override is an error.
            if part.get('mode', mode) != mode: raise ValueError(f'{full}: partition mode conflicts with primary')
            providers[full] = unit(full, mode, part['interface'], True)
        for source in item.get('implementations', []):
            implementations.append(unit(name, mode, source, False))
    order, visiting, done = [], set(), set()
    def visit(name):
        if name in done: return
        if name in visiting: raise ValueError(f'cyclic module imports involving {name}')
        visiting.add(name)
        for dep in providers[name]['imports']:
            if dep not in providers: raise ValueError(f'{name}: dependency {dep} is missing from manifest')
            visit(dep)
        visiting.remove(name); done.add(name); order.append(providers[name])
    for name in providers: visit(name)
    for item in implementations:
        for dep in item['imports']:
            if dep not in providers: raise ValueError(f'{item["name"]}: dependency {dep} is missing from manifest')
    return order, implementations

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manifest', type=pathlib.Path)
    p.add_argument('--clang', default='clang++')
    backend = p.add_mutually_exclusive_group(required=True)
    backend.add_argument('--plugin', type=pathlib.Path)
    backend.add_argument('--native', action='store_true', help='use the patched Clang frontend')
    p.add_argument('--output', default='module-build', type=pathlib.Path)
    p.add_argument('--opt-level', choices=['0', '1', '2', '3', 's', 'z'], default='2')
    a = p.parse_args()
    include = pathlib.Path(__file__).resolve().parent.parent/'include'
    preprocessing = [a.clang, '-std=c++20', '-O'+a.opt_level, '-E', '-P', '-I'+str(include)]
    if a.plugin and str(a.plugin) != 'native':
        preprocessing += ['-Dunsafe=unsafe', '-Dunsafe_fn=unsafe_fn']
    order, implementations = plan(a.manifest, preprocessing)
    compiler = pathlib.Path(shutil.which(a.clang) or a.clang).resolve()
    plugin = a.plugin.resolve() if a.plugin else None
    inputs = {str(a.manifest.resolve()): digest(a.manifest), str(compiler): digest(compiler)}
    for item in order + implementations:
        inputs[str(item['path'])] = digest(item['path'])
    if plugin and plugin.is_file(): inputs[str(plugin)] = digest(plugin)
    for name in inputs:
        if any(pathlib.Path(name).is_relative_to(target)
               for target in (a.output.absolute(), a.output.resolve())):
            raise ValueError('output directory must not contain source inputs or the compiler')
    version = subprocess.check_output([a.clang, '--version'], text=True)
    # Failed compilation never changes the published generation. Existing
    # generations remain available to readers already using their real paths.
    with generation(a.output) as out:
        policy = out/'module-safety-policy.json'
        modes = {item['name'].split(':', 1)[0]: item['mode'] for item in order}
        policy.write_text(json.dumps({'version': 1, 'modules': modes}, indent=2)+'\n')
        base = [a.clang, '-std=c++20', '-O'+a.opt_level, '-I'+str(include), '-fprebuilt-module-path='+str(out)]
        def checked(item):
            if a.native:
                return base + ['-fmodule-'+item['mode'], '-fmodule-safety-policy='+str(policy)]
            return base + ['-Xclang', '-load', '-Xclang', str(plugin), '-Xclang', '-add-plugin', '-Xclang', 'module-safety', '-Xclang', '-plugin-arg-module-safety', '-Xclang', item['mode'], '-Xclang', '-plugin-arg-module-safety', '-Xclang', 'policy='+str(policy)]
        def compile_source(item, tail, depfile):
            subprocess.run(checked(item) + ['-MD', '-MF', str(depfile)] + tail, check=True)
            # Clang make dependencies quote spaces/backslashes. Record inputs
            # from actual preprocessing, including transitive system headers.
            dependencies = depfile.read_text().replace('\\\n', '').partition(':')[2]
            for name in shlex.split(dependencies):
                path = pathlib.Path(name).resolve()
                if path.is_file():
                    old = inputs.setdefault(str(path), digest(path))
                    if old != digest(path): raise ValueError(f'input changed during build: {path}')
        for item in order:
            pcm = out/(item['name'].replace(':', '-')+'.pcm')
            compile_source(item, ['--precompile', str(item['path']), '-o', str(pcm)], pcm.with_suffix('.d'))
            progress = ['-fno-finite-loops'] if item['mode'] == 'safe' else []
            subprocess.run([a.clang, '-std=c++20', '-O'+a.opt_level, '-fprebuilt-module-path='+str(out)] + progress + ['-c', str(pcm), '-o', str(pcm.with_suffix('.o'))], check=True)
        for i, item in enumerate(implementations):
            obj = out/(item['name']+f'.impl{i}.o')
            compile_source(item, ['-c', str(item['path']), '-o', str(obj)], obj.with_suffix('.d'))
        info = {'version': 1, 'compiler': version, 'optimization': a.opt_level,
                'modes': modes, 'inputs': inputs,
                'artifacts': {path.name: digest(path) for path in sorted(out.iterdir()) if path.is_file()}}
        (out/'build-info.json').write_text(json.dumps(info, indent=2, sort_keys=True)+'\n')
        verify(out)
    print(f'Built {len(order)} interfaces/partitions and {len(implementations)} implementation units; published {a.output}')

if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
