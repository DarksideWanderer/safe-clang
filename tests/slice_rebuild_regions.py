#!/usr/bin/env python3
"""A slice rebuilt from one slice's data pointer and length borrows that slice.

The rebuilt slice covers exactly the same bytes as its source, so it borrows
the same region with the same extent: the result may be returned as a borrow
of the source, may be rebuilt again, and a live exclusive rebuild still
conflicts with its source. Taking either half from another place, using a
length that is not the slice's own stays refused.

A slice may also be built from a raw pointer and a count. Its extent is then a
claim of the code that builds it: allowed where the checker does not verify the
body's own claims (an unsafe function), or where the body hands the extent on
to its callers, and then every checked call has to place it (the length of one
slice, or a counted suffix of a known array, or an independently counted
subrange proven by a runtime bounds check) while every call in unchecked code
reconnects the result to the provenance of its own arguments.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'

API = "\n".join([
    'const [unsigned char; dyn]^ identity(const [unsigned char; dyn]^ s) safe {',
    '  unsafe { return ^*__slice_pointer((*s)~as_pointer, (*s)~length); }',
    '}',
    'const [unsigned char; dyn]^ chained(const [unsigned char; dyn]^ s) safe {',
    '  auto once = identity(s);',
    '  unsafe { return ^*__slice_pointer((*once)~as_pointer, (*once)~length); }',
    '}',
    '[unsigned char; dyn]^ writing([unsigned char; dyn]^ s) safe {',
    '  unsafe { return ^*__slice_pointer((*s)~as_pointer, (*s)~length); }',
    '}',
    'const [char; dyn]^ as_chars(const [unsigned char; dyn]^ s) safe {',
    '  unsafe { return ^*__slice_pointer(reinterpret_cast<const char*>((*s)~as_pointer), (*s)~length); }',
    '}',
    'unsigned long count(const [unsigned char; dyn]^ s) safe { return (*s)~length; }',
    'unsigned long count_chars(const [char; dyn]^ s) safe { return (*s)~length; }',
    'struct Buffer {',
    '  unsigned char bytes[4];',
    '  const unsigned char* data(const self^) safe { return self->bytes; }',
    '  unsigned long size(const self^) safe { return 4u; }',
    '};',
    'const [unsigned char; dyn]^/a slice_of_parts/(a)(const unsigned char* p, unsigned long n) unsafe {',
    '  return ^*__slice_pointer(p, n);',
    '}',
    # The official standard-library shape: a checked body hands the extent to
    # its callers, and each checked call places it.
    'const [unsigned char; dyn]^/a slice_deferred/(a)(const unsigned char* p, unsigned long n) {',
    '  return ^*__slice_pointer(p, n);',
    '}',
    'unsigned long counted_suffix() safe {',
    '  unsigned char local[2] = {1u, 2u};',
    '  auto part = slice_deferred(local, 2u);',
    '  return static_cast<unsigned long>(part[1u]);',
    '}',
    'unsigned long rebuilt_by_call(const [unsigned char; dyn]^ s) safe {',
    '  auto same = slice_deferred((*s)~as_pointer, (*s)~length);',
    '  return static_cast<unsigned long>(same[0u]);',
    '}',
    'unsigned long suffix_from_array() safe {',
    '  unsigned char local[4] = {\'a\', \'b\', \'c\', \'d\'};',
    '  auto tail = slice_deferred(&local[1], 3u);',
    '  return static_cast<unsigned long>(tail[0u]) + static_cast<unsigned long>(tail[2u]);',
    '}',
    'unsigned long prefix_from_slice() safe {',
    '  unsigned char local[4] = {\'a\', \'b\', \'c\', \'d\'};',
    '  auto source = slice_deferred(local, 4u);',
    '  auto prefix = slice_deferred(&source[0u], 2u);',
    '  return static_cast<unsigned long>(prefix[0u]) + static_cast<unsigned long>(prefix[1u]);',
    '}',
    'unsigned long subrange_from_slice() safe {',
    '  unsigned char local[4] = {\'a\', \'b\', \'c\', \'d\'};',
    '  auto source = slice_deferred(local, 4u);',
    '  auto part = slice_deferred(&source[1u], 2u);',
    '  return static_cast<unsigned long>(part[0u]) + static_cast<unsigned long>(part[1u]);',
    '}',
    'unsigned long suffix_from_slice() safe {',
    '  unsigned char local[4] = {\'a\', \'b\', \'c\', \'d\'};',
    '  auto source = slice_deferred(local, 4u);',
    '  auto part = slice_deferred(&source[1u], (*source)~length - 1u);',
    '  return static_cast<unsigned long>(part[0u]) + static_cast<unsigned long>(part[2u]);',
    '}',
    'unsigned long object_data_size() safe {',
    '  Buffer buffer{{' + "'a', 'b', 'c', 'd'" + '}};',
    '  auto all = slice_deferred(buffer.data(), buffer.size());',
    '  return static_cast<unsigned long>(all[0u]) + static_cast<unsigned long>(all[3u]);',
    '}',
    'unsigned long runtime_suffix(const [unsigned char; dyn]^ source, unsigned long start) safe {',
    '  auto part = slice_deferred(&source[start], (*source)~length - start);',
    '  return static_cast<unsigned long>(part[0u]);',
    '}',
    # A runtime length is admissible after an explicit checked bound: the
    # safe subscript proves the start, and the false edge of the second
    # guard proves that the independent count fits in the remaining suffix.
    'unsigned long runtime_length(const [unsigned char; dyn]^ source, unsigned long start, unsigned long count) safe {',
    '  if (start >= (*source)~length) return 0ul;',
    '  if (count > (*source)~length - start) return 0ul;',
    '  auto part = slice_deferred(&source[start], count);',
    '  return static_cast<unsigned long>(part[0u]);',
    '}',
    ''])
PROGRAM = "\n".join([
    'unsigned char buffer[4] = {\'a\', \'b\', \'c\', \'d\'};',
    'int main() safe {',
    '  unsigned seen = 0u;',
    '  unsafe {',
    '    const [unsigned char; dyn]^ src = ^*__slice_pointer(static_cast<const unsigned char*>(buffer), 4u);',
    '    auto same = identity(src);',
    '    auto deeper = chained(src);',
    '    const [char; dyn]^ chars = as_chars(src);',
    '    if (count(same) != 4u || count(deeper) != 4u || count_chars(chars) != 4u) return 1;',
    '    seen = static_cast<unsigned>(same[0u]) + static_cast<unsigned>(deeper[3u]) +',
    '           static_cast<unsigned>(chars[1u]);',
    '    [unsigned char; dyn]^ target = writing(^*__slice_pointer(buffer + 0u, 4u));',
    '    target[2u] = \'Z\';',
    '    if (buffer[2u] != \'Z\') return 2;',
    '    auto rebuilt = slice_of_parts(buffer, 4u);',
    '    if (count(rebuilt) != 4u || rebuilt[1u] != \'b\') return 4;',
    '    if (counted_suffix() != 2ul || rebuilt_by_call(src) != static_cast<unsigned long>(\'a\')) return 5;',
    '    if (suffix_from_array() != static_cast<unsigned long>(\'b\' + \'d\')) return 6;',
    '    if (prefix_from_slice() != static_cast<unsigned long>(\'a\' + \'b\')) return 7;',
    '    if (subrange_from_slice() != static_cast<unsigned long>(\'b\' + \'c\')) return 8;',
    '    if (suffix_from_slice() != static_cast<unsigned long>(\'b\' + \'d\')) return 9;',
    '    if (object_data_size() != static_cast<unsigned long>(\'a\' + \'d\')) return 10;',
    '    if (runtime_suffix(src, 1u) != static_cast<unsigned long>(\'b\')) return 11;',
    '    if (runtime_length(src, 1u, 2u) != static_cast<unsigned long>(\'b\')) return 12;',
    '  }',
    '  return seen == static_cast<unsigned>(\'a\' + \'d\' + \'b\') ? 0 : 3;',
    '}',
    ''])
REFUSALS = [
    # The length must be the slice's own length, not another runtime value.
    ('const [unsigned char;dyn]^ half(const [unsigned char;dyn]^ s, unsigned long n) safe '
     '{ unsafe { return ^*__slice_pointer((*s)~as_pointer, n); } }',
     'returned borrow has unknown lifetime provenance'),
    ('const [unsigned char;dyn]^ one(const [unsigned char;dyn]^ s) safe '
     '{ unsafe { return ^*__slice_pointer((*s)~as_pointer, 1u); } }',
     'returned borrow has unknown lifetime provenance'),
    # A checked call has to place the extent of a raw-parts slice result: a
    # pointer and a count that name no known allocation stay refused.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad(const unsigned char* p, unsigned long n) safe '
     '{ auto s = raw_slice(p, n); return static_cast<unsigned long>((*s)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A count beyond the array the pointer names is not that extent.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad() safe { unsigned char local[4] = {};'
     ' auto s = raw_slice(local, 9ul); return static_cast<unsigned long>((*s)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # An indirect call cannot show the pair, so a checked call stays refused.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad() safe { unsigned char local[4] = {}; auto fn = &raw_slice;'
     ' auto s = fn(local, 4ul); return static_cast<unsigned long>((*s)~length); }',
     'slice extent of an indirect call must be placed at the call site'),
    # A suffix that runs past the array is not inside it.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad() safe { unsigned char local[4] = {};'
     ' auto s = raw_slice(&local[3], 3ul); return static_cast<unsigned long>((*s)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A runtime count from an unknown slice cannot name a safe independent
    # subrange without a runtime bounds check.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad(const [unsigned char;dyn]^ s) safe {'
     ' auto part = raw_slice((*s)~as_pointer, 2u);'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A runtime start checks the subscript, but the count must still be the
    # corresponding suffix length rather than the whole source length.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad(const [unsigned char;dyn]^ s, unsigned long i) safe {'
     ' auto part = raw_slice(&s[i], (*s)~length);'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A runtime count needs its own proven bound; the checked subscript only
    # proves the start.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad(const [unsigned char;dyn]^ s, unsigned long i,'
     ' unsigned long n) safe { auto part = raw_slice(&s[i], n);'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A bound fact is invalidated by a write between the guard and the slice.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad(const [unsigned char;dyn]^ s, unsigned long i,'
     ' unsigned long n) safe { if (i >= (*s)~length) return 0;'
     ' if (n > (*s)~length - i) return 0; n = 1ul;'
     ' auto part = raw_slice(&s[i], n);'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A constant subrange must remain inside the source slice's known extent.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' unsigned long bad() safe { unsigned char local[4] = {};'
     ' auto s = raw_slice(local, 4u); unsigned long result = 0;'
     ' auto part = raw_slice(&s[3u], 2u);'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # The data pointer and size must belong to the same receiver object.
    ('const [unsigned char;dyn]^/a raw_slice/(a)(const unsigned char* p, unsigned long n) '
     '{ return ^*__slice_pointer(p, n); }'
     ' struct Buffer { unsigned char bytes[4];'
     ' const unsigned char* data(const self^) safe { return self->bytes; } };'
     ' struct Other { unsigned long size(const self^) safe { return 2u; } };'
     ' unsigned long bad() safe { Buffer b{}; Other o{};'
     ' auto part = raw_slice(b.data(), o.size());'
     ' return static_cast<unsigned long>((*part)~length); }',
     'slice extent must be the length of a slice or a counted suffix of a known array'),
    # A local is not a source a caller can supply either.
    ('const [unsigned char;dyn]^/a raw_local/(a)(unsigned long n) unsafe '
     '{ unsigned char local[4] = {};'
     ' return ^*__slice_pointer(static_cast<const unsigned char*>(local), n); }',
     'raw slice extent is not proven within a known allocation'),
    # Handing a local's storage to a raw-parts slice constructor and returning
    # the result is refused where the result's owner would be the local.
    ('const [unsigned char;dyn]^/a slice_of/(a)(const unsigned char* p, unsigned long n) unsafe '
     '{ return ^*__slice_pointer(p, n); }'
     ' const [unsigned char;dyn]^/a leak/(a)() safe { unsigned char local[4] = {};'
     ' unsafe { return slice_of(local, 4u); } }',
     'generative return lifetime cannot expose a local or input-bound owner'),
    # A live exclusive rebuild is an exclusive borrow of the same region.
    ('char conflict(const [unsigned char;dyn]^ s) safe { char out; '
     'unsafe { [unsigned char;dyn]^ m = ^*__slice_pointer(const_cast<unsigned char*>((*s)~as_pointer), (*s)~length); } '
     'out = static_cast<char>(s[0u]); m[0u] = \'q\'; return out; }',
     'access conflicts with a live exclusive borrow'),
    # Sharing cannot be laundered into mutability at a call.
    ('void take([unsigned char;dyn]^ m) safe {} '
     'void handout(const [unsigned char;dyn]^ s) safe { take(s); }',
     'no matching function'),
]
with tempfile.TemporaryDirectory(prefix='slice-rebuild-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'slice_api': 'safe'}}))
    flags = ['--driver-mode=g++', '-std=c++20', '-fcircle-safety', '-fcircle-borrow-values',
             '-fmodule-safety-policy='+str(policy), '-I'+str(root/'include'),
             '-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
    source = tmp/'consumer.cpp'
    for opt in ('-O0', '-O2'):
        for san in ([], ['-fsanitize=address,undefined', '-fno-sanitize-recover=all']):
            options = flags + [opt] + san
            module = tmp/'api.cppm'
            pcm = tmp/'api.pcm'
            module_object = tmp/'api.o'
            module.write_text('export module slice_api;\nexport {\n'+API+'\n}\n')
            for arguments in (['--precompile', str(module), '-o', str(pcm)],
                              ['-c', str(pcm), '-o', str(module_object)]):
                result = subprocess.run([str(clang)]+options+arguments, capture_output=True, text=True)
                assert result.returncode == 0, result.stderr
            source.write_text('import slice_api;\n'+PROGRAM)
            binary = tmp/'run'
            result = subprocess.run([str(clang)]+options+['-fmodule-file=slice_api='+str(pcm),
                                    str(source), str(module_object), '-o', str(binary)],
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            executed = subprocess.run([str(binary)], capture_output=True, text=True)
            assert executed.returncode == 0, (executed.returncode, executed.stderr)
    for body, diagnostic in REFUSALS:
        source.write_text(body)
        result = subprocess.run([str(clang)]+flags+['-fsyntax-only', str(source)],
                                capture_output=True, text=True)
        assert result.returncode != 0 and diagnostic in result.stderr, (body, result.stderr)
        assert 'PLEASE submit' not in result.stderr, result.stderr
print('Slice rebuild: same-place data+length reborrows and runtime-checked '
      'independent subranges across local/PCM O0/O2 plain ASan/UBSan, '
      '{} refusals passed'.format(len(REFUSALS)))
