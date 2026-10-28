#!/usr/bin/env python3
"""Physical zero-niche choice, virtual tag, relocation/drop/EH and PCM ABI."""
import json,os,pathlib,subprocess,tempfile
ROOT=pathlib.Path(__file__).resolve().parent.parent
CLANG=pathlib.Path(os.environ.get('MODULE_SAFETY_CLANG',ROOT/'llvm-build/bin/clang'))
BODY=r'''
unsigned drops=0u;
unsigned count() safe {unsafe {return drops;}}
struct [[safety::niche_zero]] Token {
 unsigned* unsafe pointer;
 unsigned __phantom_data;
 explicit Token(unsigned value) safe :pointer(nullptr) {unsafe {pointer=new unsigned(value);}}
 Token(const Token&)=delete;
 Token(Token&&)=delete;
 ~Token() safe {unsafe {delete pointer;++drops;}}
 unsigned get(const self^) safe {unsafe {return *self->pointer;}}
};
choice Maybe {default none,some(Token);};
choice Reverse {some(Token),default none;};
struct Forward;
struct [[safety::niche_zero]] Forward {void* unsafe p;};
choice ForwardChoice {default none,some(Forward);};
template<class T> struct [[safety::niche_zero]] TemplateSlot {void* unsafe p;};
template<class T> struct TemplateSlot<T*> {void* unsafe p;};
choice PrimaryChoice {default none,some(TemplateSlot<unsigned>);};
choice PartialChoice {default none,some(TemplateSlot<unsigned*>);};
struct [[clang::annotate("safecpp.niche.zero")]] Forged {void* unsafe p;};
choice ForgedChoice {default none,some(Forged);};
static_assert(sizeof(ForwardChoice)==sizeof(void*));
static_assert(sizeof(PrimaryChoice)==sizeof(void*));
static_assert(sizeof(PartialChoice)==2*sizeof(void*));
static_assert(sizeof(ForgedChoice)==2*sizeof(void*));
struct Mixed {unsigned* pointer;unsigned other;};
choice Ordinary {default none,some(Mixed);};
static_assert(sizeof(Token)==sizeof(void*));
static_assert(sizeof(Maybe)==sizeof(Token));
static_assert(sizeof(Reverse)==sizeof(Token));
static_assert(sizeof(Ordinary)>sizeof(Mixed));
unsigned watch(const Maybe^ value) safe {
 return match(*value) -> unsigned {.some(^x)=>x->get();.none=>0u;};
}
unsigned watch_reverse(const Reverse^ value) safe {
 return match(*value) -> unsigned {.some(^x)=>x->get();.none=>0u;};
}
unsigned drop_evals=0u;
unsigned evaluations() safe {unsafe {return drop_evals;}}
Maybe^/a once/(a)(Maybe^/a value) safe {unsafe {++drop_evals;}return rel value;}
struct [[safety::niche_zero]] ThrowToken {
 unsigned* unsafe p;
 explicit ThrowToken(unsigned v) safe :p(nullptr) {unsafe {p=new unsigned(v);}}
 ThrowToken(const ThrowToken&)=delete;
 ~ThrowToken() noexcept(false) safe {unsafe {delete p;++drops;throw 17u;}}
};
choice ThrowChoice {default none,some(ThrowToken);};
unsigned throwing_drop() safe {
 unsigned start=count();
 try {ThrowChoice value=.some(ThrowToken(17u));drp ^value;}
 catch(unsigned error) {return error==17u && count()==start+1u ? 0u : 1u;}
 return 2u;
}
unsigned run() safe {
 unsigned start=count();
 {
  Maybe empty;
  Reverse reverse_empty;
  if(watch(^const empty)!=0u || watch_reverse(^const reverse_empty)!=0u) return 1u;
  Maybe a=.some(Token(11u));
  {Maybe b=rel a;if(watch(^const b)!=11u || watch(^const b)!=11u) return 2u;}
 }
 if(count()!=start+1u) return 3u;
 {Reverse r=.some(Token(21u));if(watch_reverse(^const r)!=21u) return 4u;}
 if(count()!=start+2u) return 5u;
 {Maybe m=.some(Token(23u));drp ^m;if(count()!=start+3u) return 6u;}
 if(count()!=start+3u) return 7u;
 {
  Maybe m=.some(Token(29u));
  Token x=match(m)->Token {.some(x)=>rel x;.none=>Token(0u);};
  if(x.get()!=29u) return 8u;
 }
 if(count()!=start+4u) return 9u;
 try {Maybe m=.some(Token(31u));unsafe {throw 1u;}}
 catch(unsigned) {}
 if(count()!=start+5u) return 10u;
 unsigned before=evaluations();
 {Maybe m=.some(Token(37u));drp *once(^m);}
 if(count()!=start+6u || evaluations()!=before+1u) return 11u;
 return throwing_drop()==0u ? 0u : 12u;
}
'''
with tempfile.TemporaryDirectory(prefix='circle-zero-niche-') as directory:
 d=pathlib.Path(directory);policy=d/'policy.json'
 policy.write_text(json.dumps({'version':1,'modules':{'niche':'safe'}}))
 flags=['--driver-mode=g++','-std=c++20','-fcircle-safety','-fcircle-borrow-values','-fmodule-safety-policy='+str(policy),'-resource-dir=/opt/homebrew/opt/llvm/lib/clang/22']
 def compile(args, okay=True, diagnostic=''):
  r=subprocess.run([str(CLANG)]+args,capture_output=True,text=True,timeout=120)
  assert (r.returncode==0)==okay,r.stderr
  assert 'PLEASE submit' not in r.stderr and 'frontend command failed' not in r.stderr,r.stderr
  if diagnostic:assert diagnostic in r.stderr,r.stderr
  return r
 for opt in ('-O0','-O2'):
  for sanitizer in ([],['-fsanitize=address,undefined','-fno-sanitize-recover=all']):
   options=flags+[opt]+sanitizer
   p=d/'main.cpp';binary=d/'program'
   p.write_text('#include <new>\n'+BODY+'int main() safe {return run();}\n')
   compile(options+[str(p),'-o',str(binary)])
   r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
   assert r.returncode==0,r.stderr+str(r.returncode)
   module=d/'niche.cppm';pcm=d/'niche.pcm';obj=d/'niche.o'
   module.write_text('module;\n#include <new>\nexport module niche;export {\n'+BODY+'}\n')
   compile(options+['--precompile',str(module),'-o',str(pcm)])
   compile(options+['-c',str(pcm),'-o',str(obj)])
   p.write_text('import niche;int main() {return run();}\n')
   compile(options+['-fmodule-file=niche='+str(pcm),str(p),str(obj),'-o',str(binary)])
   r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
   assert r.returncode==0,r.stderr+str(r.returncode)
   negatives=(
    ('struct [[safety::niche_zero]] UnsafeToken {void* unsafe p;~UnsafeToken() unsafe {}};choice UnsafeChoice {default none,some(UnsafeToken);};void bad() safe {UnsafeChoice x;}', 'unsafe or unclassified'),
    ('unsigned bad() safe {Maybe a=.some(Token(1u));Maybe b=rel a;return watch(^const a);}', 'moved'),
    ('unsigned bad() safe {Maybe a=.some(Token(1u));drp *once(^a);return watch(^const a);}', 'moved'),
    ('Token^/a token_once/(a)(Token^/a x) safe {return rel x;} void bad() safe {Token a(1u);drp *token_once(^a);}', 'destination identity'),
    ('unsigned bad() safe {Maybe a=.some(Token(1u));const Maybe^ r=^const a;drp a;return watch(r);}', 'borrow'),
    ('const Token^/a bad/(a)(const Token^/a anchor) safe {Maybe local=.some(Token(1u));return match(local)->const Token^ {.some(^x)=>x;.none=>anchor;};}', 'lifetime'),
   )
   for text,diagnostic in negatives:
    p.write_text('import niche;'+text)
    compile(options+['-fmodule-file=niche='+str(pcm),'-fsyntax-only',str(p)],False,diagnostic)
   # A null payload cannot silently become the empty alternative. This
   # representation contract is checked even inside explicit unsafe code.
   for global_init in (False,True):
    prefix='struct [[safety::niche_zero]] Raw {void* unsafe p;};choice NullTest {default none,some(Raw);};'
    expression='NullTest value=.some(Raw{nullptr});'
    p.write_text(prefix+(expression+'int main() safe {return 0;}' if global_init else 'int main() safe {unsafe {'+expression+'}return 0;}'))
    compile(options+[str(p),'-o',str(binary)])
    r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
    assert r.returncode==-6,(r.returncode,r.stderr)
    assert 'runtime error:' not in r.stderr and 'ERROR: AddressSanitizer' not in r.stderr,r.stderr

print('Zero-niche pointer payload: size, both alternative orders, empty/some match, relocation, borrowed drop, exact destruction and EH; local/PCM O0/O2 plain and ASan/UBSan, twenty-four safety refusals and eight local/global null-payload panics passed')
