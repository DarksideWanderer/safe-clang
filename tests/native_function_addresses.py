#!/usr/bin/env python3
"""Taking an address preserves the effect; only invocation needs permission."""
import pathlib,subprocess,tempfile,json,os
root=pathlib.Path(__file__).resolve().parents[1]
clang=root/'llvm-build/bin/clang'
api='''unsigned twice(unsigned value) unsafe {return value*2u;}
const unsigned^/a checked/(a)(const unsigned^/a input) unsafe {return input;}
unsigned wrapper(unsigned value) safe {auto callback=&twice;unsafe {return callback(value);}}
template<class T> unsigned audited(T value) safe {unsafe {return ::twice(value);}}
struct Virtual {unsigned value=3u;Virtual() noexcept safe=default;virtual unsigned take() && noexcept safe {return value;}};
struct Derived final:Virtual {Derived() noexcept safe=default;unsigned take() && noexcept safe override {return value+1u;}};
struct Thrower {unsigned value=1u;Thrower() noexcept safe=default;unsigned fail() && noexcept(false) safe {throw 1u;}};
unsigned indirect_value() safe {Derived d;const auto p=&Derived::take;return (static_cast<Derived&&>(d).*p)();}
unsigned indirect_throw() safe {Thrower t;const auto p=&Thrower::fail;try {(static_cast<Thrower&&>(t).*p)();}catch(...){return 0u;}return 1u;}
unsigned virtual_value() safe {Derived d;return static_cast<Virtual&&>(d).take();}
'''
main='''int main() safe {
 auto callback=&twice;
 unsigned input=21u;
 auto borrowed=&checked;
 unsafe {auto loan=borrowed(^const input);unsigned result=callback(*loan);}
 return result==42u && wrapper(21u)==42u && audited(21u)==42u &&
        indirect_value()==4u && indirect_throw()==0u &&
        virtual_value()==4u?0:1;
}
'''
negative=[
 ('template<class T> unsigned bad(T value) safe {return ::twice(value);}', 'call to unsafe or unclassified function'),
 ('template<auto Target> struct Tag {};struct Erased {unsigned (*pointer)(unsigned)=nullptr;template<auto Target> static unsigned invoke(unsigned value) safe {return Target(value);}template<auto Target> Erased(Tag<Target>) safe {unsafe {pointer=&invoke<Target>;}}};void bad() safe {Erased value(Tag<twice>{});}', 'call to unsafe or unclassified function'),
 ('unsigned bad() safe {auto callback=&twice;return callback(1u);}', 'indirect or unresolved call'),
 ('unsigned bad() safe {return twice(1u);}', 'call to unsafe or unclassified function'),
 ('void bad() safe {auto callback=&twice;unsafe {auto nested=[callback] {return callback(1u);};}}', 'indirect or unresolved call'),
 ('unsigned bad() safe {Derived d;const auto p=&Derived::take;unsigned value=(static_cast<Derived&&>(d).*p)();return d.value;}', 'use of a moved value'),
 ('unsigned bad() safe {Derived d;static_cast<Virtual&&>(d).take();return d.value;}', 'use of a moved value'),
 ('unsigned bad() safe {Derived d;Virtual&& base=static_cast<Derived&&>(d);return static_cast<Virtual&&>(base).take();}', 'consume through a borrow'),
 ('unsigned bad() safe {Thrower t;const auto p=&Thrower::fail;try {(static_cast<Thrower&&>(t).*p)();}catch(...){return t.value;}return 0u;}', 'use of a moved value'),
 ('unsigned bad() safe {Derived d;auto p=&Derived::take;p=&Derived::take;return (static_cast<Derived&&>(d).*p)();}', 'indirect or unresolved call'),
 ('unsigned bad(Derived& d,unsigned (Derived::*p)() &&) safe {return (static_cast<Derived&&>(d).*p)();}', 'indirect or unresolved call'),
 ('struct Open {unsigned value=1u;Open() noexcept safe=default;virtual unsigned take() && noexcept safe {return value;}};struct Child:Open {Child() noexcept safe=default;unsigned take() && noexcept safe override {return value+1u;}};unsigned bad() safe {Child d;const auto p=&Open::take;return (static_cast<Open&&>(d).*p)();}', 'unchecked member-pointer application'),
 ('struct Field {unsigned x=1u;};unsigned bad(Field& f,unsigned Field::*p) safe {return f.*p;}', 'unchecked member-pointer application'),
 ('void bad() safe {using Checked=unsigned(unsigned) safe;Checked* callback=&twice;}', 'error:'),
 ('const unsigned^/a bad/(a)(const unsigned^/a input) unsafe {unsigned local=1u;return ^const local;}', 'returned reference does not borrow from the declared lifetime source'),
 ('void bad() safe {using Erased=const unsigned^/static(const unsigned^) unsafe;auto callback=reinterpret_cast<Erased*>(&checked);}', 'static lifetime contracts'),
]
with tempfile.TemporaryDirectory(prefix='native-addresses-') as td:
 d=pathlib.Path(td);p=d/'test.cpp';policy=d/'policy.json';policy.write_text(json.dumps({'version':1,'modules':{}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 for opt in ('-O0','-O2'):
  for sanitized in (False,True):
   options=flags+[opt]+(['-fsanitize=address,undefined','-fno-sanitize-recover=all'] if sanitized else [])
   p.write_text(api+main);exe=d/'run';x=subprocess.run([str(clang)]+options+[str(p),'-o',str(exe)],capture_output=True,text=True);assert x.returncode==0,x.stderr
   x=subprocess.run([str(exe)],capture_output=True,text=True,env=dict(os.environ,ASAN_OPTIONS='detect_stack_use_after_return=1'));assert x.returncode==0,x.stderr
   for source,diagnostic in negative:
    p.write_text(api+source);x=subprocess.run([str(clang)]+options+['-fsyntax-only',str(p)],capture_output=True,text=True)
    assert x.returncode!=0 and diagnostic in x.stderr and 'PLEASE submit' not in x.stderr,x.stderr
print('Unsafe function addresses preserve invocation and lifetime contracts, and a visible member-function pointer keeps receiver/throw contracts: O0/O2 plain ASan/UBSan, 4 runs and {} refusals passed'.format(4*len(negative)))
