#!/usr/bin/env python3
"""An audited sequence's element storage borrows only from its declared region.

The runtime containers already execute their element reads; this checks the
contract itself: what a storage field may claim, which result contracts an
element read may satisfy, and that a read still cannot outlive the region it
was adopted from. A local definition and a producer PCM are both exercised.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
clang = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root/'llvm-build/bin/clang'

API = "\n".join([
    'struct Owner { unsigned x=1u, y=2u; };',
    'struct View { const unsigned& ref; };',
    'template <class T, class Owner>',
    'class __attribute__((annotate("safecpp.unsafe.moved.drop"),',
    '                     annotate("safecpp.unsafe.borrowed.sequence"))) Seq {',
    '  const Owner& owner_;',
    '  __attribute__((annotate("safecpp.unsafe.sequence.storage"))) T* values_ = nullptr;',
    '  unsigned count_ = 0u;',
    'public:',
    '  __attribute__((annotate("safecpp.stores.borrow:owner"))) explicit Seq(const Owner& owner)',
    '      : owner_(owner) {}',
    '  __attribute__((annotate("safecpp.borrow.this"))) T at(unsigned i) const',
    '    { unsafe { return values_[i]; } }',
    '  __attribute__((annotate("safecpp.borrow.this"))) T& mut_at(unsigned i)',
    '    { unsafe { return values_[i]; } }',
    '  unsigned size() const { return count_; }',
    '};',
    ''])
POSITIVE = "\n".join([
    'unsigned read(const Owner& owner) safe {',
    '  Seq<View,Owner> seq(owner);',
    '  unsigned total = seq.size();',
    '  { auto value = seq.at(0u); total += value.ref; }',
    '  { auto& reference = seq.mut_at(1u); total += reference.ref; }',
    '  return total;',
    '}',
    ''])
# Declarations that claim element storage without the contract that would give
# the claim a meaning.
DECLARATION_REFUSALS = [
    ('struct LooseView { const unsigned& ref; }; '
     'struct Loose { const unsigned& owner_; '
     '__attribute__((annotate("safecpp.unsafe.sequence.storage"))) LooseView* values_ = nullptr; '
     'Loose(const unsigned& owner) : owner_(owner) {} };',
     'element storage requires an audited borrowed sequence'),
    ('struct PlainView { const unsigned& ref; }; '
     'class __attribute__((annotate("safecpp.unsafe.borrowed.sequence"))) Plain { '
     'const unsigned& owner_; '
     '__attribute__((annotate("safecpp.unsafe.sequence.storage"))) unsigned* values_ = nullptr; '
     '__attribute__((annotate("safecpp.stores.borrow:owner"))) explicit Plain(const unsigned& owner) '
     ': owner_(owner) {} };',
     'element storage requires borrow-carrying elements'),
    # The runtime containers are templates, so the claim is also checked on a
    # dependency-parameterised declaration that omits the stored region.
    ('struct Plain2View { const unsigned& ref; }; '
     'template <class T> '
     'class __attribute__((annotate("safecpp.unsafe.borrowed.sequence"))) Plain2 { '
     'const unsigned& owner_; '
     '__attribute__((annotate("safecpp.unsafe.sequence.storage"))) T* values_ = nullptr; '
     'public: explicit Plain2(const unsigned& owner) : owner_(owner) {} }; '
     'unsigned probe(const unsigned& owner) safe { Plain2<Plain2View> value(owner); return 0u; }',
     'element storage requires a declared stored borrow region'),
]
# Method bodies whose element read does not satisfy a result contract the
# sequence's region can support.
MEMBER_REFUSALS = [
    ('View leak(unsigned i) const { unsafe { return values_[i]; } }',
     'borrow result without a checked lifetime contract'),
]
# An instantiated member whose element read is claimed to borrow an unrelated
# parameter's region instead of the receiver's.
PICK = ('__attribute__((annotate("safecpp.borrow.from:owner"))) T pick(const Owner& owner, '
        'unsigned i) const { unsafe { return values_[i]; } }')
PICK_USE = ('unsigned misuse(const Owner& owner) safe { Seq<View,Owner> seq(owner); '
            'auto value = seq.pick(owner, 0u); return value.ref; }')
# Uses of the public interface whose element borrow does not respect the region
# it was adopted from.
CONSUMER_REFUSALS = [
    ('const unsigned& escape() safe { '
     'auto value = Seq<View,Owner>(Owner{}).at(0u); return value.ref; }',
     'borrow'),
    ('unsigned conflict(Owner& owner) safe { Seq<View,Owner> seq(owner); '
     'auto value = seq.at(0u); owner.x = 5u; return value.ref; }',
     'borrow'),
]


def compile_source(tmp, flags, text, extra=()):
    source = tmp/'consumer.cpp'
    source.write_text(text)
    return subprocess.run([str(clang)]+flags+list(extra)+['-fsyntax-only', str(source)],
                          capture_output=True, text=True)


def api_with(member):
    """The sequence with one more member inside it."""
    return API.replace('  unsigned size() const { return count_; }',
                       '  unsigned size() const { return count_; }\n  ' + member)


with tempfile.TemporaryDirectory(prefix='sequence-storage-') as directory:
    tmp = pathlib.Path(directory)
    policy = tmp/'policy.json'
    policy.write_text(json.dumps({'version': 1, 'modules': {'seq_api': 'safe'}}))
    common = ['--driver-mode=g++', '-std=c++20', '-fmodule-safety-policy='+str(policy)]
    local = common + ['-fcircle-safety']
    checked = common + ['-fmodule-safe']

    result = compile_source(tmp, local, API + POSITIVE)
    assert result.returncode == 0, result.stderr
    for body, diagnostic in DECLARATION_REFUSALS:
        result = compile_source(tmp, local, body)
        assert result.returncode != 0 and diagnostic in result.stderr, (body, result.stderr)
    cases = [(api_with(body), diagnostic) for body, diagnostic in MEMBER_REFUSALS]
    cases += [(API + body, diagnostic) for body, diagnostic in CONSUMER_REFUSALS]
    cases += [(api_with(PICK) + PICK_USE, 'returned reference does not borrow from the declared lifetime source')]
    for text, diagnostic in cases:
        result = compile_source(tmp, local, text)
        assert result.returncode != 0 and diagnostic in result.stderr, (text, result.stderr)
        assert 'PLEASE submit' not in result.stderr, result.stderr

    module = tmp/'api.cppm'
    module.write_text('export module seq_api;\nexport {\n'+API+'\n}\n')
    pcm = tmp/'api.pcm'
    result = subprocess.run([str(clang)]+checked+['--precompile', str(module), '-o', str(pcm)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    imported = ['-fmodule-file=seq_api='+str(pcm)]
    result = compile_source(tmp, checked, 'import seq_api;\n'+POSITIVE, imported)
    assert result.returncode == 0, result.stderr
    for body, diagnostic in CONSUMER_REFUSALS:
        result = compile_source(tmp, checked, 'import seq_api;\n'+body, imported)
        assert result.returncode != 0 and diagnostic in result.stderr, (body, result.stderr)
        assert 'PLEASE submit' not in result.stderr, result.stderr
print('Audited element storage: region-carrying element reads accepted locally and across a PCM, 7 contract refusals passed')
