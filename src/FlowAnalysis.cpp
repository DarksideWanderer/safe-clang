#include "FlowAnalysis.h"
#include "SafetyContracts.h"
#include "SafetyTraversal.h"
#include "clang/AST/Attr.h"
#ifdef MODULE_SAFETY_BUILTIN
#include "clang/AST/CircleSafety.h"
#include "clang/AST/CircleFunctionRelation.h"
#endif
#include "clang/AST/ParentMapContext.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Analysis/CFG.h"
#include <algorithm>
#include <deque>
#include <map>
#include <optional>
#include <set>
using namespace clang;
namespace modulesafety {
namespace {
using Vars = std::set<const VarDecl *>;
using FieldPath = std::vector<const FieldDecl *>;
bool prefixPath(const FieldPath &A, const FieldPath &B) {
  return A.size() <= B.size() && std::equal(A.begin(), A.end(), B.begin());
}
bool implicitObjectMethod(const FunctionDecl *F) {
  auto *M = dyn_cast_or_null<CXXMethodDecl>(F);
  return M && M->isImplicitObjectMemberFunction();
}
bool implicitRuntimeThrow(const Expr *E) {
  if (auto *B = dyn_cast_or_null<BinaryOperator>(E);
      B && BinaryOperator::getOpcodeStr(B->getOpcode()) == ":=") {
    auto *R = B->getLHS()->getType()->getAsCXXRecordDecl();
    auto *D = R && R->hasDefinition() ? R->getDefinition()->getDestructor() : nullptr;
    return D && !D->getType()->castAs<FunctionProtoType>()->isNothrow();
  }
  if (auto *Cast = dyn_cast_or_null<CXXDynamicCastExpr>(E))
    return Cast->isGLValue() && Cast->getCastKind() == CK_Dynamic;
  if (auto *Typeid = dyn_cast_or_null<CXXTypeidExpr>(E))
    return Typeid->isPotentiallyEvaluated() && Typeid->hasNullCheck();
  return false;
}
bool marked(const Decl *D, llvm::StringRef Tag) {
  for (auto *A : D->specific_attrs<AnnotateAttr>())
    if (A->getAnnotation() == Tag)
      return true;
  return false;
}
bool nativeBorrow(const UnaryOperator *U) {
  auto Spelling = UnaryOperator::getOpcodeStr(U->getOpcode());
  return Spelling == "^" || Spelling == "^const";
}
bool nativeRelocation(const UnaryOperator *U) {
  return UnaryOperator::getOpcodeStr(U->getOpcode()) == "^^";
}
const UnaryOperator *relocation(const Expr *E) {
  if (!E) return nullptr;
  for (;;) {
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E)) E = Cleanup->getSubExpr();
    else if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E)) E = Bound->getSubExpr();
    else break;
  }
  auto *U = dyn_cast<UnaryOperator>(E);
  return U && nativeRelocation(U) ? U : nullptr;
}
bool cannotReturn(const Expr *E) {
  if (!E) return false;
  for (;;) {
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr();
    else if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      E = Bound->getSubExpr();
    else
      break;
  }
  if (auto *Statement = dyn_cast<StmtExpr>(E))
    if (auto *Body = Statement->getSubStmt())
      return cannotReturn(dyn_cast_or_null<Expr>(Body->body_back()));
  if (isa<CXXThrowExpr>(E)) return true;
  if (auto *Call = dyn_cast<CallExpr>(E))
    if (auto *Callee = Call->getDirectCallee())
      return Callee->isNoReturn() ||
             modulesafety::marked(Callee, "safecpp.panic");
  return false;
}
bool nativeBorrowDereference(const UnaryOperator *U) {
#ifdef MODULE_SAFETY_BUILTIN
  if (U && U->getOpcode() == UO_Deref &&
      U->getSubExpr()->IgnoreParenImpCasts()->getType()->getAs<BorrowValueType>())
    return true;
  if (U && U->getOpcode() == UO_Deref)
    if (const auto *Ref = dyn_cast<DeclRefExpr>(U->getSubExpr()->IgnoreParenImpCasts()))
      if (const auto *Value = dyn_cast<ValueDecl>(Ref->getDecl()))
        if (const auto *Borrow = Value->getType()->getAs<ReferenceType>())
          if (Borrow->isSafetyBorrow())
            return true;
#endif
  // Native dereference accesses the borrow's existing referent, so its value
  // type is unchanged. Raw pointer dereference has a different pointee type.
  return U && U->getOpcode() == UO_Deref && !U->isTypeDependent() &&
         U->getType() == U->getSubExpr()->getType();
}
bool containsStringLiteral(const Stmt *S) {
  if (!S) return false;
  if (isa<StringLiteral>(S)) return true;
  for (const Stmt *Child : S->children())
    if (containsStringLiteral(Child)) return true;
  return false;
}
bool containsBoundsTrap(const Stmt *S) {
  if (!S) return false;
  if (const auto *Call = dyn_cast<CallExpr>(S))
    if (const auto *Callee = Call->getDirectCallee())
      if (Callee->getIdentifier() &&
          (Callee->getIdentifier()->getName() == "__builtin_trap" ||
           Callee->getIdentifier()->getName() == "__builtin_abort"))
        return true;
  for (const Stmt *Child : S->children())
    if (containsBoundsTrap(Child)) return true;
  return false;
}
bool referencesVar(const Stmt *S, const VarDecl *V) {
  if (!S || !V) return false;
  if (const auto *D = dyn_cast<DeclRefExpr>(S)) return D->getDecl() == V;
  for (const Stmt *Child : S->children())
    if (referencesVar(Child, V)) return true;
  return false;
}
const VarDecl *variable(const Expr *E) {
  if (!E)
    return nullptr;
  E = evaluationSource(E->IgnoreParenImpCasts());
  while (auto *Cleanups = dyn_cast<ExprWithCleanups>(E))
    E = Cleanups->getSubExpr()->IgnoreParenImpCasts();
  if (auto *D = dyn_cast<DeclRefExpr>(E)) {
    if (auto *Binding = dyn_cast<BindingDecl>(D->getDecl()))
      return dyn_cast_or_null<VarDecl>(Binding->getDecomposedDecl());
    return dyn_cast<VarDecl>(D->getDecl());
  }
  if (auto *U = dyn_cast<UnaryOperator>(E);
      U && (nativeBorrow(U) || nativeBorrowDereference(U)))
    return variable(U->getSubExpr());


  if (auto *C = dyn_cast<CastExpr>(E))
    return variable(C->getSubExpr());
  if (auto *M = dyn_cast<MemberExpr>(E))
    return variable(M->getBase());
  if (auto *Array = dyn_cast<ArraySubscriptExpr>(E))
    return variable(Array->getBase());
  if (auto *Call = dyn_cast<CallExpr>(E); Call)
    if (auto *Fn = Call->getDirectCallee();
        Fn && Fn->getReturnType()->isReferenceType()) {
      unsigned Offset = isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Fn)
                            ? 1u : 0u;
      if (modulesafety::marked(Fn, "safecpp.borrow.this")) {
        if (auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
          return variable(Member->getImplicitObjectArgument());
        if (Offset && Call->getNumArgs()) return variable(Call->getArg(0));
      }
      auto Regions = borrowedParameters(Fn);
      if (Regions.size() == 1 && *Regions.begin() + Offset < Call->getNumArgs())
        return variable(Call->getArg(*Regions.begin() + Offset));
    }
  return nullptr;
}
const VarDecl *matchSubjectBase(const Expr *E) {
  if (!E) return nullptr;
  for (;;) {
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr();
    else if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      E = Bound->getSubExpr();
    else if (auto *Member = dyn_cast<MemberExpr>(E))
      E = Member->getBase();
    else if (auto *U = dyn_cast<UnaryOperator>(E);
             U && (nativeRelocation(U) || nativeBorrow(U) ||
                   U->getOpcode() == UO_Deref || U->getOpcode() == UO_Extension))
      E = U->getSubExpr();
    else if (auto *Cast = dyn_cast<CastExpr>(E))
      E = Cast->getSubExpr();
    else if (auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      // OR patterns select one payload from the same match subject. Preserve
      // that common loan ancestor without merging the branches' field roots.
      auto *Left = matchSubjectBase(Choice->getTrueExpr());
      auto *Right = matchSubjectBase(Choice->getFalseExpr());
      return Left && Left == Right ? Left : nullptr;
    }
    else
      break;
  }
  auto *V = variable(E);
  return V && modulesafety::marked(V, "safecpp.native.match.subject") ? V
                                                                     : nullptr;
}
#ifdef MODULE_SAFETY_BUILTIN
// Only a checked array decay and a bounded constant count establish this
// relation. The data pointer of arbitrary raw-parts slices has no such proof.
const Expr *arraySliceSource(const InitListExpr *Init) {
  auto *Record = Init->getType()->getAsCXXRecordDecl();
  if (!Record || Init->getNumInits() != 2) return nullptr;
  auto &C = Record->getASTContext();
  if (!C.circleSliceField(Init->getType(), false)) return nullptr;
  const Expr *Pointer = Init->getInit(0);
  QualType Element = Pointer->getType()->isPointerType()
                         ? Pointer->getType()->getPointeeType() : QualType();
  const Expr *Array = Pointer->IgnoreParenImpCasts();
  while (auto *Cast = dyn_cast<CastExpr>(Array)) {
    if (Cast->getCastKind() != CK_NoOp && Cast->getCastKind() != CK_BitCast &&
        Cast->getCastKind() != CK_ArrayToPointerDecay) return nullptr;
    Array = Cast->getSubExpr()->IgnoreParenImpCasts();
  }
  auto *Allocation = C.getAsConstantArrayType(Array->getType());
  Expr::EvalResult Count;
  if (!Element.isNull() && Allocation &&
      C.hasSameUnqualifiedType(Element, Allocation->getElementType()) &&
      !(Allocation->getElementType().getCVRQualifiers() & ~Element.getCVRQualifiers()) &&
      Init->getInit(1)->EvaluateAsInt(Count, C) && !Count.HasSideEffects &&
      !Count.Val.getInt().isNegative() && Count.Val.getInt().getActiveBits() <= 64 &&
      Allocation->getSize().getActiveBits() <= 64 &&
      Count.Val.getInt().getZExtValue() <= Allocation->getSize().getZExtValue())
    return Array;
  return nullptr;
}
#endif
// A borrow-valued projection through an explicit object receiver is a
// reborrow of that receiver, not an independent loan over its ultimate owner.
// Keep the named receiver when one exists so conflict checks compare it with
// its own loan; temporary receivers have no such variable and keep the roots
// of the projection.
const VarDecl *borrowedReceiver(const Expr *E) {
  if (!E)
    return nullptr;
  E = evaluationSource(E->IgnoreParenImpCasts());
  for (;;) {
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr()->IgnoreParenImpCasts();
    else if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(E))
      E = Temporary->getSubExpr()->IgnoreParenImpCasts();
    else if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      E = Bound->getSubExpr()->IgnoreParenImpCasts();
    else if (auto *Cast = dyn_cast<CastExpr>(E))
      E = Cast->getSubExpr()->IgnoreParenImpCasts();
    else if (auto *Paren = dyn_cast<ParenExpr>(E))
      E = Paren->getSubExpr()->IgnoreParenImpCasts();
    else if (auto *Unary = dyn_cast<UnaryOperator>(E);
             Unary && (nativeBorrow(Unary) || nativeBorrowDereference(Unary)))
      E = Unary->getSubExpr()->IgnoreParenImpCasts();
#ifdef MODULE_SAFETY_BUILTIN
    else if (auto *Init = dyn_cast<InitListExpr>(E); Init && arraySliceSource(Init))
      E = arraySliceSource(Init);
#endif
    else if (auto *Comma = dyn_cast<BinaryOperator>(E);
             Comma && Comma->getOpcode() == BO_Comma)
      E = Comma->getRHS()->IgnoreParenImpCasts();
    else
      break;
  }
  if (auto *V = variable(E))
    return V;
  auto *Call = dyn_cast<CallExpr>(E);
  auto *Method = Call ? dyn_cast_or_null<CXXMethodDecl>(Call->getDirectCallee())
                      : nullptr;
  if (!Method || !Method->isExplicitObjectMemberFunction() ||
      !Call->getNumArgs())
    return nullptr;
  return variable(Call->getArg(0));
}
// Keep native borrow operations in the AST, but inspect the underlying place
// when proving that two directly owned fields have disjoint storage.
const Expr *borrowedPlace(const Expr *E) {
  E = evaluationSource(E->IgnoreParenImpCasts());
  if (auto *U = dyn_cast<UnaryOperator>(E);
      U && (nativeBorrow(U) || nativeBorrowDereference(U)))
    return borrowedPlace(U->getSubExpr());
  return E;
}
bool wholeObject(const Expr *E) {
  auto *Ref = dyn_cast<DeclRefExpr>(E->IgnoreParenImpCasts());
  return Ref && isa<VarDecl>(Ref->getDecl());
}
FieldPath ownedFieldPath(const Expr *E) {
  FieldPath Path;
  E = evaluationSource(E->IgnoreParenImpCasts());
  E = borrowedPlace(E);
  if (auto *Array = dyn_cast<ArraySubscriptExpr>(E))
    E = borrowedPlace(Array->getBase()->IgnoreParenImpCasts());
  while (auto *Member = dyn_cast<MemberExpr>(E)) {
    auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
    if (Member->isArrow() || !Field || Field->getType()->isReferenceType() ||
        Field->isBitField() || Field->hasAttr<NoUniqueAddressAttr>()) return {};
    Path.push_back(Field);
    E = borrowedPlace(Member->getBase()->IgnoreParenImpCasts());
  }
  auto *Ref = dyn_cast<DeclRefExpr>(E);
  auto *V = Ref ? dyn_cast<VarDecl>(Ref->getDecl()) : nullptr;
  if (!V || (V->getType()->isReferenceType() &&
             !modulesafety::marked(V, "safecpp.native.match.subject")))
    return {};
  std::reverse(Path.begin(), Path.end());
  return Path;
}
// Preserve materialized temporaries and native borrow operations while
// peeling the representation-only casts used to select an && method.
const Expr *consumingPlace(const Expr *E) {
  for (;;) {
    if (auto *P = dyn_cast<ParenExpr>(E)) E = P->getSubExpr();
    else if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr();
    else if (auto *Cast = dyn_cast<CastExpr>(E);
             Cast && Cast->getCastKind() == CK_NoOp)
      E = Cast->getSubExpr();
    else return E;
  }
}
// A derived-to-base conversion selects the base subobject of an owning place.
// Peeling that conversion lets the checker see `d.base` as a field path while
// still requiring the same consumable-subobject checks.
const Expr *consumingSubobjectPlace(const Expr *E) {
  E = consumingPlace(E);
  while (auto *Cast = dyn_cast<CastExpr>(E)) {
    auto Kind = Cast->getCastKind();
    if (Kind != CK_DerivedToBase && Kind != CK_UncheckedDerivedToBase &&
        Kind != CK_NoOp)
      break;
    E = consumingPlace(Cast->getSubExpr());
  }
  return E;
}
// Distinct directly owned fields are disjoint even when their enclosing
// lifetime region is the same. Reference fields do not establish disjointness:
// two different reference members can point to the very same object.
bool disjointOwnedFields(const Expr *A, const Expr *B) {
  if (!A || !B)
    return false;
  auto *MA = dyn_cast<MemberExpr>(borrowedPlace(A));
  auto *MB = dyn_cast<MemberExpr>(borrowedPlace(B));
  if (!MA || !MB || MA->isArrow() || MB->isArrow())
    return false;
  auto *FA = dyn_cast<FieldDecl>(MA->getMemberDecl());
  auto *FB = dyn_cast<FieldDecl>(MB->getMemberDecl());
  if (!FA || !FB || FA == FB || FA->getParent() != FB->getParent() ||
      FA->getParent()->isUnion() || FA->isBitField() || FB->isBitField() ||
      FA->hasAttr<NoUniqueAddressAttr>() || FB->hasAttr<NoUniqueAddressAttr>() ||
      objectBorrow(FA->getType()) || objectBorrow(FB->getType()))
    return false;
  auto *DA = dyn_cast<DeclRefExpr>(borrowedPlace(MA->getBase()));
  auto *DB = dyn_cast<DeclRefExpr>(borrowedPlace(MB->getBase()));
  return DA && DB && DA->getDecl() == DB->getDecl();
}
struct Loan {
  Vars Roots;
  bool Exclusive = false;
  Vars Parents = {};
  // Missing means the legacy uniform permission; an engaged set records
  // exactly which origins may be written, including an empty shared set.
  std::optional<Vars> WriteRoots = std::nullopt;
  bool exclusiveAt(const VarDecl *Root) const {
    return Exclusive && (!WriteRoots || WriteRoots->count(Root));
  }
  bool operator==(const Loan &R) const {
    return Roots == R.Roots && Exclusive == R.Exclusive && Parents == R.Parents &&
           WriteRoots == R.WriteRoots;
  }
};
void mergeLoan(Loan &A, const Loan &B) {
  A.Roots.insert(B.Roots.begin(), B.Roots.end());
  A.Exclusive |= B.Exclusive;
  if (A.WriteRoots && B.WriteRoots)
    A.WriteRoots->insert(B.WriteRoots->begin(), B.WriteRoots->end());
  else A.WriteRoots.reset();
}
using FieldLoans = std::map<FieldPath, Loan>;
struct SliceBoundFact {
  const VarDecl *Source = nullptr;
  const Expr *Start = nullptr;
  const Expr *Count = nullptr;
  bool operator==(const SliceBoundFact &R) const {
    return Source == R.Source && Start == R.Start && Count == R.Count;
  }
  bool operator<(const SliceBoundFact &R) const {
    if (Source != R.Source) return Source < R.Source;
    if (Start != R.Start) return Start < R.Start;
    return Count < R.Count;
  }
};
using CallableRegions = std::map<unsigned, Vars>;
struct State {
  std::map<const VarDecl *, std::map<FieldPath, CallableRegions>> Callables;
  std::map<const VarDecl *, FieldLoans> Fields;
  // Indirect element storage is not represented by a C++ reference field.
  // Its retained origins must survive NLL expiry of temporary receiver loans.
  std::map<const VarDecl *, Vars> RetainedBorrows;
  // Pointee origins are distinct from the pointer object's own storage.
  // An empty set is unknown and must poison a join, not disappear from it.
  std::map<const VarDecl *, Vars> RawPointers;
  // The storage designated by a borrow/reference is distinct from the data
  // it carries. Unknown on either incoming path poisons the joined summary.
  std::map<const VarDecl *, Vars> BorrowStorage;
  Vars EscapedPointerSlots, InvalidRawRoots;
  Vars Ready, Moved, Relocated;
  // Borrows spent by a relocation: the handle names a place whose value the
  // relocation took, so reaching that place through this handle is over.
  Vars Spent;
  std::map<const VarDecl *, std::set<FieldPath>> RelocatedFields;
  std::map<const VarDecl *, const FieldDecl *> ActiveUnions;
  std::map<const VarDecl *, Loan> Loans;
  // Facts proven on every path into this point. A false edge of
  // `if (count > length - start) return;` contributes the subrange bound.
  std::set<SliceBoundFact> SliceBounds;
  bool operator==(const State &R) const {
    return Callables == R.Callables && RetainedBorrows == R.RetainedBorrows && RawPointers == R.RawPointers &&
           BorrowStorage == R.BorrowStorage &&
           EscapedPointerSlots == R.EscapedPointerSlots &&
           InvalidRawRoots == R.InvalidRawRoots && Ready == R.Ready && Moved == R.Moved && Relocated == R.Relocated &&
           Spent == R.Spent &&
           RelocatedFields == R.RelocatedFields && Loans == R.Loans && Fields == R.Fields &&
           ActiveUnions == R.ActiveUnions && SliceBounds == R.SliceBounds;
  }
};
// Join at both ordinary and exceptional control-flow edges.
State joinStates(State A, const State &B) {
  Vars Ready;
  std::set_intersection(A.Ready.begin(), A.Ready.end(), B.Ready.begin(),
                        B.Ready.end(), std::inserter(Ready, Ready.end()),
                        A.Ready.key_comp());
  A.Ready = std::move(Ready);
  A.EscapedPointerSlots.insert(B.EscapedPointerSlots.begin(), B.EscapedPointerSlots.end());
  A.InvalidRawRoots.insert(B.InvalidRawRoots.begin(), B.InvalidRawRoots.end());
  auto PointerKeys = Vars{};
  for (const auto &[V, R] : A.RawPointers) PointerKeys.insert(V);
  for (const auto &[V, R] : B.RawPointers) PointerKeys.insert(V);
  for (auto *V : PointerKeys) {
    auto I = A.RawPointers.find(V);
    auto J = B.RawPointers.find(V);
    if (I == A.RawPointers.end() || J == B.RawPointers.end() ||
        I->second.empty() || J->second.empty()) A.RawPointers[V].clear();
    else I->second.insert(J->second.begin(), J->second.end());
  }
  Vars StorageKeys;
  for (const auto &[V, R] : A.BorrowStorage) StorageKeys.insert(V);
  for (const auto &[V, R] : B.BorrowStorage) StorageKeys.insert(V);
  for (auto *V : StorageKeys) {
    auto I = A.BorrowStorage.find(V);
    auto J = B.BorrowStorage.find(V);
    if (I == A.BorrowStorage.end() || J == B.BorrowStorage.end() ||
        I->second.empty() || J->second.empty()) A.BorrowStorage[V].clear();
    else I->second.insert(J->second.begin(), J->second.end());
  }
  A.Moved.insert(B.Moved.begin(), B.Moved.end());
  for (const auto &[Owner, Origins] : B.RetainedBorrows)
    A.RetainedBorrows[Owner].insert(Origins.begin(), Origins.end());
  A.Relocated.insert(B.Relocated.begin(), B.Relocated.end());
  for (const auto &[Owner, Fields] : B.RelocatedFields)
    A.RelocatedFields[Owner].insert(Fields.begin(), Fields.end());
  for (auto I = A.ActiveUnions.begin(); I != A.ActiveUnions.end();)
    if (auto J = B.ActiveUnions.find(I->first);
        J == B.ActiveUnions.end() || J->second != I->second)
      I = A.ActiveUnions.erase(I);
    else ++I;
  // Roots/exclusivity are may-facts. An ancestor is a permission to bypass
  // a conflicting loan, so it must hold on every incoming path.
  for (auto &[Alias, Borrow] : A.Loans) {
    Vars Common;
    if (auto I = B.Loans.find(Alias); I != B.Loans.end())
      std::set_intersection(Borrow.Parents.begin(), Borrow.Parents.end(),
                            I->second.Parents.begin(), I->second.Parents.end(),
                            std::inserter(Common, Common.end()),
                            Borrow.Parents.key_comp());
    Borrow.Parents = std::move(Common);
  }
  for (auto &[Alias, Borrow] : B.Loans) {
    auto &Loan = A.Loans[Alias];
    mergeLoan(Loan, Borrow);
  }
  for (const auto &[Owner, Fields] : B.Fields)
    for (const auto &[Path, Borrow] : Fields) {
      auto &Merged = A.Fields[Owner][Path];
      mergeLoan(Merged, Borrow);
    }
  // Missing/unknown callable captures poison a control-flow join.
  for (const auto &[Owner, Paths] : B.Callables)
    for (const auto &[Path, Captures] : Paths)
      for (const auto &[ID, Roots] : Captures) {
        auto &Dest = A.Callables[Owner][Path][ID];
        if (Dest.empty() || Roots.empty()) Dest.clear();
        else Dest.insert(Roots.begin(), Roots.end());
      }
  for (auto &[Owner, Paths] : A.Callables)
    for (auto &[Path, Captures] : Paths)
      for (auto &[ID, Roots] : Captures) {
        auto O = B.Callables.find(Owner);
        if (O == B.Callables.end() || !O->second.count(Path) || !O->second.at(Path).count(ID)) Roots.clear();
      }
  std::set<SliceBoundFact> Bounds;
  std::set_intersection(A.SliceBounds.begin(), A.SliceBounds.end(),
                        B.SliceBounds.begin(), B.SliceBounds.end(),
                        std::inserter(Bounds, Bounds.end()));
  A.SliceBounds = std::move(Bounds);
  return A;
}
bool hasBorrowConflict(const VarDecl *V, bool Write, const Vars &Roots,
                       const Vars &Ancestors, const State &S,
                       const Vars &DeadBindings = {},
                       const Vars *WriteRoots = nullptr) {
  for (auto &[Alias, L] : S.Loans) {
    bool MutableBorrowValue = false;
#ifdef MODULE_SAFETY_BUILTIN
    MutableBorrowValue = V->getType()->getAs<BorrowValueType>() &&
                         objectBorrow(V->getType(), true);
#endif
    if (Alias == V || Ancestors.count(Alias) || DeadBindings.count(Alias) ||
        (L.Exclusive && L.Parents.count(V) &&
         !MutableBorrowValue &&
         (marked(Alias, "safecpp.native.match.binding") ||
          marked(Alias, "safecpp.native.match.subject"))) ||
        (S.Moved.count(Alias) && objectBorrow(Alias->getType())))
      continue;
    // The generated match subject keeps the operand alive while the pattern
    // is tested and its bindings are formed. Inside the arm, each binding
    // carries its own loan; mutating the operand after the last binding use is
    // therefore not a use of the subject temporary.
    if (Write && marked(Alias, "safecpp.native.match.subject"))
      continue;
    for (auto *Root : Roots)
      if (L.Roots.count(Root) &&
          ((Write && (!WriteRoots || WriteRoots->count(Root))) || L.exclusiveAt(Root)))
        return true;
  }
  return false;
}
// Mark only the permission of the expression itself. Nested function bodies
// receive independent analyses, even if they were declared inside unsafe.
class Contexts : public RecursiveASTVisitor<Contexts> {
  bool Unsafe = false;

public:
  std::set<const Stmt *> Unchecked, Generated;
  std::map<const VarDecl *, const CompoundStmt *> Scopes;
  const CompoundStmt *Scope = nullptr;
  bool VisitStmt(Stmt *S) {
    if (Unsafe)
      Unchecked.insert(S);
    return true;
  }
  // Before the base capture executes, check that evaluating its index cannot
  // invalidate the captured loan. State queries must not reinterpret an old
  // captured address using a receiver rebound later inside that index.
  std::map<const Stmt *, std::vector<std::pair<const Expr *, const Expr *>>> SliceIndices;
  bool VisitPseudoObjectExpr(PseudoObjectExpr *E) {
#ifdef MODULE_SAFETY_BUILTIN
    const auto *Syntax = dyn_cast<ArraySubscriptExpr>(E->getSyntacticForm());
    if (Syntax && !Syntax->getType()->isDependentType()) {
      const auto *Base = dyn_cast<OpaqueValueExpr>(Syntax->getBase());
      const auto *Index = dyn_cast<OpaqueValueExpr>(Syntax->getIdx());
      if (Base && Index && !Base->getSourceExpr()->getType().isNull() &&
          !Base->getType()->isDependentType()) {
        auto *Record = Base->getType()->getAs<BorrowValueType>();
        QualType Shape = Record ? Record->getPointeeType() : Base->getType();
        if (auto *R = Shape->getAsCXXRecordDecl();
            R && R->getASTContext().isCircleSliceRecord(Shape))
          SliceIndices[Base->getSourceExpr()].push_back(
              {Base->getSourceExpr(), Index->getSourceExpr()});
      }
    }
#endif
    return true;
  }
  std::set<const VarDecl *> UnsafeVars;
  bool VisitVarDecl(VarDecl *V) {
    Scopes[V] = Scope;
    if (Unsafe)
      UnsafeVars.insert(V);
    return true;
  }
  void generatedSuspension(Stmt *S, Stmt *Operand) {
    if (!S || S == Operand)
      return;
    Unchecked.insert(S);
    Generated.insert(S);
    for (auto *Child : S->children())
      generatedSuspension(Child, Operand);
  }
  bool TraverseCoyieldExpr(CoyieldExpr *E) {
    auto *Call = dyn_cast<CallExpr>(E->getOperand()->IgnoreParenImpCasts());
    if (!Call || Call->getNumArgs() != 1)
      return true;
    auto *Value = Call->getArg(0);
    generatedSuspension(E, Value);
    return TraverseStmt(Value);
  }
  bool TraverseCoawaitExpr(CoawaitExpr *E) {
    generatedSuspension(E, E->getOperand());
    return TraverseStmt(E->getOperand());
  }
  bool TraverseLambdaExpr(LambdaExpr *) { return true; }
  bool TraverseCompoundStmt(CompoundStmt *S) {
    auto *Old = Scope;
    Scope = S;
    bool R = RecursiveASTVisitor::TraverseCompoundStmt(S);
    Scope = Old;
    return R;
  }
  bool TraverseIfStmt(IfStmt *S) {
    auto *V = S->getConditionVariable();
    if (!V || !marked(V, "safecpp.unsafe.scope"))
      return RecursiveASTVisitor::TraverseIfStmt(S);
    TraverseStmt(S->getInit());
    TraverseDecl(V);
    TraverseStmt(S->getCond());
    bool Old = Unsafe;
    Unsafe = true;
#ifdef MODULE_SAFETY_BUILTIN
    if (const auto *Body = circleUnsafeBody(S)) {
      for (auto *Child : Body->body()) TraverseStmt(Child);
    } else
#endif
    TraverseStmt(S->getThen());
    Unsafe = Old;
    TraverseStmt(S->getElse());
    return true;
  }
};
class Uses : public RecursiveASTVisitor<Uses> {
public:
  Vars Used;
  bool VisitDeclRefExpr(DeclRefExpr *E) {
    if (auto *V = variable(E))
      Used.insert(V);
    return true;
  }
  bool TraverseLambdaExpr(LambdaExpr *E) {
    for (const auto &Capture : E->captures())
      if (Capture.capturesVariable())
        if (auto *V = dyn_cast<VarDecl>(Capture.getCapturedVar()))
          Used.insert(V);
    return true;
  }
};
class Analysis {
  ASTContext &C;
  FunctionDecl *F;
  std::optional<AnalysisParents> Parents;
  llvm::ArrayRef<DynTypedNode> parentNodes(const DynTypedNode &Node) {
    if (!Parents) {
      Parents.emplace();
      Parents->TraverseDecl(F);
    }
    return Parents->get(Node);
  }
  template <typename T> llvm::ArrayRef<DynTypedNode> parentNodes(const T &Node) {
    return parentNodes(DynTypedNode::create(Node));
  }
  CheckCall Check;
  const VarDecl *ThisOrigin = nullptr;
  const VarDecl *StaticOrigin = nullptr;
  const VarDecl *LiteralOrigin = nullptr;
  const VarDecl *CreationTarget = nullptr;
  std::map<const VarDecl *, std::map<FieldPath, const VarDecl *>> FieldOrigins;
  std::map<const VarDecl *, const VarDecl *> OriginOwners;
  std::map<const VarDecl *, Vars> MatchOrigins;
  std::map<const VarDecl *, const ParmVarDecl *> ParameterRegions;
  struct ClassRegionOrigin {
    const VarDecl *Parameter;
    const CXXRecordDecl *Record;
    unsigned Index;
  };
  std::map<const VarDecl *, ClassRegionOrigin> ClassRegions;
  Vars CaptureRegions, CapturedVariables, ExternalPointerRoots;
  Contexts Context;
  std::set<std::pair<const Stmt *, std::string>> Reported;
  std::map<const Stmt *, Vars> LiveAfter;
  std::map<const CFGElement *, const CFGBlock *> ExceptionHandlers;
  std::map<unsigned, Vars> HandlerLocals;
  std::map<unsigned, std::map<unsigned, State>> ExceptionalOut;
  bool Emit = false;
  bool ContractsOnly = false;
  void error(const Stmt *S, llvm::StringRef Message) {
    if (!Emit || ContractsOnly || Context.Unchecked.count(S) ||
        !Reported.emplace(S, Message.str()).second)
      return;
    auto &D = C.getDiagnostics();
    D.Report(S->getBeginLoc(),
             D.getCustomDiagID(DiagnosticsEngine::Error, "module-safety: %0"))
        << Message;
  }
  void contractError(const Stmt *At, llvm::StringRef Message) {
    if (!Emit || !Reported.emplace(At, Message.str()).second) return;
    C.getDiagnostics().Report(At->getBeginLoc(),
        C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
                                          "module-safety: %0")) << Message;
  }
  bool permanentRoot(const VarDecl *V, const State &S, Vars &Seen) {
    if (!V || S.InvalidRawRoots.count(V) || !Seen.insert(V).second) return false;
    if (V == StaticOrigin || V == LiteralOrigin) return true;
#ifdef MODULE_SAFETY_BUILTIN
    if (functionRootRegion(V) == 0x40000000u) return true;
    if ((ClassRegions.count(V) ||
         (ParameterRegions.count(V) && !OriginOwners.count(V))) &&
        circleFunctionRegionIsStatic(F->getType()->getAs<FunctionProtoType>(),
                                      functionRootRegion(V)))
      return true;
    if (auto I = ClassRegions.find(V); I != ClassRegions.end())
      if (circleClassRegionIsStatic(I->second.Record, I->second.Index)) return true;
    const ParmVarDecl *Parameter = dyn_cast<ParmVarDecl>(V);
    bool ProjectedRegion = false;
    if (auto I = ParameterRegions.find(V); I != ParameterRegions.end())
      // Field-storage places also name their parameter for alias tracking;
      // they are not the parameter's carried-data region.
      Parameter = I->second, ProjectedRegion = !OriginOwners.count(V);
    if (Parameter && Parameter->getDeclContext() == F)
      if (auto *Proto = F->getType()->getAs<FunctionProtoType>()) {
        auto Info = Proto->getExtParameterInfo(Parameter->getFunctionScopeIndex());
        if (F->getLiteralIdentifier() && Parameter->getFunctionScopeIndex() == 0 &&
            Parameter->getType()->isPointerType()) return true;
        // A static type promises its carried regions, not the storage of a
        // by-value parameter or of the borrow handle itself. The latter is a
        // local object even when all of its referents are permanent.
        bool StaticLifetimeReferent = Parameter->getType()->isReferenceType() ||
                                      Parameter->getType()->isPointerType() ||
                                      Parameter->getType()->getAs<BorrowValueType>();
        bool StaticLifetime = Info.hasStaticLifetime() ||
            circleFunctionRegionIsStatic(Proto, circleFunctionRegion(
                Proto, Parameter->getFunctionScopeIndex() + 1));
        if (StaticLifetime &&
            (ProjectedRegion || StaticLifetimeReferent)) return true;
        if (Info.hasStaticTypeLifetimes() &&
            (ProjectedRegion || Parameter->getType()->isReferenceType()))
          return true;
      }
#endif
    if (!V->hasGlobalStorage() || V->getTLSKind() != VarDecl::TLS_None)
      return false;
    if (!objectBorrow(V->getType())) return true;
    auto Origins = S.Loans.count(V) ? S.Loans.at(V).Roots
                    : V->hasInit() ? expressionRoots(V->getInit(), S) : Vars{};
    if (Origins.empty()) return false;
    for (auto *Origin : Origins) {
      auto Path = Seen;
      if (!permanentRoot(Origin, S, Path)) return false;
    }
    return true;
  }
  void staticFieldValue(const Expr *Value, const Stmt *At, const State &S,
                        bool Variable = false) {
    // A slice record's static provenance is the provenance of its data
    // pointer, not that of the record's temporary storage.
#ifdef MODULE_SAFETY_BUILTIN
    if (const auto *List = dyn_cast<InitListExpr>(Value);
        List && !C.circleSliceElement(Value->getType()).isNull() &&
        List->getNumInits() > 0) {
      staticFieldValue(List->getInit(0), At, S, Variable);
      return;
    }
#endif
    auto Origins = expressionRoots(Value, S);
    // A value formed from a string literal's bytes carries immutable static
    // storage. The generated slice record is a temporary, but its data pointer
    // is the literal's array, so the static contract is satisfied by that
    // origin rather than by the record's local storage.
    if (containsStringLiteral(Value)) {
#ifdef MODULE_SAFETY_BUILTIN
      if (const InitListExpr *Slice = rawSliceConstruction(Value);
          Slice && !placeableRawExtent(Slice->getInit(0), Slice->getInit(1),
                                       S)) {
        contractError(At, Variable
            ? "static borrow variable lifetime contract requires permanent non-thread-local borrow origins"
            : "static field lifetime contract requires permanent non-thread-local borrow origins");
        return;
      }
#endif
      Origins.clear();
      Origins.insert(LiteralOrigin);
    }
    bool Valid = !Origins.empty();
    for (auto *Origin : Origins) {
      Vars Seen;
      Valid &= permanentRoot(Origin, S, Seen);
    }
    if (!Valid)
      contractError(At, Variable
          ? "static borrow variable lifetime contract requires permanent non-thread-local borrow origins"
          : "static field lifetime contract requires permanent non-thread-local borrow origins");
  }
  void staticArgumentContracts(const FunctionProtoType *Proto,
      const std::vector<std::pair<const Expr *, QualType>> &Args,
      const Stmt *At, const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    if (!Proto) return;
    for (unsigned I = 0; I < Proto->getNumParams() && I < Args.size(); ++I) {
      auto Info = Proto->getExtParameterInfo(I);
      bool StaticLifetime = Info.hasStaticLifetime() ||
          circleFunctionRegionIsStatic(Proto, circleFunctionRegion(Proto, I + 1));
      if (!StaticLifetime && !Info.hasStaticTypeLifetimes()) continue;
      auto [Value, Type] = Args[I];
      if (!StaticLifetime && Info.hasStaticTypeLifetimes() && !objectBorrow(Type)) continue;
      auto Origins = expressionRoots(Value, S);
      // The standard gives a string literal object static storage duration.
      // The literal operator's first argument is the array-to-pointer decay
      // of that object, so it satisfies a static-lifetime parameter even when
      // the expression has no named root.
      bool LiteralArgument = isa<StringLiteral>(Value->IgnoreParenImpCasts());
      bool Valid = LiteralArgument || !Origins.empty();
      if (!LiteralArgument)
        for (auto *Origin : Origins) {
          Vars Seen;
          Valid &= permanentRoot(Origin, S, Seen);
        }
      if (!Valid)
        contractError(At, "static lifetime contract requires permanent non-thread-local borrow origins");
    }
#endif
  }
  Vars retainedOrigins(const Vars &Places, const State &S) {
    Vars Result, Seen;
    std::vector<const VarDecl *> Pending(Places.begin(), Places.end());
    while (!Pending.empty()) {
      auto *Place = Pending.back(); Pending.pop_back();
      if (!Seen.insert(Place).second) continue;
      auto Add = [&](const VarDecl *Owner) {
        if (auto I = S.RetainedBorrows.find(Owner); I != S.RetainedBorrows.end())
          for (auto *Origin : I->second) {
            Result.insert(Origin);
            Pending.push_back(Origin);
          }
      };
      Add(Place);
      if (auto I = OriginOwners.find(Place); I != OriginOwners.end())
        Add(I->second);
    }
    return Result;
  }
  Vars withRetainedOrigins(Vars Places, const State &S) {
    auto Origins = retainedOrigins(Places, S);
    Places.insert(Origins.begin(), Origins.end());
    return Places;
  }
  Vars roots(const VarDecl *V, const State &S) {
    if (!V)
      return {};
    Vars R;
    if (auto It = S.Loans.find(V); It != S.Loans.end())
      R = It->second.Roots;
    else R.insert(V);
    if (auto It = S.RetainedBorrows.find(V); It != S.RetainedBorrows.end())
      R.insert(It->second.begin(), It->second.end());
    if (S.Loans.count(V)) return withRetainedOrigins(std::move(R), S);
    if (auto I = FieldOrigins.find(V); I != FieldOrigins.end())
      for (const auto &[Field, Origin] : I->second) R.insert(Origin);
    return withRetainedOrigins(std::move(R), S);
  }
  bool indirectBorrowStorage(QualType T, QualType Element = {},
                             std::set<const CXXRecordDecl *> Seen = {},
                             bool ExclusiveOnly = false) {
    T = T.getNonReferenceType();
#ifdef MODULE_SAFETY_BUILTIN
    if (auto *Borrow = T->getAs<BorrowValueType>()) T = Borrow->getPointeeType();
#endif
    auto *Record = T->getAsCXXRecordDecl();
    if (!Record || !Record->hasDefinition() ||
        !Seen.insert(Record->getCanonicalDecl()).second) return false;
    for (auto *Field : Record->getDefinition()->fields()) {
      auto Type = Field->getType();
      if (Type->isRecordType() && indirectBorrowStorage(Type, Element, Seen, ExclusiveOnly))
        return true;
      if (!Type->isPointerType()) continue;
      if (!modulesafety::hasLifetimeBinderParameter(Record)) continue;
      auto Pointee = Type->getPointeeType();
      if ((objectBorrow(Pointee, ExclusiveOnly) ||
           indirectBorrowStorage(Pointee, {}, Seen, ExclusiveOnly)) &&
          (Element.isNull() || C.hasSameUnqualifiedType(Pointee, Element)))
        return true;
    }
    for (const auto &Base : Record->getDefinition()->bases())
      if (indirectBorrowStorage(Base.getType(), Element, Seen, ExclusiveOnly)) return true;
    return false;
  }
  bool emptyIndirectConstruction(const Expr *E) {
    if (!E) return false;
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr()->IgnoreParenImpCasts();
    if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      E = Bound->getSubExpr()->IgnoreParenImpCasts();
    auto *Construct = dyn_cast<CXXConstructExpr>(E);
    if (!Construct || Construct->getNumArgs()) return false;
    const FunctionDecl *Definition = nullptr;
    if (!Construct->getConstructor()->hasBody(Definition)) return false;
    auto *Body = dyn_cast<CompoundStmt>(Definition->getBody());
    if (!Body || !Body->body_empty()) return false;
    auto *Ctor = cast<CXXConstructorDecl>(Definition);
    bool Found = false;
    for (auto *Field : Ctor->getParent()->fields()) {
      auto T = Field->getType();
      if (!T->isPointerType() ||
          (!objectBorrow(T->getPointeeType()) &&
           !indirectBorrowStorage(T->getPointeeType()))) continue;
      bool Null = false;
      for (auto *Init : Ctor->inits())
        if (Init->isMemberInitializer() && Init->getMember() == Field)
          Null = Init->getInit()->isNullPointerConstant(
                     C, Expr::NPC_ValueDependentIsNotNull) != Expr::NPCK_NotNull;
      if (!Null) return false;
      Found = true;
    }
    return Found;
  }
  void retainCallBorrows(const CallExpr *Call, State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    auto *Callee = Call->getDirectCallee();
    auto *Prototype = callPrototype(Call);
    if (!Callee && !Prototype) return;
    auto Count = Callee ? Callee->getNumParams() : Prototype->getNumParams();
    auto ParameterType = [&](unsigned I) {
      return Callee ? Callee->getParamDecl(I)->getType() : Prototype->getParamType(I);
    };
    unsigned Offset = isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee) ? 1 : 0;
    // A mutable call can retain an element in its indirect storage. Keep all
    // possible origins until the owning storage is replaced or destroyed.
    for (unsigned Receiver = 0; Receiver < Count &&
                                Receiver + Offset < Call->getNumArgs(); ++Receiver) {
      auto ReceiverType = ParameterType(Receiver);
      auto *Borrow = ReceiverType->getAs<BorrowValueType>();
      bool Mutable = Borrow ? !C.circleBorrowIsShared(Borrow)
                            : ReceiverType->isReferenceType() &&
                                  !ReceiverType->getPointeeType().isConstQualified();
      if (!Mutable || !indirectBorrowStorage(ReceiverType)) continue;
      auto *Owner = variable(borrowedPlace(Call->getArg(Receiver + Offset)));
      Vars Owners;
      auto StorageType = Borrow ? Borrow->getPointeeType()
                                : ReceiverType->getPointeeType();
      for (auto *Root : expressionRoots(Call->getArg(Receiver + Offset), S))
        if (C.hasSameUnqualifiedType(Root->getType(), StorageType))
          Owners.insert(Root);
      if (Owners.empty() && Owner) Owners.insert(Owner);
      std::set<const FieldDecl *> ConstructorFields;
      if (ThisOrigin && isa<CXXConstructorDecl>(F))
        if (auto Fields = FieldOrigins.find(ThisOrigin); Fields != FieldOrigins.end())
          for (const auto &[Path, Place] : Fields->second)
            if (Path.size() == 1 && Owners.count(Place) &&
                fieldClassRegion(Path.front())) {
              ConstructorFields.insert(Path.front());
              if (!S.Ready.count(Place))
                error(Call, "constructor member storage is not initialized");
            }
      if (Owners.empty()) {
        error(Call, "indirect borrow storage mutation requires a known owner");
        continue;
      }
      for (unsigned I = 0; I < Count && I + Offset < Call->getNumArgs(); ++I) {
        if (I == Receiver) continue;
        auto Type = ParameterType(I).getNonReferenceType();
        if ((!objectBorrow(Type) && !indirectBorrowStorage(Type)) ||
            !indirectBorrowStorage(ReceiverType, Type)) continue;
        auto Origins = expressionRoots(Call->getArg(I + Offset), S);
        for (auto *Field : ConstructorFields)
          classFieldValue(Field, Call->getArg(I + Offset), nullptr, Call, S);
        if (auto *Move = relocation(Call->getArg(I + Offset)))
          for (auto *Place : ownedPlaces(variable(Move->getSubExpr())))
            Origins.erase(Place);
        if (Origins.empty()) error(Call, "stored element borrow has unknown provenance");
        for (auto *Storage : Owners) {
          auto &Retained = S.RetainedBorrows[Storage];
          Retained.insert(Origins.begin(), Origins.end());
          Retained.erase(Storage);
        }
      }
    }
#endif
  }
  Vars canonicalRegion(const VarDecl *V, const State &S, Vars &Seen) const {
    if (!V || !Seen.insert(V).second)
      return V ? Vars{V} : Vars{};
    if (auto I = ParameterRegions.find(V); I != ParameterRegions.end())
      return canonicalRegion(I->second, S, Seen);
    if (auto I = OriginOwners.find(V); I != OriginOwners.end()) {
      auto *Owner = I->second;
      if (marked(Owner, "safecpp.native.match.subject") ||
          marked(Owner, "safecpp.native.match.binding"))
        return canonicalRegion(Owner, S, Seen);
      return {V};
    }
    if (!marked(V, "safecpp.native.match.subject") &&
        !marked(V, "safecpp.native.match.binding"))
      return {V};
    if (auto I = S.Loans.find(V);
        I != S.Loans.end() && !I->second.Roots.empty()) {
      Vars Result;
      for (auto *Root : I->second.Roots) {
        auto Part = canonicalRegion(Root, S, Seen);
        Result.insert(Part.begin(), Part.end());
      }
      if (!Result.empty()) return Result;
    }
    return {V};
  }
  Vars canonicalRegions(const Vars &Input, const State &S) const {
    Vars Result;
    for (auto *Root : Input) {
      Vars Seen;
      auto Part = canonicalRegion(Root, S, Seen);
      Result.insert(Part.begin(), Part.end());
    }
    return Result;
  }
  void eraseLoan(const VarDecl *V, State &S) {
    S.BorrowStorage.erase(V);
    S.Callables.erase(V);
    auto I = S.Loans.find(V);
    if (I == S.Loans.end())
      return;
    if (marked(V, "safecpp.native.match.subject") ||
        marked(V, "safecpp.native.match.binding"))
      MatchOrigins[V] = I->second.Roots;
    S.Loans.erase(I);
  }
  void resolveMatchStorage(Vars &R, const State &S) {
    // A match subject and its pattern bindings are lowering artifacts. Their
    // loans can name one another (and a subject's own loan can include the
    // subject as an ancestor), so resolve the chain to the user-visible
    // storage instead of copying one artifact root into the result.
    Vars Resolved, Seen;
    auto Add = [&](auto &&Self, const VarDecl *V) -> void {
      if (!V || !Seen.insert(V).second) return;
      if (!marked(V, "safecpp.native.match.subject") &&
          !marked(V, "safecpp.native.match.binding")) {
        Resolved.insert(V);
        return;
      }
      if (auto I = S.Loans.find(V);
          I != S.Loans.end() && !I->second.Roots.empty()) {
        for (auto *Root : I->second.Roots)
          if (Root != V) Self(Self, Root);
      }
      if (auto I = MatchOrigins.find(V);
          I != MatchOrigins.end() && !I->second.empty()) {
        for (auto *Root : I->second)
          if (Root != V) Self(Self, Root);
      }
      if (V->hasInit()) {
        // The match lowering may move a temporary source before the arm
        // binding is formed. Provenance is still the source's pre-move
        // declaration; do not let the flow-state moved bit erase it.
        State Fallback = S;
        Fallback.Moved.clear();
        Fallback.Relocated.clear();
        auto InitRoots = expressionRoots(V->getInit(), Fallback);
        for (auto *Root : InitRoots)
          if (Root != V) Self(Self, Root);
      }
    };
    for (auto *V : R) Add(Add, V);
    R = std::move(Resolved);
  }
  const VarDecl *fieldOrigin(const VarDecl *V, const FieldPath &Field) const {
    auto I = FieldOrigins.find(V);
    if (I == FieldOrigins.end()) return nullptr;
    auto J = I->second.find(Field);
    return J == I->second.end() ? nullptr : J->second;
  }
  Vars ownedPlaces(const VarDecl *V, const FieldPath &Path = {}) const {
    Vars R;
    if (!V) return R;
    if (Path.empty()) R.insert(V);
    if (auto I = FieldOrigins.find(V); I != FieldOrigins.end())
      for (const auto &[Field, Origin] : I->second)
        if (prefixPath(Path, Field)) R.insert(Origin);
    return R;
  }
  bool ownsMoveSource(const Expr *E, unsigned Depth = 0) const {
    if (!E || Depth > 32) return false;
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cast = dyn_cast<CastExpr>(E)) return ownsMoveSource(Cast->getSubExpr(), Depth + 1);
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E)) return ownsMoveSource(Cleanup->getSubExpr(), Depth + 1);
    if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(E)) return Temporary->getSubExpr()->isPRValue();
    if (auto *Array = dyn_cast<ArraySubscriptExpr>(E)) return ownsMoveSource(Array->getBase(), Depth + 1);
    if (auto *Choice = dyn_cast<ConditionalOperator>(E))
      return ownsMoveSource(Choice->getTrueExpr(), Depth + 1) && ownsMoveSource(Choice->getFalseExpr(), Depth + 1);
    if (auto *Choice = dyn_cast<BinaryConditionalOperator>(E))
      return ownsMoveSource(Choice->getCommon(), Depth + 1) && ownsMoveSource(Choice->getFalseExpr(), Depth + 1);
    if (auto *Binary = dyn_cast<BinaryOperator>(E)) {
      if (Binary->getOpcode() == BO_Comma) return ownsMoveSource(Binary->getRHS(), Depth + 1);
      if (Binary->isAssignmentOp()) return ownsMoveSource(Binary->getLHS(), Depth + 1);
      return false;
    }
    if (auto *U = dyn_cast<UnaryOperator>(E); U && nativeBorrow(U)) return false;
    if (auto *Call = dyn_cast<CallExpr>(E); Call && E->isGLValue()) {
      auto *Callee = Call->getDirectCallee();
      if (!Callee || isa<CXXMethodDecl>(Callee) || !Callee->getReturnType()->isRValueReferenceType()) return false;
      auto From = borrowedParameters(Callee);
      return From.size() == 1 && *From.begin() < Call->getNumArgs() &&
             ownsMoveSource(Call->getArg(*From.begin()), Depth + 1);
    }
    if (auto *Ref = dyn_cast<DeclRefExpr>(E))
      if (auto *V = dyn_cast<VarDecl>(Ref->getDecl()); V &&
          (Ref->refersToEnclosingVariableOrCapture() || V->isInitCapture() ||
           !V->hasLocalStorage() || V->getDeclContext() != F)) return false;
    if (auto *V = variable(E); V && V->getType()->isReferenceType()) {
      auto *P = dyn_cast<ParmVarDecl>(V);
      if (!P || !P->getType()->isRValueReferenceType()) return false;
      if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F); Ctor && Ctor->isMoveConstructor())
        return Ctor->getNumParams() && P == Ctor->getParamDecl(0);
      if (auto *Method = dyn_cast<CXXMethodDecl>(F); Method && Method->isMoveAssignmentOperator())
        return Method->getNumParams() && P == Method->getParamDecl(0);
      if (auto Transfer = transferredBorrow(F))
        return *Transfer < F->getNumParams() && P == F->getParamDecl(*Transfer);
      return false;
    }
    if (auto *Member = dyn_cast<MemberExpr>(E)) return ownsMoveSource(Member->getBase(), Depth + 1);
    if (isa<CXXThisExpr>(E)) return consumingReceiver(dyn_cast<CXXMethodDecl>(F));
    if (auto *U = dyn_cast<UnaryOperator>(E); U && U->getOpcode() == UO_Deref)
      return ownsMoveSource(U->getSubExpr(), Depth + 1);
    return isa<DeclRefExpr>(E) || E->isPRValue();
  }
  bool projectedRecord(QualType T) const {
#ifdef MODULE_SAFETY_BUILTIN
    if (T->isReferenceType()) return false;
    auto *R = T->getAsCXXRecordDecl();
    if (!R || !R->hasDefinition()) return false;
    R = R->getDefinition();
    // Imported native records keep their field model even when the consumer
    // enables only module safety. Plain Clang records retain the old path.
    if (!C.getLangOpts().CircleBorrowValues &&
        !circleRecordHasLifetimeBinderParameter(R) &&
        circleClassLifetimeNames(R).empty()) return false;
    if (R->isUnion() || R->getNumBases() || R->hasUserDeclaredDestructor()) return false;
    bool Found = false;
    for (const auto *Field : R->fields()) {
      if (Field->isCirclePhantom()) continue;
      if (Field->isBitField() || Field->hasAttr<NoUniqueAddressAttr>()) return false;
      if (!objectBorrow(Field->getType())) continue;
      Found = true;
      // A choice projects its active alternative out of a generated union
      // storage. The payload walker resolves the active field from the match
      // lowering rather than treating the union as owning a single region.
      if (auto *FieldRecord = Field->getType()->getAsCXXRecordDecl())
        if (FieldRecord->hasDefinition() &&
            marked(FieldRecord->getDefinition(), "safecpp.native.choice.storage"))
          continue;
      if (!Field->getType()->getAs<BorrowValueType>() &&
          !circleIsCallableValue(Field->getType()) &&
          !projectedRecord(Field->getType())) return false;
    }
    return Found;
#else
    return false;
#endif
  }
  bool projectedLifetimeRecord(QualType T) const {
#ifdef MODULE_SAFETY_BUILTIN
    if (T->isReferenceType()) return false;
    auto *R = T->getAsCXXRecordDecl();
    if (!R || !R->hasDefinition()) return false;
    R = R->getDefinition();
    if (!C.getLangOpts().CircleBorrowValues &&
        !circleRecordHasLifetimeBinderParameter(R) &&
        circleClassLifetimeNames(R).empty()) return false;
    if (R->isUnion() || R->getNumBases()) return false;
    bool Found = false;
    for (const auto *Field : R->fields()) {
      if (Field->isCirclePhantom()) continue;
      if (Field->isBitField() || Field->hasAttr<NoUniqueAddressAttr>()) return false;
      if (objectBorrow(Field->getType())) {
        Found = true;
        continue;
      }
      auto *FieldRecord = Field->getType()->getAsCXXRecordDecl();
      if (FieldRecord && FieldRecord->hasDefinition() &&
          marked(FieldRecord->getDefinition(), "safecpp.native.choice.storage"))
        continue;
      if (Field->getType()->getAs<BorrowValueType>()) {
        Found = true;
        continue;
      }
      if (FieldRecord && !projectedLifetimeRecord(Field->getType()))
        return false;
    }
    return Found;
#else
    return false;
#endif
  }
  // Phantom fields carry lifetime metadata but no storage. A default-
  // constructed holder whose only borrow-carrying field is phantom has no
  // live referent to project; its regions are supplied later by operations
  // such as `push` or by an explicit lifetime binding.
  bool phantomOnlyBorrow(QualType T) const {
#ifdef MODULE_SAFETY_BUILTIN
    auto *Record = circleClassRecord(T);
    if (!Record || !Record->hasDefinition()) return false;
    bool SawPhantom = false;
    for (const auto *Field : Record->getDefinition()->fields()) {
      if (Field->isCirclePhantom()) {
        SawPhantom = true;
        continue;
      }
      if (objectBorrow(Field->getType())) return false;
    }
    return SawPhantom;
#else
    return false;
#endif
  }
  Vars fieldRoots(const VarDecl *Owner, const FieldPath &Path, const State &S) const {
    Vars R;
    if (auto I = S.Fields.find(Owner); I != S.Fields.end())
      for (const auto &[P, L] : I->second)
        if (prefixPath(Path, P)) R.insert(L.Roots.begin(), L.Roots.end());
    return R;
  }
  void refreshFields(const VarDecl *Owner, State &S) {
    Loan Combined;
    Combined.WriteRoots.emplace();
    if (auto I = S.Loans.find(Owner); I != S.Loans.end())
      Combined.Parents = I->second.Parents;
    for (const auto &[P, L] : S.Fields[Owner]) {
      Combined.Roots.insert(L.Roots.begin(), L.Roots.end());
      Combined.Exclusive |= L.Exclusive;
      for (auto *Root : L.Roots)
        if (L.exclusiveAt(Root)) Combined.WriteRoots->insert(Root);
    }
    S.Loans[Owner] = std::move(Combined);
  }
  void retireFields(const VarDecl *Owner, const FieldPath &Path, State &S) {
    if (auto C = S.Callables.find(Owner); C != S.Callables.end()) {
      for (auto P = C->second.begin(); P != C->second.end();) {
        if (prefixPath(Path, P->first)) P = C->second.erase(P); else ++P;
      }
    }
    auto I = S.Fields.find(Owner);
    if (I == S.Fields.end()) return;
    for (auto P = I->second.begin(); P != I->second.end();)
      if (prefixPath(Path, P->first)) P = I->second.erase(P); else ++P;
    refreshFields(Owner, S);
  }
  unsigned projectedFunctionRegion(const FunctionProtoType *Type,
                                   unsigned Position, unsigned Region) const {
    return modulesafety::projectedFunctionRegion(Type, Position, Region);
  }
  bool functionRegionOutlives(const FunctionProtoType *Type,
                              unsigned Long, unsigned Short) const {
    return modulesafety::functionRegionOutlives(Type, Long, Short);
  }
  unsigned functionRootRegion(const VarDecl *Root) const {
#ifdef MODULE_SAFETY_BUILTIN
    auto *Type = F->getType()->getAs<FunctionProtoType>();
    if (!Type) return 0;
    const VarDecl *Parameter = Root;
    unsigned Region = 0;
    if (auto I = ClassRegions.find(Root); I != ClassRegions.end()) {
      Parameter = I->second.Parameter;
      Region = I->second.Index;
    } else if (auto I = ParameterRegions.find(Root); I != ParameterRegions.end())
      Parameter = I->second;
    for (unsigned I = 0; I < F->getNumParams(); ++I)
      if (F->getParamDecl(I) == Parameter) {
        if (Region)
          return projectedFunctionRegion(Type, I + 1, Region);
        return circleFunctionRegion(Type, I + 1);
      }
#endif
    return 0;
  }
  bool originOutlives(const VarDecl *Long, const VarDecl *Short, const State &S) {
    if (Long == Short) return true;
#ifdef MODULE_SAFETY_BUILTIN
    auto L = ClassRegions.find(Long), R = ClassRegions.find(Short);
    if (L != ClassRegions.end() && R != ClassRegions.end() &&
        L->second.Parameter == R->second.Parameter &&
        L->second.Record == R->second.Record &&
        circleClassRegionOutlives(L->second.Record, L->second.Index, R->second.Index))
      return true;
#endif
    Vars Seen;
    if (permanentRoot(Long, S, Seen)) return true;
    if (functionRegionOutlives(F->getType()->getAs<FunctionProtoType>(),
                              functionRootRegion(Long), functionRootRegion(Short)))
      return true;
    auto Owner = [&](const VarDecl *Root) {
      Vars Visited;
      while (Visited.insert(Root).second) {
        auto I = OriginOwners.find(Root);
        if (I == OriginOwners.end()) break;
        Root = I->second;
      }
      return Root;
    };
    auto *LongOwner = Owner(Long), *ShortOwner = Owner(Short);
    auto ShortScope = Context.Scopes.find(ShortOwner);
    if (ShortScope == Context.Scopes.end()) return false;
    // An external parameter region is valid throughout this invocation.
    if (ParameterRegions.count(Long) || isa<ParmVarDecl>(LongOwner)) return true;
    auto LongScope = Context.Scopes.find(LongOwner);
    if (LongScope == Context.Scopes.end()) return false;
    const Stmt *Scope = ShortScope->second;
    while (Scope) {
      if (Scope == LongScope->second) return true;
      auto Parents = parentNodes(*Scope);
      if (Parents.size() != 1) break;
      Scope = Parents[0].get<Stmt>();
    }
    return false;
  }
  void classArgumentContracts(const FunctionProtoType *Type,
      const std::vector<std::pair<const Expr *, QualType>> &Arguments,
      const Stmt *At, const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    if (!Type) return;
    auto Projections = Type->getClassLifetimeBindings();
    for (unsigned I = 0; I + 2 < Projections.size(); I += 3) {
      unsigned Position = Projections[I];
      if (!Position || Position > Arguments.size()) continue;
      auto [Argument, ParameterType] = Arguments[Position - 1];
      auto *Borrow = ParameterType->getAs<BorrowValueType>();
      auto *Record = circleClassRecord(ParameterType);
      if (!Record && circleIsCallableValue(ParameterType)) {
        auto Captures = circleCallableCaptures(Argument->IgnoreParenImpCasts()->getType());
        if (Captures.empty()) continue; // closed code can instantiate its binders
        unsigned Region = Projections[I + 1];
        if (!Region || Region > Captures.size()) {
          contractError(At, "callback capture layout does not match its lifetime contract");
          continue;
        }
        auto Existing = callableRegionRoots(Argument, Captures[Region - 1], S);
        auto V = circle_relation::FunctionRelation(C).callableVariance(ParameterType, Region);
        circleForEachFunctionRegionSource(Type, Projections[I + 2],
            [&](unsigned P, unsigned R) {
              if (P >= Arguments.size() || (P + 1 == Position && R == Region)) return;
              auto Source = Arguments[P].first;
              auto Sources = R ? classRegionRoots(Source, circleClassRecord(Arguments[P].second), R, S)
                               : expressionRoots(Source, S);
              bool Valid = !Existing.empty() && !Sources.empty();
              for (auto *A : Existing) for (auto *B : Sources) {
                if (V == circle_relation::Variance::Covariant || V == circle_relation::Variance::Invariant)
                  Valid &= originOutlives(A, B, S);
                if (V == circle_relation::Variance::Contravariant || V == circle_relation::Variance::Invariant)
                  Valid &= originOutlives(B, A, S);
              }
              if (!Valid) contractError(At, "callback argument does not preserve its captured lifetime region");
            });
        continue;
      }
      if (!Record) continue;
      auto Existing = classRegionRoots(borrowedPlace(Argument), Record,
                                      Projections[I + 1], S);
      if (circleFunctionRegionIsStatic(Type, Projections[I + 2])) {
        bool Valid = !Existing.empty();
        for (auto *Root : Existing) {
          Vars Seen;
          Valid &= permanentRoot(Root, S, Seen);
        }
        if (!Valid)
          contractError(At, "static class argument requires permanent lifetime regions");
      }
      if (!Borrow || C.circleBorrowIsShared(Borrow)) continue;
      auto Check = [&](const Vars &Sources) {
        bool Valid = !Existing.empty() && !Sources.empty();
        for (auto *Source : Sources)
          for (auto *Destination : Existing)
            Valid &= originOutlives(Source, Destination, S);
        if (!Valid)
          contractError(At, "mutable class argument does not preserve its lifetime region");
      };
      circleForEachFunctionRegionSource(Type, Projections[I + 2],
          [&](unsigned P, unsigned Region) {
            if (P >= Arguments.size()) { Check({}); return; }
            if (P + 1 == Position && Region == Projections[I + 1]) return;
            auto [Source, SourceType] = Arguments[P];
            Check(Region ? classRegionRoots(borrowedPlace(Source),
                                             circleClassRecord(SourceType), Region, S)
                         : expressionRoots(Source, S));
          });
    }
#endif
  }
  void argumentLifetimeContracts(const FunctionProtoType *Type,
      const std::vector<std::pair<const Expr *, QualType>> &Arguments,
      const Stmt *At, const State &S, const Expr *Callable = nullptr) {
    staticArgumentContracts(Type, Arguments, At, S);
    classArgumentContracts(Type, Arguments, At, S);
#ifdef MODULE_SAFETY_BUILTIN
    if (!Type || !Callable) return;
    for (unsigned I = 0; I < Type->getNumParams() && I < Arguments.size(); ++I) {
      unsigned ID = circleFunctionRegion(Type, I + 1);
      if (!circleRegionIsCapture(ID)) continue;
      auto Required = callableRegionRoots(Callable, ID, S);
      auto Actual = expressionRoots(Arguments[I].first, S);
      bool Valid = !Required.empty() && !Actual.empty();
      for (auto *A : Actual) for (auto *B : Required) Valid &= originOutlives(A, B, S);
      if (!Valid) contractError(At, "callback argument does not preserve its captured lifetime region");
    }
#endif
  }
  unsigned constructorParameterRegion(const ParmVarDecl *P,
                                      const CXXRecordDecl *R,
                                      const FunctionDecl *Owner = nullptr) const {
#ifdef MODULE_SAFETY_BUILTIN
    auto *FT = (Owner ? Owner : F)->getType()->getAs<FunctionProtoType>();
    if (!FT || !FT->getLifetimeBindings().empty()) return 0;
    for (auto *A : P->specific_attrs<AnnotateAttr>()) {
      auto Text = A->getAnnotation();
      if (A->isImplicit() && Text.consume_front("safecpp.native.lifetime:"))
        return circleClassLifetimeIndex(R, Text);
    }
    auto Names = modulesafety::classLifetimeBindingNames(P->getType());
    if (Names.size() == 1)
      return circleClassLifetimeIndex(R, Names.front());
#endif
    return 0;
  }
  unsigned mappedFieldRegion(const FieldDecl *Field, unsigned Region) const {
#ifdef MODULE_SAFETY_BUILTIN
    return circleMappedFieldRegion(Field, Region);
#else
    return 0;
#endif
  }
  unsigned mappedPathRegion(const FieldPath &Path, unsigned Region = 1) const {
    for (auto I = Path.rbegin(); I != Path.rend(); ++I) {
      Region = mappedFieldRegion(*I, Region);
      if (!Region || Region == 0x40000000u) return Region;
    }
    return Region;
  }
#ifdef MODULE_SAFETY_BUILTIN
  Vars enclosingRegionRoots(unsigned ID, const State &S) {
    auto *FT = F->getType()->getAs<FunctionProtoType>();
    Vars Result;
    if (circleFunctionRegionIsStatic(FT, ID)) return {StaticOrigin};
    for (const auto &[Root, P] : ParameterRegions)
      if (circleFunctionRegionOutlives(FT, functionRootRegion(Root), ID)) Result.insert(Root);
    for (auto *P : F->parameters())
      if (circleFunctionRegionOutlives(FT, functionRootRegion(P), ID)) {
        auto R = roots(P, S); Result.insert(R.begin(), R.end());
      }
    return Result;
  }
  Vars callableRegionRoots(const Expr *E, unsigned Capture, const State &S) {
    E = evaluationSource(E);
    if (!E) return {};
    if (const auto *Cast = dyn_cast<CastExpr>(E)) {
      auto SourceCaptures = circleCallableCaptures(Cast->getSubExpr()->getType());
      if (llvm::is_contained(SourceCaptures, Capture))
        return callableRegionRoots(Cast->getSubExpr(), Capture, S);
      // Instantiating closed polymorphic code in the current region scope.
      if (SourceCaptures.empty()) {
        if (circleCaptureDepth(Capture) == 1) {
          auto Roots = enclosingRegionRoots(circleCaptureSlot(Capture), S);
          if (!Roots.empty()) return Roots;
        }
        return {StaticOrigin};
      }
      Vars Result;
      for (unsigned ID : SourceCaptures) {
        auto Part = callableRegionRoots(Cast->getSubExpr(), ID, S);
        if (Part.empty()) return {};
        Result.insert(Part.begin(), Part.end());
      }
      return Result;
    }
    E = evaluationSource(E->IgnoreParens());
    if (const auto *W = dyn_cast<ExprWithCleanups>(E)) return callableRegionRoots(W->getSubExpr(), Capture, S);
    if (const auto *W = dyn_cast<MaterializeTemporaryExpr>(E)) return callableRegionRoots(W->getSubExpr(), Capture, S);
    if (const auto *W = dyn_cast<CXXBindTemporaryExpr>(E)) return callableRegionRoots(W->getSubExpr(), Capture, S);
    if (const auto *W = dyn_cast<CXXDefaultArgExpr>(E)) return callableRegionRoots(W->getExpr(), Capture, S);
    if (const auto *U = relocation(E)) return callableRegionRoots(U->getSubExpr(), Capture, S);
    if (const auto *B = dyn_cast<BinaryOperator>(E); B && B->getOpcode() == BO_Comma)
      return callableRegionRoots(B->getRHS(), Capture, S);
    if (const auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      auto A = callableRegionRoots(Choice->getTrueExpr(), Capture, S);
      auto B = callableRegionRoots(Choice->getFalseExpr(), Capture, S);
      if (A.empty() || B.empty()) return {};
      A.insert(B.begin(), B.end()); return A;
    }
    if (const auto *Call = dyn_cast<CallExpr>(E)) {
      auto *FT = callPrototype(Call);
      if (!FT) return {};
      if (circleCaptureDepth(Capture) > 1)
        return callableRegionRoots(Call->getCallee(),
            circleCapturedRegion(circleCaptureDepth(Capture) - 1, circleCaptureSlot(Capture)), S);
      unsigned Destination = circleCaptureSlot(Capture);
      Vars Result;
      for (unsigned I = 0; I < FT->getNumParams() && I < Call->getNumArgs(); ++I) {
        auto Part = argumentRegionRoots(Call->getArg(I), FT, I, Destination, S);
        Result.insert(Part.begin(), Part.end());
      }
      return Result;
    }
    if (auto *V = variable(E)) {
      auto Path = ownedFieldPath(E);
      if (auto I = S.Callables.find(V); I != S.Callables.end())
        if (auto J = I->second.find(Path); J != I->second.end())
          if (auto K = J->second.find(Capture); K != J->second.end()) return K->second;
      if (isa<ParmVarDecl>(V) && Path.empty() &&
          !isa<MemberExpr>(E->IgnoreParenImpCasts()) && circleCaptureDepth(Capture) == 1)
        return enclosingRegionRoots(circleCaptureSlot(Capture), S);
    }
    // A member of a temporary call result has no owning VarDecl. Its capture
    // still projects through the returned class's independent region slots.
    if (const auto *Member = dyn_cast<MemberExpr>(E->IgnoreParenImpCasts()))
      if (const auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl())) {
        auto Captures = circleCallableCaptures(Field->getType());
        auto I = llvm::find(Captures, Capture);
        if (I != Captures.end()) {
          unsigned Region = mappedFieldRegion(Field, unsigned(I - Captures.begin()) + 1);
          if (Region == 0x40000000u) return {StaticOrigin};
          if (Region) return classRegionRoots(Member->getBase(),
              cast<CXXRecordDecl>(Field->getParent()), Region, S);
        }
      }
    return {};
  }
  CallableRegions callableRegions(const Expr *E, QualType Type, const State &S) {
    CallableRegions Result;
    if (circleIsCallableValue(Type))
      for (unsigned ID : circleCallableCaptures(Type)) Result[ID] = callableRegionRoots(E, ID, S);
    return Result;
  }
  Vars callableFieldRegionRoots(const Expr *E, const FieldPath &Path,
                               unsigned Role, const State &S) {
    if (!E || !Role) return {};
    if (Path.empty()) {
      if (!circleIsCallableValue(E->getType())) return {};
      auto Captures = circleCallableCaptures(E->getType());
      if (Captures.empty()) return {StaticOrigin};
      return Role <= Captures.size() ? callableRegionRoots(E, Captures[Role - 1], S) : Vars{};
    }
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *W = dyn_cast<ExprWithCleanups>(E))
      return callableFieldRegionRoots(W->getSubExpr(), Path, Role, S);
    if (const auto *W = dyn_cast<MaterializeTemporaryExpr>(E))
      return callableFieldRegionRoots(W->getSubExpr(), Path, Role, S);
    if (const auto *W = dyn_cast<CXXBindTemporaryExpr>(E))
      return callableFieldRegionRoots(W->getSubExpr(), Path, Role, S);
    if (const auto *W = dyn_cast<CXXDefaultInitExpr>(E))
      return callableFieldRegionRoots(W->getExpr(), Path, Role, S);
    if (const auto *U = relocation(E))
      return callableFieldRegionRoots(U->getSubExpr(), Path, Role, S);
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && Construct->getConstructor()->isImplicit() &&
        Construct->getConstructor()->isCopyOrMoveConstructor() && Construct->getNumArgs() == 1)
      return callableFieldRegionRoots(Construct->getArg(0), Path, Role, S);
    if (const auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      auto Left = callableFieldRegionRoots(Choice->getTrueExpr(), Path, Role, S);
      auto Right = callableFieldRegionRoots(Choice->getFalseExpr(), Path, Role, S);
      if (Left.empty() || Right.empty()) return {};
      Left.insert(Right.begin(), Right.end()); return Left;
    }
    if (const auto *List = dyn_cast<InitListExpr>(E)) {
      auto *Record = circleClassRecord(List->getType());
      if (!Record || !Record->hasDefinition()) return {};
      unsigned Index = 0;
      for (const auto *Field : Record->getDefinition()->fields()) {
        if (Index >= List->getNumInits()) return {};
        if (Field == Path.front())
          return callableFieldRegionRoots(List->getInit(Index),
              FieldPath(Path.begin() + 1, Path.end()), Role, S);
        ++Index;
      }
      return {};
    }
    if (auto *Owner = variable(E)) {
      auto Key = ownedFieldPath(E);
      Key.insert(Key.end(), Path.begin(), Path.end());
      if (auto I = S.Callables.find(Owner); I != S.Callables.end())
        if (auto J = I->second.find(Key); J != I->second.end()) {
          auto Captures = circleCallableCaptures(Path.back()->getType());
          if (Role > Captures.size()) return {};
          auto K = J->second.find(Captures[Role - 1]);
          return K != J->second.end() ? K->second : Vars{};
        }
    }
    unsigned Region = mappedPathRegion(Path, Role);
    if (const auto *Call = dyn_cast<CallExpr>(E)) {
      // Missing projections are unknown. Falling back to the merged payload
      // would re-enter this same query and lose the individual capture role.
      if (!projectedFunctionRegion(callPrototype(Call), 0, Region)) return {};
    } else if (!variable(E)) return {};
    return classRegionRoots(E, circleClassRecord(E->getType()), Region, S);
  }
  void rememberCallableFields(const VarDecl *Owner, const Expr *E, QualType T,
                              State &S, FieldPath Prefix = {}) {
    if (!E) return;
    if (circleIsCallableValue(T)) {
      S.Callables[Owner][Prefix] = callableRegions(E, T, S);
      return;
    }
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *W = dyn_cast<ExprWithCleanups>(E)) E = W->getSubExpr()->IgnoreParenImpCasts();
    if (const auto *U = relocation(E)) E = U->getSubExpr()->IgnoreParenImpCasts();
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && Construct->getConstructor()->isImplicit() &&
        Construct->getConstructor()->isCopyOrMoveConstructor() && Construct->getNumArgs() == 1)
      E = Construct->getArg(0)->IgnoreParenImpCasts();
    if (const auto *Source = variable(E)) {
      auto Values = S.Callables.count(Source) ? S.Callables.at(Source)
                                             : std::map<FieldPath, CallableRegions>{};
      auto SourcePath = ownedFieldPath(E);
      auto &Saved = S.Callables[Owner];
      for (auto I = Saved.begin(); I != Saved.end();)
        if (prefixPath(Prefix, I->first)) I = Saved.erase(I); else ++I;
      for (const auto &[Path, Regions] : Values) {
        if (!prefixPath(SourcePath, Path)) continue;
        auto Destination = Prefix;
        Destination.insert(Destination.end(), Path.begin() + SourcePath.size(), Path.end());
        Saved[Destination] = Regions;
      }
      return;
    }
    auto *Record = circleClassRecord(T);
    if (!Record || !Record->hasDefinition()) return;
    if (const auto *List = dyn_cast<InitListExpr>(E)) {
      unsigned I = 0;
      for (const auto *Field : Record->getDefinition()->fields()) {
        if (I >= List->getNumInits()) break;
        auto Path = Prefix; Path.push_back(Field);
        rememberCallableFields(Owner, List->getInit(I++), Field->getType(), S, Path);
      }
    } else if (const auto *Call = dyn_cast<CallExpr>(E)) {
      auto *FT = callPrototype(Call);
      if (!FT) return;
      auto Add = [&](auto &&Self, const CXXRecordDecl *R, FieldPath Path) -> void {
        for (const auto *Field : R->getDefinition()->fields()) {
          auto Next = Path; Next.push_back(Field);
          if (circleIsCallableValue(Field->getType())) {
            auto Captures = circleCallableCaptures(Field->getType());
            for (unsigned I = 0; I < Captures.size(); ++I) {
              FieldPath Relative(Next.begin() + Prefix.size(), Next.end());
              unsigned Destination = projectedFunctionRegion(FT, 0, mappedPathRegion(Relative, I + 1));
              Vars Roots;
              if (Destination == 0x40000000u) Roots.insert(StaticOrigin);
              else if (circleRegionIsCapture(Destination)) Roots = callableRegionRoots(Call->getCallee(), Destination, S);
              else for (unsigned P = 0; P < FT->getNumParams() && P < Call->getNumArgs(); ++P) {
                auto Part = argumentRegionRoots(Call->getArg(P), FT, P, Destination, S);
                Roots.insert(Part.begin(), Part.end());
              }
              S.Callables[Owner][Next][Captures[I]] = std::move(Roots);
            }
          } else if (auto *Nested = circleClassRecord(Field->getType());
                     Nested && Nested->hasDefinition() && !Field->getType()->getAs<BorrowValueType>())
            Self(Self, Nested, Next);
        }
      };
      Add(Add, Record, Prefix);
    }
  }
#endif
  Vars classRegionRoots(const Expr *E, const CXXRecordDecl *R, unsigned Region,
                        const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    if (!E || !Region) return {};
    if (!R && circleIsCallableValue(E->getType())) {
      auto Captures = circleCallableCaptures(E->getType());
      return Region <= Captures.size() ? callableRegionRoots(E, Captures[Region - 1], S) : Vars{};
    }
    if (!R) return {};
    const Expr *Place = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *Cleanup = dyn_cast<ExprWithCleanups>(Place))
      return classRegionRoots(Cleanup->getSubExpr(), R, Region, S);
    if (const auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Place))
      return classRegionRoots(Temporary->getSubExpr(), R, Region, S);
    if (const auto *Bound = dyn_cast<CXXBindTemporaryExpr>(Place))
      return classRegionRoots(Bound->getSubExpr(), R, Region, S);
    if (const auto *Cast = dyn_cast<CastExpr>(Place);
        Cast && (Cast->getCastKind() == CK_NoOp ||
                 Cast->getCastKind() == CK_ConstructorConversion) &&
        C.hasSameUnqualifiedType(Cast->getType(), Cast->getSubExpr()->getType()))
      return classRegionRoots(Cast->getSubExpr(), R, Region, S);
    if (const auto *Default = dyn_cast<CXXDefaultArgExpr>(Place))
      return classRegionRoots(Default->getExpr(), R, Region, S);
    if (const auto *Default = dyn_cast<CXXDefaultInitExpr>(Place))
      return classRegionRoots(Default->getExpr(), R, Region, S);
    if (const auto *Move = relocation(Place))
      return classRegionRoots(Move->getSubExpr(), R, Region, S);
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(Place);
        Construct && Construct->getConstructor()->isImplicit() &&
        Construct->getConstructor()->isCopyOrMoveConstructor() &&
        Construct->getNumArgs() == 1)
      return classRegionRoots(Construct->getArg(0), R, Region, S);
    if (auto *Unary = dyn_cast<UnaryOperator>(Place);
        Unary && (nativeBorrow(Unary) || nativeBorrowDereference(Unary)))
      return classRegionRoots(Unary->getSubExpr(), R, Region, S);
    if (auto *Member = dyn_cast<MemberExpr>(Place))
      if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
          Field && circleClassRecord(Field->getType()) &&
          circleClassRecord(Field->getType())->getCanonicalDecl() == R->getCanonicalDecl()) {
        if (Field->getType()->getAs<BorrowValueType>()) return {};
        unsigned Mapped = mappedFieldRegion(Field, Region);
        if (Mapped == 0x40000000u) return {StaticOrigin};
        return Mapped ? classRegionRoots(Member->getBase(),
            cast<CXXRecordDecl>(Field->getParent()), Mapped, S) : Vars{};
      }
    auto Select = [&](const FieldLoans &Fields, const FieldPath &Prefix = {}) {
      Vars Result;
      bool Found = false;
      for (const auto &[Path, Loan] : Fields) {
        if (!prefixPath(Prefix, Path)) continue;
        // Compose the leaf's region through every enclosing class binding.
        // Field ordinals alone cannot distinguish remapped nested regions.
        unsigned Mapped = mappedPathRegion(Path);
        if (Mapped != 0x40000000u && !circleClassRegionOutlives(R, Mapped, Region)) continue;
        if (Loan.Roots.empty()) return Vars{};
        Found = true;
        Result.insert(Loan.Roots.begin(), Loan.Roots.end());
      }
      return Found ? Result : Vars{};
    };
    const VarDecl *V = variable(E);
    if (isa<CXXThisExpr>(E->IgnoreParenImpCasts())) V = ThisOrigin;
    if (V) {
      if (Region == 1 && circleClassLifetimeNames(R).size() == 1)
        if (auto I = S.RetainedBorrows.find(V); I != S.RetainedBorrows.end())
          return I->second;
      if (auto I = S.Fields.find(V); I != S.Fields.end()) {
        auto Fields = I->second;
        Vars Captured;
        bool FoundCapture = false;
        if (auto Calls = S.Callables.find(V); Calls != S.Callables.end())
          for (const auto &[Path, Values] : Calls->second) {
            if (!prefixPath(ownedFieldPath(E), Path) || Path.empty()) continue;
            Fields.erase(Path);
            auto Layout = circleCallableCaptures(Path.back()->getType());
            for (unsigned J = 0; J < Layout.size(); ++J) {
              unsigned Mapped = mappedPathRegion(Path, J + 1);
              if (Mapped != 0x40000000u && !circleClassRegionOutlives(R, Mapped, Region)) continue;
              auto K = Values.find(Layout[J]);
              if (K == Values.end() || K->second.empty()) return {};
              FoundCapture = true;
              Captured.insert(K->second.begin(), K->second.end());
            }
          }
        auto Result = Select(Fields, ownedFieldPath(E));
        if (FoundCapture) Result.insert(Captured.begin(), Captured.end());
        if (V == ThisOrigin && isa<CXXConstructorDecl>(F))
          if (auto Fields = FieldOrigins.find(V); Fields != FieldOrigins.end())
            for (const auto &[Path, Place] : Fields->second)
              if (Path.size() == 1 && circleClassRegionOutlives(
                      R, fieldClassRegion(Path.front()), Region)) {
                auto Retained = retainedOrigins({Place}, S);
                Result.insert(Retained.begin(), Retained.end());
              }
        return Result;
      }
      Vars Result;
      for (auto *Root : roots(V, S)) {
        if (auto P = ParameterRegions.find(Root); P != ParameterRegions.end())
          Root = P->second;
        auto *Owner = circleClassRecord(Root->getType());
        if (!Owner || Owner->getCanonicalDecl() != R->getCanonicalDecl()) continue;
        if (auto I = S.Fields.find(Root); I != S.Fields.end()) {
          auto Part = Select(I->second);
          if (Part.empty()) return {};
          Result.insert(Part.begin(), Part.end());
        } else if (Region == 1 && circleClassLifetimeNames(R).size() == 1) {
          // An alias of indirect storage carries the same saved data region.
          // This aggregate summary cannot identify one of several regions.
          auto I = S.RetainedBorrows.find(Root);
          if (I == S.RetainedBorrows.end() || I->second.empty()) return {};
          Result.insert(I->second.begin(), I->second.end());
        }
      }
      if (!Result.empty()) return Result;
    }
    if (const auto *Call = dyn_cast<CallExpr>(Place)) {
      auto *Type = callPrototype(Call);
      unsigned Destination = projectedFunctionRegion(Type, 0, Region);
      if (Destination) {
        if (Destination == 0x40000000u) return {StaticOrigin};
        if (circleRegionIsCapture(Destination))
          return callableRegionRoots(Call->getCallee(), Destination, S);
        auto *Callee = callCallee(Call);
        unsigned Offset = Callee && isa<CXXOperatorCallExpr>(Call) &&
                                  implicitObjectMethod(Callee) ? 1u : 0u;
        Vars Result;
        bool Known = true;
        for (unsigned I = 0; I < Type->getNumParams() && I + Offset < Call->getNumArgs(); ++I) {
          if (!circleFunctionParameterSuppliesRegion(Type, I, Destination)) continue;
          if (closedCallableSource(Call->getArg(I + Offset), Type->getParamType(I))) continue;
          auto Part = argumentRegionRoots(Call->getArg(I + Offset), Type, I, Destination, S);
          Known &= !Part.empty();
          Result.insert(Part.begin(), Part.end());
        }
        return Known ? Result : Vars{};
      }
    }
    FieldLoans Fields;
    if (projectedPayload(E, C.getCanonicalTagType(R), S, Fields)) {
      Vars Captured;
      for (auto I = Fields.begin(); I != Fields.end();) {
        const auto &Path = I->first;
        if (Path.empty() || !circleIsCallableValue(Path.back()->getType())) { ++I; continue; }
        auto Layout = circleCallableCaptures(Path.back()->getType());
        for (unsigned Role = 1; Role <= Layout.size(); ++Role) {
          unsigned Mapped = mappedPathRegion(Path, Role);
          if (Mapped != 0x40000000u && !circleClassRegionOutlives(R, Mapped, Region)) continue;
          auto Part = callableFieldRegionRoots(E, Path, Role, S);
          if (Part.empty()) return {};
          Captured.insert(Part.begin(), Part.end());
        }
        I = Fields.erase(I);
      }
      auto Result = Select(Fields);
      Result.insert(Captured.begin(), Captured.end());
      return Result;
    }
#endif
    return {};
  }
  Vars argumentRegionRoots(const Expr *Argument, const FunctionProtoType *Type,
                           unsigned Index, unsigned Destination,
                           const State &S) {
    if (!Type || Index >= Type->getNumParams()) return {};
    QualType Parameter = Type->getParamType(Index);
#ifdef MODULE_SAFETY_BUILTIN
    Vars Result;
    bool Known = true;
    circleForEachFunctionRegionSource(Type, Destination,
        [&](unsigned P, unsigned Region) {
          if (P != Index) return;
          if (Region && closedCallableSource(Argument, Parameter)) return;
          auto Part = Region ? classRegionRoots(Argument,
                                   circleClassRecord(Parameter), Region, S)
                             : referenceRoots(Argument, Parameter, S);
          Known &= !Part.empty();
          Result.insert(Part.begin(), Part.end());
        });
    return Known ? Result : Vars{};
#else
    return {};
#endif
  }
#ifdef MODULE_SAFETY_BUILTIN
  bool closedCallableSource(const Expr *Argument, QualType Parameter) const {
    return circleIsCallableValue(Parameter) &&
           circleCallableCaptures(Argument->IgnoreParenImpCasts()->getType()).empty();
  }
#endif
  Vars argumentResultRoots(const Expr *Argument, const FunctionProtoType *Type,
                           unsigned Index, const State &S) {
    if (!Type || Index >= Type->getNumParams()) return {};
    QualType Parameter = Type->getParamType(Index);
#ifdef MODULE_SAFETY_BUILTIN
    auto Bindings = Type->getLifetimeBindings();
    if (!Bindings.empty() && Bindings[0] &&
        circleFunctionHasClassProjection(Type, Index + 1))
      return argumentRegionRoots(Argument, Type, Index, Bindings[0], S);
#endif
    // Without explicit carried-region projections, a receiver's conventional
    // result contract still determines whether the result borrows its storage
    // or copies a payload from it (for example a vector element's view).
    return referenceRoots(Argument,
        Parameter->isReferenceType() ? Parameter : Type->getReturnType(), S);
  }
  // A class value may carry a borrow through a phantom lifetime field. The
  // phantom has no storage of its own, but its saved roots are the region the
  // class's generated results borrow from.
  Vars receiverPhantomRoots(const Expr *E, const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    const VarDecl *V = variable(E);
    if (!V) return {};
    auto I = S.Fields.find(V);
    const FieldLoans *Fields = I == S.Fields.end() ? nullptr : &I->second;
    FieldLoans Temporary;
    if (!Fields && V->getType()->isReferenceType() && V->hasInit()) {
      QualType Pointee = V->getType()->getPointeeType();
      auto *Record = Pointee->getAsCXXRecordDecl();
      if (Record &&
          projectedPayload(V->getInit(), C.getCanonicalTagType(Record), S,
                           Temporary))
        Fields = &Temporary;
    }
    if (!Fields) return {};
    Vars Result;
    bool Found = false;
    for (const auto &[Path, Loan] : *Fields) {
      if (Path.empty() || !Path.back()->isCirclePhantom()) continue;
      Found = true;
      Result.insert(Loan.Roots.begin(), Loan.Roots.end());
    }
    return Found ? Result : Vars{};
#else
    return {};
#endif
  }
  void classFieldValue(const FieldDecl *Field, const Expr *Value,
                       const Expr *Target, const Stmt *At, const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    if (circleIsCallableValue(Field->getType())) {
      if (circleCallableCaptures(Value->IgnoreParenImpCasts()->getType()).empty()) return;
      auto *R = cast<CXXRecordDecl>(Field->getParent())->getCanonicalDecl();
      auto Captures = circleCallableCaptures(Field->getType());
      for (unsigned I = 0; I < Captures.size(); ++I) {
        unsigned Region = mappedFieldRegion(Field, I + 1);
        auto Variance = circle_relation::FunctionRelation(C).callableVariance(Field->getType(), I + 1);
        if (Variance == circle_relation::Variance::Bivariant) continue;
        auto Origins = callableRegionRoots(Value, Captures[I], S);
        auto Existing = Target ? classRegionRoots(Target, R, Region, S) : Vars{};
        bool Valid = Region && !Origins.empty();
        for (auto *Origin : Origins) {
          Vars Seen;
          bool Cov = permanentRoot(Origin, S, Seen), Contra = false;
          for (auto *Destination : Existing) {
            Cov |= originOutlives(Origin, Destination, S);
            Contra |= originOutlives(Destination, Origin, S);
          }
          if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
              Ctor && Ctor->getParent()->getCanonicalDecl() == R) {
            if (auto Source = ClassRegions.find(Origin);
                Source != ClassRegions.end() && Source->second.Record == R) {
              Cov |= circleClassRegionOutlives(R, Source->second.Index, Region);
              Contra |= circleClassRegionOutlives(R, Region, Source->second.Index);
            }
            unsigned Source = functionRootRegion(Origin);
            if (circleRegionIsCapture(Source) && circleCaptureDepth(Source) == 1) {
              Source = circleCaptureSlot(Source);
              Cov |= circleClassRegionOutlives(R, Source, Region);
              Contra |= circleClassRegionOutlives(R, Region, Source);
            }
          }
          Valid &= Variance == circle_relation::Variance::Covariant ? Cov
              : Variance == circle_relation::Variance::Contravariant ? Contra : Cov && Contra;
        }
        if (!Valid) contractError(At, "class callback field does not preserve its captured lifetime region");
      }
      return;
    }
    unsigned Region = fieldClassRegion(Field);
    if (!Region) return;
    // An implicit array copy lowers to `ArrayInitLoopExpr`: the element-wise
    // copy keeps the source array's origins, and a copy or move constructor
    // cannot rebind the field's declared region. Validate explicit
    // initializers instead of treating the synthesized loop as an unknown
    // array initializer.
    if (isa<ArrayInitLoopExpr>(Value))
      if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
          Ctor && Ctor->isCopyOrMoveConstructor())
        return;
    auto *R = cast<CXXRecordDecl>(Field->getParent())->getCanonicalDecl();
    // A field whose type is itself a class value is copied through the nested
    // value's constructor, so the region roots come from that constructor's
    // argument rather than from the construct expression.
    const Expr *Source = Value;
#ifdef MODULE_SAFETY_BUILTIN
    if (circleClassLifetimeBinding(Field->getType()))
      if (const auto *Construct = dyn_cast<CXXConstructExpr>(Value->IgnoreParenImpCasts());
          Construct && Construct->getNumArgs() == 1 &&
          Construct->getConstructor()->isCopyOrMoveConstructor())
        Source = Construct->getArg(0);
#endif
    auto Origins = expressionRoots(Source, S);
    Vars Existing = Target ? classRegionRoots(Target, R, Region, S) : Vars{};
    auto *FunctionType = F->getType()->getAs<FunctionProtoType>();
    bool Valid = !Origins.empty();
    for (auto *Origin : Origins) {
      Vars Seen;
      bool Allowed = permanentRoot(Origin, S, Seen) || Existing.count(Origin);
      for (auto *Destination : Existing)
        Allowed |= originOutlives(Origin, Destination, S);
      // An aggregate initialized outside a constructor still names its
      // regions through the enclosing function's parameters. A borrow slot
      // array has one declared region for the whole field, so every element
      // origin must be a live parameter whose region outlives it.
      const VarDecl *Parameter = Origin;
      if (auto I = ParameterRegions.find(Origin); I != ParameterRegions.end())
        Parameter = I->second;
      if (auto *P = dyn_cast<ParmVarDecl>(Parameter);
          P && llvm::is_contained(F->parameters(), P) && S.Ready.count(P) &&
          !S.Moved.count(P) && !S.Relocated.count(P)) {
        unsigned Bound = circleClassLifetimeIndex(
            R, modulesafety::parameterLifetimeLabel(P));
        if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
            Ctor && Ctor->getParent()->getCanonicalDecl() == R)
          Bound = constructorParameterRegion(P, R);
        if (isa<CXXConstructorDecl>(F) &&
            (!FunctionType || FunctionType->getLifetimeBindings().empty()))
          Allowed |= Bound && circleClassRegionOutlives(R, Bound, Region);
      }
      if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
          Ctor && Ctor->getParent()->getCanonicalDecl() == R)
        if (auto I = ClassRegions.find(Origin); I != ClassRegions.end())
          Allowed |= I->second.Record == R && circleClassRegionOutlives(R, I->second.Index, Region) &&
                     isa<ParmVarDecl>(I->second.Parameter);
      Valid &= Allowed;
    }
    if (!Valid)
      contractError(At, "class field lifetime contract does not preserve its declared region");
#endif
  }
  bool dropBorrowRootLive(const VarDecl *Root, const State &S) const {
    if (!Root || Root == StaticOrigin || Root == LiteralOrigin ||
        Root->hasGlobalStorage())
      return true;
    return S.Ready.count(Root) && !S.Moved.count(Root) &&
           !S.Relocated.count(Root);
  }
  // A destructor without `[[unsafe::drop_only(T)]]` uses the lifetime of the
  // borrows stored in its fields. Dropping it after one of those owners has
  // ended would turn a dangling field into a use of the dead region.
  bool indirectDropUsesBorrows(const CXXDestructorDecl *Dtor,
                              std::set<const CXXRecordDecl *> Seen = {}) {
    if (!Dtor || Dtor->isTrivial()) return false;
    auto *Record = Dtor->getParent()->getDefinition();
    if (!Record || !Seen.insert(Record->getCanonicalDecl()).second) return false;
    bool DropOnly = marked(Dtor, "safecpp.drop.only");
    if (Dtor->isUserProvided() && !DropOnly) return true;
    // Implicit destruction only invokes field/base drops. A wrapper around
    // drop-only containers does not inspect their retained payloads itself.
    for (const auto *Field : Record->fields()) {
      if (auto *R = C.getBaseElementType(Field->getType())->getAsCXXRecordDecl();
          R && indirectDropUsesBorrows(R->getDestructor(), Seen)) return true;
      // A drop-only container still runs its elements' destructors. The
      // promise permits dropping a borrowed handle, not reading a dangling
      // referent from a non-drop-only element destructor.
      auto T = Field->getType();
      if (DropOnly && T->isPointerType() &&
          modulesafety::hasLifetimeBinderParameter(Record)) {
        auto Element = T->getPointeeType();
        if (objectBorrow(Element) || indirectBorrowStorage(Element))
          if (auto *R = Element->getAsCXXRecordDecl();
              R && R->hasDefinition() &&
              indirectDropUsesBorrows(R->getDestructor(), Seen)) return true;
      }
    }
    for (const auto &Base : Record->bases())
      if (auto *R = Base.getType()->getAsCXXRecordDecl();
          R && indirectDropUsesBorrows(R->getDestructor(), Seen)) return true;
    return false;
  }
  void checkDropBorrows(const CXXDestructorDecl *Dtor, const VarDecl *Target,
                        const Stmt *At, State &S) {
    if (!Dtor || !Target) return;
    auto Check = [&](const Vars &Roots) {
      for (auto *Root : Roots)
        if (!dropBorrowRootLive(Root, S)) {
          error(At, "dropping a borrow-carrying object requires drop_only");
          return false;
        }
      return true;
    };
    if (!marked(Dtor, "safecpp.drop.only")) {
      auto I = S.Fields.find(Target);
      if (I != S.Fields.end())
        for (const auto &[Path, Loan] : I->second)
          if (!Check(Loan.Roots)) return;
      if (auto J = S.Loans.find(Target); J != S.Loans.end())
        Check(J->second.Roots);
    }
    if (indirectDropUsesBorrows(Dtor)) {
      auto Places = ownedPlaces(Target);
      // A field drop is represented by a synthetic place, whereas its
      // descendants remain indexed by the original enclosing declaration.
      if (auto I = OriginOwners.find(Target); I != OriginOwners.end())
        if (auto J = FieldOrigins.find(I->second); J != FieldOrigins.end())
          for (const auto &[Path, Origin] : J->second)
            if (Origin == Target) {
              auto Descendants = ownedPlaces(I->second, Path);
              Places.insert(Descendants.begin(), Descendants.end());
              break;
            }
      Check(retainedOrigins(Places, S));
    }
  }
  // Project every leaf borrow of a multi-region call result. A `T+` field may
  // itself carry several regions, so the call-result summary must descend
  // through nested class values instead of assuming one region per top-level
  // field. The visible label at a leaf is obtained by narrowing the result
  // type's projections along the field path. Every parameter region that
  // outlives the leaf contributes to its conservative provenance summary.
  bool projectCallClassFields(const CallExpr *Call,
                              const FunctionProtoType *Proto,
                              const FunctionDecl *Callee, QualType T,
                              const State &S, FieldLoans &Result,
                              FieldPath Prefix = {}) {
#ifdef MODULE_SAFETY_BUILTIN
    if (!Call || !Proto) return false;
    auto Names = modulesafety::classLifetimeBindingNames(
        Proto->getReturnType());
    if (Names.empty()) return false;
    unsigned Offset =
        Callee && isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee) ? 1u
                                                                      : 0u;
    auto Add = [&](auto &&Self, QualType Current,
                   FieldPath Path) -> bool {
      auto *Record = circleClassRecord(Current);
      if (!Record || !Record->hasDefinition()) return false;
      for (const auto *Field : Record->getDefinition()->fields()) {
        if (Field->isCirclePhantom() || !objectBorrow(Field->getType()))
          continue;
        auto Next = Path;
        Next.push_back(Field);
        if (staticLifetimeField(Field)) {
          Vars StaticRoots = expressionRoots(Call, S);
          if (StaticRoots.empty()) StaticRoots.insert(StaticOrigin);
          Result[Next] = {StaticRoots, objectBorrow(Field->getType(), true)};
          continue;
        }
        auto *FieldRecord = circleClassRecord(Field->getType());
        if (!Field->getType()->getAs<BorrowValueType>() && FieldRecord &&
            FieldRecord->hasDefinition() &&
            projectedLifetimeRecord(Field->getType())) {
          if (!Self(Self, Field->getType(), std::move(Next)))
            return false;
          continue;
        }
        if (circleIsCallableValue(Field->getType())) {
          // The field loan keeps every captured region live. Per-capture
          // summaries in Callables retain the precision needed for calls.
          Vars Origins;
          auto Captures = circleCallableCaptures(Field->getType());
          for (unsigned Role = 1; Role <= Captures.size(); ++Role) {
            unsigned Destination = projectedFunctionRegion(Proto, 0, mappedPathRegion(Next, Role));
            Vars Part;
            if (Destination == 0x40000000u) Part.insert(StaticOrigin);
            else if (circleRegionIsCapture(Destination))
              Part = callableRegionRoots(Call->getCallee(), Destination, S);
            else for (unsigned I = 0; I < Proto->getNumParams() && I + Offset < Call->getNumArgs(); ++I) {
              if (!circleFunctionParameterSuppliesRegion(Proto, I, Destination)) continue;
              if (closedCallableSource(Call->getArg(I + Offset), Proto->getParamType(I))) continue;
              auto Source = argumentRegionRoots(Call->getArg(I + Offset), Proto, I, Destination, S);
              if (Source.empty()) return false;
              Part.insert(Source.begin(), Source.end());
            }
            if (Part.empty()) return false;
            Origins.insert(Part.begin(), Part.end());
          }
          if (Origins.empty()) return false;
          Result[Next] = {Origins, false};
          continue;
        }
        llvm::SmallVector<llvm::StringRef, 4> Visible;
        if (!regionLabels(Proto->getReturnType(), Next, Visible))
          return false;
        unsigned Local = fieldClassRegion(Field);
        if (!Local) Local = circleProjectedFieldOrdinal(Field);
        if (!Local || Local > Visible.size() || Visible[Local - 1].empty())
          return false;
        unsigned Destination = projectedFunctionRegion(
            Proto, 0, mappedPathRegion(Next));
        bool Found = false;
        for (unsigned I = 0; I < Proto->getNumParams(); ++I) {
          if (I + Offset >= Call->getNumArgs()) break;
          if (!circleFunctionParameterSuppliesRegion(Proto, I, Destination))
            continue;
          if (closedCallableSource(Call->getArg(I + Offset), Proto->getParamType(I))) continue;
          auto Part = argumentRegionRoots(Call->getArg(I + Offset), Proto, I,
                                           Destination, S);
          if (Part.empty()) return false;
          auto &Loan = Result[Next];
          Loan.Roots.insert(Part.begin(), Part.end());
          Loan.Exclusive = objectBorrow(Field->getType(), true);
          Found = true;
        }
        if (!Found && circleRegionIsCapture(Destination)) {
          auto Origins = callableRegionRoots(Call->getCallee(), Destination, S);
          if (Origins.empty()) return false;
          Result[Next] = {Origins, objectBorrow(Field->getType(), true)};
          Found = true;
        }
        if (!Found && Destination == 0x40000000u) {
          // The producer verifies static leaves even when no parameter
          // supplies them. The result's carrier does not become permanent.
          Result[Next] = {{StaticOrigin}, objectBorrow(Field->getType(), true)};
          Found = true;
        }
        if (!Found) return false;
      }
      return true;
    };
    return Add(Add, T, std::move(Prefix));
#else
    return false;
#endif
  }
  bool projectedPayload(const Expr *E, QualType T, const State &S,
                        FieldLoans &Result, FieldPath Prefix = {}) {
    if (!E) return false;
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *Default = dyn_cast<CXXDefaultArgExpr>(E))
      return projectedPayload(Default->getExpr(), T, S, Result, Prefix);
    if (const auto *Default = dyn_cast<CXXDefaultInitExpr>(E))
      return projectedPayload(Default->getExpr(), T, S, Result, Prefix);
    if (const auto *Cast = dyn_cast<CastExpr>(E);
        Cast && Cast->getCastKind() == CK_NoOp)
      return projectedPayload(Cast->getSubExpr(), T, S, Result, Prefix);
    if (const auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      return projectedPayload(Cleanup->getSubExpr(), T, S, Result, Prefix);
    if (const auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(E))
      return projectedPayload(Temporary->getSubExpr(), T, S, Result, Prefix);
    if (const auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      return projectedPayload(Bound->getSubExpr(), T, S, Result, Prefix);
    if (const auto *Statement = dyn_cast<StmtExpr>(E))
      if (const auto *Body = Statement->getSubStmt())
        if (const auto *Last = dyn_cast_or_null<Expr>(Body->body_back()))
          return projectedPayload(Last, T, S, Result, Prefix);
    if (const auto *U = relocation(E))
      return projectedPayload(U->getSubExpr(), T, S, Result, Prefix);
    if (const auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      FieldLoans Left, Right;
      bool HasLeft = !cannotReturn(Choice->getTrueExpr()) &&
                     projectedPayload(Choice->getTrueExpr(), T, S, Left, Prefix);
      bool HasRight = !cannotReturn(Choice->getFalseExpr()) &&
                      projectedPayload(Choice->getFalseExpr(), T, S, Right, Prefix);
      if (!HasLeft && !HasRight) return false;
      if (!HasLeft) {
        Result = std::move(Right);
        return true;
      }
      if (!HasRight) {
        Result = std::move(Left);
        return true;
      }
      for (const auto &[Path, Loan] : Right) {
        auto I = Left.find(Path);
        if (I == Left.end()) return false;
        mergeLoan(I->second, Loan);
      }
      Result = std::move(Left);
      return true;
    }
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && Construct->getConstructor()->isImplicit() &&
        Construct->getConstructor()->isCopyOrMoveConstructor() && Construct->getNumArgs()==1)
      return projectedPayload(Construct->getArg(0), T, S, Result, Prefix);
    if (const auto *Source = variable(E); Source && S.Fields.count(Source)) {
      auto Path = ownedFieldPath(E);
      for (const auto &[P, L] : S.Fields.at(Source))
        if (prefixPath(Path, P)) {
          auto Dest = Prefix;
          Dest.insert(Dest.end(), P.begin()+Path.size(), P.end());
          Result[Dest] = L;
        }
      return true;
    }
    auto *List = dyn_cast<InitListExpr>(E);
    auto *Record = T->getAsCXXRecordDecl();
#ifdef MODULE_SAFETY_BUILTIN
    if (const auto *Call = dyn_cast<CallExpr>(E); Call && Record) {
      const FunctionProtoType *Proto = callPrototype(Call);
      if (Proto && circleSimpleClassValueRegion(Proto->getReturnType()) &&
          (!Proto->getReturnBorrowSources().empty() || Proto->hasGenerativeReturnLifetime()) &&
          C.hasSameUnqualifiedType(Proto->getReturnType(), T)) {
        auto Origins = expressionRoots(Call, S);
        if (Origins.empty()) return false;
        for (const auto *Field : Record->getDefinition()->fields()) {
          if (!objectBorrow(Field->getType())) continue;
          auto Path = Prefix; Path.push_back(Field);
          Result[Path] = {Origins, objectBorrow(Field->getType(), true)};
        }
        return true;
      }
      // A result carrying several regions projects each field to the argument
      // whose parameter is bound to that field's region, so the fields are
      // tracked separately instead of sharing one region set.
      if (Proto && modulesafety::multiRegionClassValue(Proto->getReturnType()) &&
          !Proto->getReturnBorrowSources().empty() &&
          C.hasSameUnqualifiedType(Proto->getReturnType(), T)) {
        const FunctionDecl *Callee = Call->getDirectCallee();
        return projectCallClassFields(Call, Proto, Callee, T, S, Result,
                                      Prefix);
      }
      if (Proto && Proto->getReturnBorrow() == 0x40000000u &&
          C.hasSameUnqualifiedType(Proto->getReturnType(), T)) {
        Vars StaticRoots;
        if (const FunctionDecl *Callee = callCallee(Call))
          StaticRoots = staticCallRoots(Call, Callee, S);
        if (StaticRoots.empty()) StaticRoots.insert(StaticOrigin);
        // Only the carried leaves are permanent. The nested value's own
        // storage still belongs to the returned object.
        auto Add = [&](auto &&Self, const CXXRecordDecl *Current,
                       FieldPath Path) -> bool {
          if (!Current || !Current->hasDefinition()) return false;
          for (const auto *Field : Current->getDefinition()->fields()) {
            if (Field->isCirclePhantom() || !objectBorrow(Field->getType())) continue;
            auto Next = Path; Next.push_back(Field);
            if (!Field->getType()->getAs<BorrowValueType>() &&
                Field->getType()->isRecordType()) {
              if (!projectedLifetimeRecord(Field->getType()) ||
                  !Self(Self, circleClassRecord(Field->getType()), std::move(Next)))
                return false;
            } else
              Result[Next] = {StaticRoots, objectBorrow(Field->getType(), true)};
          }
          return true;
        };
        return Add(Add, Record, std::move(Prefix));
      }
      if (const FunctionDecl *Callee = Call->getDirectCallee();
          Proto && Callee && C.hasSameUnqualifiedType(Proto->getReturnType(), T)) {
        auto Sources = modulesafety::borrowedParameters(Callee);
        if (Sources.size() == 1) {
          unsigned I = *Sources.begin();
          unsigned Offset =
              isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee)
                  ? 1u : 0u;
          if (I + Offset < Call->getNumArgs()) {
            auto ParamType = Callee->getParamDecl(I)->getType();
            Vars Part;
            // A choice returned from an explicit object method can project a
            // borrow through the receiver's class lifetime parameter. Use the
            // region that parameter named, not the receiver object's own
            // storage.
            if (auto *Method = dyn_cast<CXXMethodDecl>(Callee);
                Method && Method->isExplicitObjectMemberFunction())
              Part = receiverPhantomRoots(Call->getArg(I + Offset), S);
            if (Part.empty())
              Part = referenceRoots(
                  Call->getArg(I + Offset),
                  ParamType->isReferenceType() ? ParamType : T, S);
            const FieldDecl *Only = nullptr;
            for (const auto *Field : Record->getDefinition()->fields())
              if (objectBorrow(Field->getType())) {
                if (Only) {
                  Only = nullptr;
                  break;
                }
                Only = Field;
              }
            if (Only && !Part.empty()) {
              auto Path = Prefix; Path.push_back(Only);
              Result[Path] = {Part, objectBorrow(Only->getType(), true)};
              return true;
            }
          }
        }
      }
    }
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && Record && hasClassLifetimeFields(T)) {
      const FunctionDecl *Definition = nullptr;
      if (!Construct->getConstructor()->hasBody(Definition)) return false;
      auto *Ctor = cast<CXXConstructorDecl>(Definition);
      State Bound;
      for (unsigned I = 0; I < Ctor->getNumParams() && I < Construct->getNumArgs(); ++I) {
        auto *P = Ctor->getParamDecl(I);
        Bound.Ready.insert(P);
        if (!objectBorrow(P->getType())) continue;
        auto Origins = referenceRoots(Construct->getArg(I), P->getType(), S);
        if (Origins.empty()) return false;
        Bound.Loans[P] = {Origins, objectBorrow(P->getType(), true)};
        if (hasClassLifetimeFields(P->getType())) {
          FieldLoans Fields;
          if (!projectedPayload(Construct->getArg(I),
                 C.getCanonicalTagType(circleClassRecord(P->getType())), S, Fields))
            return false;
          Bound.Fields[P] = std::move(Fields);
        }
      }
      for (auto *Init : Ctor->inits()) {
        if (!Init->isMemberInitializer()) return false;
        const auto *Field = Init->getMember();
        if (!objectBorrow(Field->getType())) continue;
        if (Field->getType()->isRecordType()) return false;
        auto Origins = expressionRoots(Init->getInit(), Bound);
        if (Origins.empty()) return false;
        unsigned Region = fieldClassRegion(Field);
        if (Region)
          for (unsigned I = 0; I < Ctor->getNumParams() && I < Construct->getNumArgs(); ++I) {
            auto *P = Ctor->getParamDecl(I);
            const auto *Owner = circleClassRecord(P->getType());
            Vars Part;
            if (Owner && Owner->getCanonicalDecl() == Record->getCanonicalDecl())
              Part = classRegionRoots(Construct->getArg(I), Record, Region, S);
            else if (circleClassRegionOutlives(Record, constructorParameterRegion(P, Record, Ctor), Region))
              Part = expressionRoots(Construct->getArg(I), S);
            else continue;
            if (Part.empty()) return false;
            Origins.insert(Part.begin(), Part.end());
          }
        auto Path = Prefix; Path.push_back(Field);
        Result[Path] = {Origins, objectBorrow(Field->getType(), true)};
      }
      return true;
    }
    if (const auto *Source = variable(E); Source && objectBorrow(T)) {
      auto Loan = S.Loans.find(Source);
      auto *Borrowed = T->getAsCXXRecordDecl();
      if (Loan != S.Loans.end() && Borrowed && Borrowed->hasDefinition()) {
        const FieldDecl *Only = nullptr;
        for (const auto *Field : Borrowed->getDefinition()->fields())
          if (objectBorrow(Field->getType())) {
            if (Only) return false;
            Only = Field;
          }
        if (Only && !Loan->second.Roots.empty()) {
          auto P = Prefix; P.push_back(Only);
          Result[P] = {Loan->second.Roots,
                       objectBorrow(Only->getType(), true)};
          return true;
        }
      }
    }
#endif
    if (isa<CXXConstructExpr>(E) && Record && hasStaticLifetimeFields(T)) {
      // Every constructor write to a static field is validated separately.
      // Such a field carries a permanent region, independently of the local
      // storage of the constructed object; other borrowed fields need their
      // own constructor projection summary.
      Vars Origins;
      for (auto *Arg : cast<CXXConstructExpr>(E)->arguments())
        for (auto *Root : expressionRoots(Arg, S)) Origins.insert(Root);
      if (Origins.empty()) Origins.insert(StaticOrigin);
      for (auto *Field : Record->getDefinition()->fields()) {
        if (!objectBorrow(Field->getType())) continue;
        if (!staticLifetimeField(Field)) return false;
        auto P = Prefix; P.push_back(Field);
        Result[P] = {Origins, objectBorrow(Field->getType(), true)};
      }
      return true;
    }
    if (List && Record && Record->isUnion()) {
      if (List->getNumInits() == 0) return true;
      if (List->getNumInits() != 1) return false;
      const Expr *Init = List->getInit(0)->IgnoreParenImpCasts();
      const FieldDecl *Match = nullptr;
      for (const auto *Field : Record->getDefinition()->fields()) {
        if (!objectBorrow(Field->getType())) continue;
        if (!C.hasSameUnqualifiedType(Init->getType(), Field->getType()))
          continue;
        if (Match) return false;
        Match = Field;
      }
      // The active alternative has no borrowed payload.
      if (!Match) return true;
      auto P = Prefix; P.push_back(Match);
      if (projectedRecord(Match->getType()))
        return projectedPayload(Init, Match->getType(), S, Result, P);
      auto Origins = expressionRoots(Init, S);
      if (Origins.empty())
        if (auto *Rel = relocation(Init))
          if (auto *Binding = variable(Rel->getSubExpr());
              Binding && marked(Binding, "safecpp.native.match.binding") &&
              Binding->hasInit())
            if (auto *FromBinding = relocation(Binding->getInit()))
              if (auto *Owner = variable(FromBinding->getSubExpr()))
                {
                  Origins = roots(Owner, S);
                  Origins.erase(Owner);
                }
      if (Origins.empty()) return false;
      Result[P] = {Origins, objectBorrow(Match->getType(), true)};
      return true;
    }
    if (!List || !Record || !projectedRecord(T)) return false;
    unsigned I = 0;
    for (const auto *Field : Record->getDefinition()->fields()) {
      if (I >= List->getNumInits())
        // A choice stores only the active alternatives. An absent payload
        // field is the `none` alternative, which carries no borrow.
        return marked(Record, "safecpp.native.choice");
      auto *Init = List->getInit(I++);
      if (!objectBorrow(Field->getType())) continue;
      auto P = Prefix; P.push_back(Field);
      auto *FieldRecord = Field->getType()->getAsCXXRecordDecl();
      bool UnionStorage =
          FieldRecord && FieldRecord->hasDefinition() &&
          marked(FieldRecord->getDefinition(), "safecpp.native.choice.storage");
      if (UnionStorage || projectedRecord(Field->getType())) {
        if (!projectedPayload(Init, Field->getType(), S, Result, P)) return false;
      } else {
        auto R = expressionRoots(Init, S);
#ifdef MODULE_SAFETY_BUILTIN
        if (R.empty())
          if (const InitListExpr *Slice = rawSliceConstruction(Init))
            R = rawPointerRoots(Slice->getInit(0), S);
#endif
        if (R.empty()) return false;
        Result[P] = {R, objectBorrow(Field->getType(), true)};
      }
    }
    return true;
  }
  void initializeFields(const VarDecl *V, State &S) {
    auto T = V->getType();
    bool ExplicitReceiver = false;
    bool MatchSubject =
        marked(V, "safecpp.native.match.subject");
#ifdef MODULE_SAFETY_BUILTIN
    auto *Record = circleClassRecord(T);
    if (auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && Method->isExplicitObjectMemberFunction() &&
        Method->getNumParams() && V == Method->getParamDecl(0))
      ExplicitReceiver = true;
#else
    auto *Record = T->getAsCXXRecordDecl();
#endif
    if ((!V->hasLocalStorage() && !ExplicitReceiver) ||
        (T->isReferenceType() && !ExplicitReceiver && !MatchSubject) ||
        (objectBorrow(T) && !projectedRecord(T) && !ExplicitReceiver &&
         !MatchSubject) ||
        !Record || !Record->hasDefinition() || Record->isUnion()) return;
    auto &Fields = FieldOrigins[V];
    auto Add = [&](auto &&Self, const CXXRecordDecl *R, FieldPath Path) -> void {
      for (auto *Field : R->fields()) {
#ifdef MODULE_SAFETY_BUILTIN
        if (Field->isCirclePhantom()) continue;
#endif
        if (Field->isBitField() || Field->hasAttr<NoUniqueAddressAttr>()) continue;
        auto Next = Path; Next.push_back(Field);
        auto &Origin = Fields[Next];
        if (!Origin) {
          Origin = ImplicitParamDecl::Create(C, F, V->getLocation(), nullptr,
              Field->getType(), ImplicitParamKind::Other);
          // Only fields reached through a borrowed receiver belong to the
          // caller's parameter region. Fields of a by-value parameter are
          // local storage; OriginOwners already records their alias owner.
          if (auto *P = dyn_cast<ParmVarDecl>(V);
              P && (T->isReferenceType()
#ifdef MODULE_SAFETY_BUILTIN
                    || T->getAs<BorrowValueType>()
#endif
                    ))
            ParameterRegions[Origin] = P;
        }
        OriginOwners[Origin] = V;
        S.Moved.erase(Origin); S.Relocated.erase(Origin);
        if (S.Ready.count(V)) S.Ready.insert(Origin); else S.Ready.erase(Origin);
        if (auto *Child = Field->getType()->getAsCXXRecordDecl(); Child && Child->hasDefinition() &&
            !Child->isUnion() && (!objectBorrow(Field->getType()) || projectedRecord(Field->getType())))
          Self(Self, Child->getDefinition(), Next);
      }
    };
    Add(Add, Record->getDefinition(), {});
  }
  void endFields(const VarDecl *V, State &S) {
    for (auto *Place : ownedPlaces(V)) S.Ready.erase(Place);
  }
  void restoreFields(const VarDecl *V, State &S) {
    for (auto *Place : ownedPlaces(V)) {
      S.Ready.insert(Place);
      S.Moved.erase(Place);
    }
  }
  Vars parents(const VarDecl *V, const State &S) {
    if (auto It = S.Loans.find(V); It != S.Loans.end()) {
      auto Result = It->second.Parents;
      Result.insert(V);
      return Result;
    }
    return {};
  }
  // Parent loans grant permission to reborrow; merely sharing a root is not
  // permission. Preserve that distinction when several values are stored in
  // an aggregate. Every overlapping constituent must authorize a candidate
  // parent, and alternatives must agree on it.
  Vars valueParents(const Expr *E, const State &S) {
    if (!E) return {};
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      return valueParents(Cleanup->getSubExpr(), S);
    if (const auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(E))
      return valueParents(Temporary->getSubExpr(), S);
    if (const auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      return valueParents(Bound->getSubExpr(), S);
    if (const auto *Default = dyn_cast<CXXDefaultInitExpr>(E))
      return valueParents(Default->getExpr(), S);
    if (const auto *Default = dyn_cast<CXXDefaultArgExpr>(E))
      return valueParents(Default->getExpr(), S);
    if (const auto *Cast = dyn_cast<CastExpr>(E);
        Cast && Cast->getCastKind() == CK_NoOp)
      return valueParents(Cast->getSubExpr(), S);
    if (const auto *Move = relocation(E))
      return valueParents(Move->getSubExpr(), S);
    if (const auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && Construct->getConstructor()->isImplicit() &&
        Construct->getConstructor()->isCopyOrMoveConstructor() &&
        Construct->getNumArgs() == 1)
      return valueParents(Construct->getArg(0), S);
    if (const auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      if (cannotReturn(Choice->getTrueExpr()))
        return valueParents(Choice->getFalseExpr(), S);
      if (cannotReturn(Choice->getFalseExpr()))
        return valueParents(Choice->getTrueExpr(), S);
      auto Left = valueParents(Choice->getTrueExpr(), S);
      auto Right = valueParents(Choice->getFalseExpr(), S);
      Vars Common;
      std::set_intersection(Left.begin(), Left.end(), Right.begin(), Right.end(),
                            std::inserter(Common, Common.end()), Left.key_comp());
      return Common;
    }
    // A lowered array-to-slice pair is a reborrow of its one array source,
    // rather than an aggregate of unrelated pointer and length fields.
    if (const auto *Receiver = borrowedReceiver(E)) {
      auto Result = parents(Receiver, S);
      Result.insert(Receiver);
      return Result;
    }
    if (const auto *List = dyn_cast<InitListExpr>(E)) {
      if (List->isSyntacticForm() && List->getSemanticForm())
        List = List->getSemanticForm();
      if (!List->getType()->isArrayType() &&
          !List->getType()->getAsCXXRecordDecl()) return {};
      std::vector<std::pair<Vars, Vars>> Parts;
      Vars Candidates;
      for (const auto *Init : List->inits()) {
        auto T = Init->getType();
        if (!T->isReferenceType() && !objectBorrow(T) &&
            !indirectBorrowStorage(T)) continue;
        auto Roots = expressionRoots(Init, S);
        if (Roots.empty()) return {};
        auto Ancestors = valueParents(Init, S);
        Candidates.insert(Ancestors.begin(), Ancestors.end());
        Parts.emplace_back(std::move(Roots), std::move(Ancestors));
      }
      for (auto I = Candidates.begin(); I != Candidates.end();) {
        auto Loan = S.Loans.find(*I);
        bool Authorized = Loan != S.Loans.end();
        if (Authorized)
          for (const auto &[Roots, Ancestors] : Parts) {
            if (Ancestors.count(*I)) continue;
            for (auto *Root : Roots)
              if (Loan->second.Roots.count(Root)) Authorized = false;
          }
        if (!Authorized) I = Candidates.erase(I);
        else ++I;
      }
      return Candidates;
    }
    return {};
  }
  /// A match binding protects its payload only while the binding is live.
  /// Liveness is flow-sensitive: once the enclosing CFG statement no longer
  /// uses the binding, its last use has happened.
  bool matchBindingDeadAt(const VarDecl *V, const Stmt *At) {
    if (!V || (!marked(V, "safecpp.native.match.binding") &&
               !marked(V, "safecpp.native.match.subject")))
      return false;
    const Stmt *Cur = At;
    for (unsigned Depth = 0; Cur && Depth < 64; ++Depth) {
      if (auto It = LiveAfter.find(Cur); It != LiveAfter.end()) {
        return !It->second.count(V);
      }
      auto Parents = parentNodes(*Cur);
      if (Parents.size() != 1)
        break;
      Cur = Parents[0].get<Stmt>();
    }
    return false;
  }
  bool isDestructorObjectAccess(const Stmt *At, const VarDecl *V,
                                const FieldPath &Field) const {
    if (!At || Field.empty())
      return false;
    auto *Call = dyn_cast<CXXMemberCallExpr>(At);
    if (!Call)
      return false;
    auto *Method = dyn_cast_or_null<CXXMethodDecl>(Call->getDirectCallee());
    if (!Method || !isa<CXXDestructorDecl>(Method) ||
        variable(Call->getImplicitObjectArgument()) != V)
      return false;
    return ownedFieldPath(Call->getImplicitObjectArgument()) == Field;
  }
  void access(const VarDecl *V, bool Write, const Stmt *At, State &S,
              bool Reinitializes = false, const FieldPath &Field = {},
              const Vars *WriteRoots = nullptr, const Vars *ReadRoots = nullptr) {
    if (!V)
      return;
    // The generated `match` lowering owns its subject and its pattern bindings
    // and scopes their lifetimes to the arm: it relocates the matched
    // alternative out of the subject itself, and the operand the user wrote is
    // what the analysis tracks.
    for (const auto *A : V->specific_attrs<AnnotateAttr>())
      if (A->isImplicit() &&
          A->getAnnotation().starts_with("safecpp.native.match"))
        return;
    if (isDestructorObjectAccess(At, V, Field)) {
      auto I = S.RelocatedFields.find(V);
      if (I != S.RelocatedFields.end() && I->second.count(Field))
        return;
    }
    if (S.Relocated.count(V))
      error(At, "use of a relocated object whose lifetime has ended");
    if (auto I = S.RelocatedFields.find(V); I != S.RelocatedFields.end())
      for (const auto &Missing : I->second)
        if (prefixPath(Field, Missing) || prefixPath(Missing, Field))
          error(At, "use of a partially relocated owner or an absent field");
    if (V->hasLocalStorage() && (!Write || V->getType()->isReferenceType()) && !S.Ready.count(V))
      error(At, "read of a variable not initialized on every control-flow path");
    if ((!Write || !Reinitializes) && S.Moved.count(V))
      error(At, "use of a moved value");
    auto R = roots(V, S);
    if (!Field.empty() && fieldOrigin(V, Field)) R = ownedPlaces(V, Field);
    if (!Field.empty() && S.Fields.count(V)) {
      auto Payload = fieldRoots(V, Field, S);
      if (!Payload.empty()) R = std::move(Payload);
    }
    // Reading a borrow field reads its handle slot as well as the data it
    // names. A live exclusive borrow of the holder protects that slot even
    // when the carried data itself is shared. Pointee writes use a separate
    // access; they must not be mistaken for writes to the handle slot.
    if (!Write && !Field.empty() && fieldOrigin(V, Field)) {
      auto Storage = ownedPlaces(V, Field);
      R.insert(Storage.begin(), Storage.end());
    }
    if (Write && !V->getType()->isReferenceType() && objectBorrow(V->getType()))
      R.insert(V);
    if (WriteRoots) R.insert(WriteRoots->begin(), WriteRoots->end());
    if (ReadRoots) R.insert(ReadRoots->begin(), ReadRoots->end());
    auto Retained = retainedOrigins(R, S);
    R.insert(Retained.begin(), Retained.end());
    auto Ancestors = parents(V, S);
    // A parameter's projected region is reached through that parameter's own
    // loan. Accessing the region is an access through the receiver, not a
    // second borrower conflicting with it.
    if (auto I = ParameterRegions.find(V); I != ParameterRegions.end())
      Ancestors.insert(I->second);
    if (auto I = ClassRegions.find(V); I != ClassRegions.end())
      Ancestors.insert(I->second.Parameter);
    for (auto *Root : R) {
      bool RecoversOwnedPlace = Reinitializes && ownedPlaces(V).count(Root);
      if (Root != V && S.RelocatedFields.count(Root))
        error(At, "borrow refers to a partially relocated owner");
      if (Root != V && !RecoversOwnedPlace && S.Moved.count(Root))
        error(At, "borrow refers to a moved value");
      if (Root != V && !RecoversOwnedPlace && Root->hasLocalStorage() &&
          !S.Ready.count(Root))
        error(At, "borrow outlives its owner");
    }
    // Mutating the handle's allocation does not mutate shared referents
    // retained inside it. Their liveness was checked above independently.
    for (auto *Root : Retained) R.erase(Root);
    // Indirect storage retains permissions as well as provenance. Resolve
    // projected fields back to their owner for NLL and receiver authorization.
    const Vars *Live = nullptr;
    const Stmt *Cur = At;
    for (unsigned Depth = 0; Cur && Depth < 64; ++Depth) {
      if (auto I = LiveAfter.find(Cur); I != LiveAfter.end()) {
        Live = &I->second;
        break;
      }
      auto P = parentNodes(*Cur);
      if (P.size() != 1) break;
      Cur = P[0].get<Stmt>();
    }
    for (const auto &[Storage, Origins] : S.RetainedBorrows) {
      auto *Owner = Storage;
      Vars Seen;
      while (Seen.insert(Owner).second) {
        auto I = OriginOwners.find(Owner);
        if (I == OriginOwners.end()) break;
        Owner = I->second;
      }
      if (Owner == V || Storage == V || Ancestors.count(Owner) ||
          Ancestors.count(Storage) || S.Moved.count(Owner) ||
          !S.Ready.count(Owner)) continue;
      bool IsLive = !Live || Live->count(Owner);
      if (!IsLive)
        for (auto *Alias : *Live)
          if (auto I = S.Loans.find(Alias); I != S.Loans.end() &&
              (I->second.Roots.count(Owner) || I->second.Parents.count(Owner)))
            IsLive = true;
      if (!IsLive || (!Write && !indirectBorrowStorage(Storage->getType(), {}, {}, true)))
        continue;
      for (auto *Root : R)
        if (Root != LiteralOrigin && Origins.count(Root) &&
            ((Write && (!WriteRoots || WriteRoots->count(Root))) ||
             indirectBorrowStorage(Storage->getType(), {}, {}, true))) {
          error(At, Write ? "mutation conflicts with a live borrow"
                          : "access conflicts with a live exclusive borrow");
          break;
        }
    }
    Vars DeadBindings;
    for (auto &Entry : S.Loans) {
      if (matchBindingDeadAt(Entry.first, At))
        DeadBindings.insert(Entry.first);
    }
    if (hasBorrowConflict(V, Write, R, Ancestors, S, DeadBindings, WriteRoots))
      error(At, Write ? "mutation conflicts with a live borrow"
                      : "access conflicts with a live exclusive borrow");
  }
  Vars receiverRoots(const Expr *E, const State &S) {
    auto R = expressionRoots(E, S);
    if (isa<CXXThisExpr>(E->IgnoreParenImpCasts()))
      return R;
    if (auto *Owner = variable(E)) {
      if (!Owner->getType()->isReferenceType())
        R.insert(Owner);
      return R;
    }
    // A checked reference-returning call already carries its storage owner.
    // Do not accept materialized prvalues here: their storage can expire.
    if (isa<CallExpr>(E->IgnoreParenImpCasts()) && E->isGLValue())
      return R;
    return {};
  }
  Vars referenceRoots(const Expr *E, QualType T, const State &S) {
    auto R = expressionRoots(E, S);
    if (!T->isReferenceType()) {
      if (E && indirectBorrowStorage(E->getType()))
        if (auto *Move = relocation(E))
          for (auto *Place : ownedPlaces(variable(Move->getSubExpr())))
            R.erase(Place);
      if (objectBorrow(T) && projectedLifetimeRecord(T)) {
        FieldLoans Payload;
        if (projectedPayload(E, T, S, Payload)) {
          Vars Result;
          for (const auto &[Path, Loan] : Payload)
            Result.insert(Loan.Roots.begin(), Loan.Roots.end());
          if (!Result.empty()) return Result;
        }
      }
      return R;
    }
    if (!objectBorrow(T->getPointeeType()))
      return R;
    // Reference validity includes the storage of the borrowed object itself,
    // not only the lifetimes stored in its fields. Do not strip materialized
    // temporaries before checking whether their lifetime was extended.
    const Expr *Source = E;
    for (;;) {
      if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Source))
        Source = Cleanup->getSubExpr();
      else if (auto *Paren = dyn_cast<ParenExpr>(Source))
        Source = Paren->getSubExpr();
      else if (auto *Cast = dyn_cast<ImplicitCastExpr>(Source))
        Source = Cast->getSubExpr();
      else
        break;
    }
    if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Source)) {
      auto *Extending = dyn_cast_or_null<VarDecl>(Temporary->getExtendingDecl());
      if (!Extending || R.empty()) return {};
      R.insert(Extending);
      return R;
    }
    if (auto *Unary = dyn_cast<UnaryOperator>(Source);
        Unary && (nativeBorrow(Unary) || Unary->getOpcode() == UO_Deref ||
                  Unary->getOpcode() == UO_Extension))
      return referenceRoots(Unary->getSubExpr(), T, S);
    if (auto *Cast = dyn_cast<CastExpr>(Source); Cast && Cast->isGLValue())
      return referenceRoots(Cast->getSubExpr(), T, S);
    auto Join = [&](const Expr *Left, const Expr *Right) {
      auto L = referenceRoots(Left, T, S);
      auto R = referenceRoots(Right, T, S);
      if (L.empty() || R.empty()) return Vars{};
      L.insert(R.begin(), R.end());
      return L;
    };
    if (auto *Choice = dyn_cast<ConditionalOperator>(Source))
      return Join(Choice->getTrueExpr(), Choice->getFalseExpr());
    if (auto *Choice = dyn_cast<BinaryConditionalOperator>(Source))
      return Join(Choice->getCommon(), Choice->getFalseExpr());
    if (auto *Binary = dyn_cast<BinaryOperator>(Source)) {
      if (Binary->getOpcode() == BO_Comma)
        return referenceRoots(Binary->getRHS(), T, S);
      if (Binary->isAssignmentOp())
        return referenceRoots(Binary->getLHS(), T, S);
    }
    if (auto *Member = dyn_cast<MemberExpr>(Source)) {
      if (Member->getMemberDecl()->getType()->isReferenceType()) return R;
      auto Base = referenceRoots(Member->getBase(),
          C.getLValueReferenceType(Member->getBase()->getType()), S);
      if (Base.empty()) return {};
      R.insert(Base.begin(), Base.end());
      return R;
    }
    if (auto *Owner = variable(Source)) {
      if (!Owner->getType()->isReferenceType()) R.insert(Owner);
      return R;
    }
    // An element of an audited sequence borrows the region the expression
    // roots already name: the sequence's storage is that region, not a
    // separate object whose lifetime would have to be tracked here.
    if (const Expr *StorageObject = nullptr;
        sequenceStorageBase(Source, StorageObject) && !R.empty())
      return R;
    if (isa<CXXThisExpr>(Source) && ThisOrigin) return R;
    if (auto *Call = dyn_cast<CallExpr>(Source); Call && Call->isGLValue()) return R;
    return {};
  }
  // The audited element-storage field an element access came from, and the
  // object whose sequence owns it. Nil for every other pointer expression, so
  // the storage contract never widens unrelated pointer provenance.
  const FieldDecl *sequenceStorageBase(const Expr *E, const Expr *&Object) const {
    if (!E) return nullptr;
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Index = dyn_cast<ArraySubscriptExpr>(E))
      return sequenceStorageBase(Index->getBase(), Object);
    if (auto *Add = dyn_cast<BinaryOperator>(E)) {
      switch (Add->getOpcode()) {
      case BO_Add:
        if (const FieldDecl *Field = sequenceStorageBase(Add->getLHS(), Object))
          return Field;
        return sequenceStorageBase(Add->getRHS(), Object);
      case BO_Sub:
        return sequenceStorageBase(Add->getLHS(), Object);
      default:
        return nullptr;
      }
    }
    if (auto *Member = dyn_cast<MemberExpr>(E)) {
      auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
      if (!Field || !modulesafety::sequenceStorageField(Field)) return nullptr;
      // `this->storage_` and `object.storage_` name a known sequence object.
      // A member reached through an arbitrary pointer is not a known region.
      const Expr *Base = Member->getBase()->IgnoreParenImpCasts();
      if (!isa<CXXThisExpr>(Base) && Member->getBase()->getType()->isPointerType())
        return nullptr;
      Object = Member->getBase();
      return Field;
    }
    return nullptr;
  }
  // Roots of an element read through a sequence's audited storage: the region
  // the sequence carries. For a receiver that is the receiver itself, which is
  // what its `borrow.this` result contract promises; for another known object
  // it is that object's declared region.
  Vars sequenceElementRoots(const Expr *E, const State &S) {
    const Expr *Object = nullptr;
    if (!sequenceStorageBase(E, Object) || !Object) return {};
    if (isa<CXXThisExpr>(Object->IgnoreParenImpCasts())) {
      if (!ThisOrigin) return {};
      return {ThisOrigin};
    }
    if (const VarDecl *V = variable(Object)) return roots(V, S);
    return {};
  }
  bool copiedIndirectElementRoots(const Expr *E, QualType Element,
                                  const State &S, Vars &Result) {
#ifdef MODULE_SAFETY_BUILTIN
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Deref = dyn_cast<UnaryOperator>(E);
        Deref && Deref->getOpcode() == UO_Deref)
      E = Deref->getSubExpr()->IgnoreParenImpCasts();
    auto *Call = dyn_cast<CallExpr>(E);
    if (!Call) return false;
    auto *Returned = Call->getType()->getAs<BorrowValueType>();
    auto *Method = dyn_cast_or_null<CXXMethodDecl>(Call->getDirectCallee());
    if (!Returned || !Method ||
        !C.hasSameUnqualifiedType(Returned->getPointeeType(), Element))
      return false;
    const Expr *Receiver = nullptr;
    if (Method->isExplicitObjectMemberFunction() && Call->getNumArgs())
      Receiver = Call->getArg(0);
    else if (auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
      Receiver = Member->getImplicitObjectArgument();
    if (!Receiver || !indirectBorrowStorage(Receiver->getType(), Element))
      return false;
    bool Found = false;
    for (auto *Owner : expressionRoots(Receiver, S)) {
      if (!indirectBorrowStorage(Owner->getType(), Element)) continue;
      auto Origins = retainedOrigins({Owner}, S);
      if (Origins.empty()) return false;
      Found = true;
      Result.insert(Origins.begin(), Origins.end());
    }
    return Found && !Result.empty();
#else
    return false;
#endif
  }
#ifdef MODULE_SAFETY_BUILTIN
  // The slice place a `~length` or `~as_pointer` projection reads, or null
  // when the expression is not that projection of a known place. A borrow
  // names its referent directly, so the dereference of a slice borrow and the
  // borrow itself both lead to the same place.
  const VarDecl *sliceProjectionPlace(const Expr *E, llvm::StringRef Field) const {
    if (!E) return nullptr;
    E = evaluationSource(E->IgnoreParens());
    while (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      E = Cleanup->getSubExpr()->IgnoreParens();
    if (auto *Cast = dyn_cast<CastExpr>(E))
      return sliceProjectionPlace(Cast->getSubExpr(), Field);
    if (auto *U = dyn_cast<UnaryOperator>(E);
        U && (U->getOpcode() == UO_Deref || nativeBorrow(U)))
      return sliceProjectionPlace(U->getSubExpr(), Field);
    auto *Member = dyn_cast<MemberExpr>(E);
    if (!Member) return nullptr;
    auto *Accessed = dyn_cast<FieldDecl>(Member->getMemberDecl());
    if (!Accessed || Accessed->getName() != Field) return nullptr;
    const Expr *Base = Member->getBase()->IgnoreParenImpCasts();
    for (;;) {
      auto *Unary = dyn_cast<UnaryOperator>(Base);
      if (!Unary || (Unary->getOpcode() != UO_Deref && !nativeBorrow(Unary)))
        break;
      Base = Unary->getSubExpr()->IgnoreParenImpCasts();
    }
    if (isa<CXXThisExpr>(Base)) return ThisOrigin;
    return variable(Base);
  }
  // Whether a slice rebuilt from this data pointer reaches exactly as far as
  // its source. The copied length counts source elements, so the byte extent
  // is preserved only while the element sizes agree.
  bool sameSliceElementSize(const Expr *Pointer, const VarDecl *Source) const {
    if (!Pointer || !Source || !Pointer->getType()->isPointerType()) return false;
    QualType SourceElement = C.circleSliceElement(Source->getType());
    QualType TargetElement = Pointer->getType()->getPointeeType();
    if (SourceElement.isNull() || TargetElement.isNull()) return false;
    return C.getTypeSizeInChars(SourceElement.getUnqualifiedType()) ==
           C.getTypeSizeInChars(TargetElement.getUnqualifiedType());
  }
  // Whether a returned expression forms a slice borrow whose extent this
  // subset cannot place inside a known allocation. The pointer side of such a
  // construction may already have a modelled region; the extent is the part
  // that is still an unexpressed precondition, so it is named separately
  // instead of being reported as missing pointer provenance.
  // A result carrying several class regions has to borrow each of its fields
  // from the parameter bound to that field's region. The result type names one
  // region per field in the record's own order.
  //
  // The label of a leaf's region is read down the projected path: the result
  // type names the regions the caller binds, and a nested field's type names
  // the enclosing record's regions in the enclosing record's own scope, so
  // each level is resolved through the level above it.
  bool regionLabels(QualType Result, const FieldPath &Path,
                    llvm::SmallVectorImpl<llvm::StringRef> &Leaf) const {
    Leaf.clear();
    auto ResultNames = modulesafety::classLifetimeBindingNames(Result);
    Leaf.append(ResultNames.begin(), ResultNames.end());
    for (unsigned I = 0; I + 1 < Path.size(); ++I) {
      const FieldDecl *Step = Path[I];
      unsigned Count = circleTypeLifetimeCount(Step->getType());
      if (!Count) return false;
      llvm::SmallVector<llvm::StringRef, 4> Next;
      for (unsigned Region = 1; Region <= Count; ++Region) {
        unsigned Outer = circleMappedFieldRegion(Step, Region);
        if (Outer == 0x40000000u) Next.push_back("static");
        else {
          if (!Outer || Outer > Leaf.size()) return false;
          Next.push_back(Leaf[Outer - 1]);
        }
      }
      Leaf.clear();
      Leaf.append(Next.begin(), Next.end());
    }
    return true;
  }
  void classResultFields(const Expr *Value, QualType Result, const Stmt *At,
                         const State &S) {
    auto Names = modulesafety::classLifetimeBindingNames(Result);
    const auto *Record = circleClassRecord(Result);
    if (!Record || !Record->hasDefinition() || Names.empty()) {
      contractError(At, "class-value result lifetime contract is not modeled");
      return;
    }
    FieldLoans Payload;
    if (!projectedPayload(Value, Result, S, Payload)) {
      contractError(At, "class-value result provenance cannot be established");
      return;
    }
    for (const auto &[Path, Loan] : Payload) {
      if (Path.empty()) continue;
      llvm::SmallVector<llvm::StringRef, 4> Visible;
      if (!regionLabels(Result, Path, Visible)) {
        contractError(At, "class-value result field projection is not modeled");
        continue;
      }
      const FieldDecl *Field = Path.back();
#ifdef MODULE_SAFETY_BUILTIN
      if (circleIsCallableValue(Field->getType())) {
        auto Captures = circleCallableCaptures(Field->getType());
        auto *Type = F->getType()->getAs<FunctionProtoType>();
        for (unsigned Role = 1; Role <= Captures.size(); ++Role) {
          auto Variance = circle_relation::FunctionRelation(C).callableVariance(Field->getType(), Role);
          if (Variance == circle_relation::Variance::Bivariant) continue;
          unsigned Region = mappedPathRegion(Path, Role);
          unsigned Destination = projectedFunctionRegion(Type, 0, Region);
          auto Origins = callableFieldRegionRoots(Value, Path, Role, S);
          bool Valid = Destination && !Origins.empty();
          for (auto *Origin : Origins) {
            Vars Seen;
            if (permanentRoot(Origin, S, Seen)) continue;
            unsigned Source = functionRootRegion(Origin);
            bool Cov = functionRegionOutlives(Type, Source, Destination);
            bool Contra = functionRegionOutlives(Type, Destination, Source);
            Valid &= Variance == circle_relation::Variance::Covariant ? Cov
                : Variance == circle_relation::Variance::Contravariant ? Contra : Cov && Contra;
          }
          if (!Valid) contractError(At, "class callback result does not preserve its captured lifetime region");
        }
        continue;
      }
#endif
#ifndef MODULE_SAFETY_BUILTIN
      unsigned Region = fieldClassRegion(Field);
      if (!Region) Region = circleProjectedFieldRegion(Result, Field);
      llvm::StringRef Bound =
          Region && Region <= Visible.size() ? Visible[Region - 1] : llvm::StringRef();
#endif
      bool Static = staticLifetimeField(Field);
      for (auto *Origin : Loan.Roots) {
        Vars Seen;
        // A permanent origin outlives every region the result names.
        if (permanentRoot(Origin, S, Seen)) continue;
        if (Static) {
          contractError(At, "class-value static result field requires a permanent borrow origin");
          continue;
        }
        bool Allowed = false;
#ifdef MODULE_SAFETY_BUILTIN
        // Result projections and parameter origins share the function's
        // canonical region graph; spelling equality misses outlives edges.
        auto *Type = F->getType()->getAs<FunctionProtoType>();
        unsigned Destination = projectedFunctionRegion(Type, 0, mappedPathRegion(Path));
        Allowed = functionRegionOutlives(Type, functionRootRegion(Origin), Destination);
        // Moving the value transfers its field loans, not their backing
        // regions. The relocation access checks the handle before retiring it.
        if (auto I = ParameterRegions.find(Origin);
            I != ParameterRegions.end() && !ClassRegions.count(Origin)) {
          const auto *P = I->second;
          Allowed &= S.Ready.count(P) && !S.Moved.count(P) && !S.Relocated.count(P);
        }
#else
        if (auto I = ParameterRegions.find(Origin); I != ParameterRegions.end()) {
          const ParmVarDecl *P = I->second;
          Allowed = !Bound.empty() &&
                    modulesafety::parameterLifetimeLabel(P) == Bound &&
                    S.Ready.count(P) && !S.Moved.count(P) && !S.Relocated.count(P);
        }
#endif
        if (!Allowed)
          contractError(At, "class-value result field does not borrow from the parameter "
                            "bound to its region");
      }
    }
  }
  bool unprovenSliceExtent(const Expr *E) const {
    auto *Init = rawSliceConstruction(E);
    if (!Init) return false;
    Expr::EvalResult Count;
    return !Init->getInit(1)->EvaluateAsInt(Count, C) || Count.HasSideEffects ||
           Count.Val.getInt().isNegative() || Count.Val.getInt().getActiveBits() > 64;
  }
  // The slice construction a returned expression forms, if any:
  // `*__slice_pointer(p, n)` behind the borrow, dereference and cast wrappers
  // a return adds. A slice is a generated record of a data pointer and a
  // count, so the construction is an initializer list over those two fields.
  const InitListExpr *rawSliceConstruction(const Expr *E) const {
    for (unsigned Step = 0; E && Step < 16; ++Step) {
      if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
        E = Cleanup->getSubExpr();
      else if (auto *Cast = dyn_cast<CastExpr>(E))
        E = Cast->getSubExpr();
      else if (auto *Borrow = dyn_cast<UnaryOperator>(E); Borrow && nativeBorrow(Borrow))
        E = Borrow->getSubExpr();
      else
        break;
      E = evaluationSource(E->IgnoreParens());
    }
    auto *Init = dyn_cast_or_null<InitListExpr>(E);
    if (!Init || Init->getNumInits() != 2 ||
        !C.circleSliceField(Init->getType(), false))
      return nullptr;
    return Init;
  }
  // The parameter an operand names, through the casts a conversion adds.
  const ParmVarDecl *parameterOf(const Expr *E) const {
    if (!E) return nullptr;
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cast = dyn_cast<CastExpr>(E)) E = Cast->getSubExpr()->IgnoreParenImpCasts();
    return dyn_cast_or_null<ParmVarDecl>(variable(E));
  }
  // The single return a body's raw slice construction is, or null. More than
  // one return means the extent cannot be read off a call the same way.
  const InitListExpr *returnedRawSlice(const Stmt *S, unsigned &Returns) const {
    if (!S) return nullptr;
    if (const auto *Return = dyn_cast<ReturnStmt>(S)) {
      ++Returns;
      const InitListExpr *Slice = rawSliceConstruction(Return->getRetValue());
      return Returns == 1 ? Slice : nullptr;
    }
    for (const Stmt *Child : S->children())
      if (const InitListExpr *Slice = returnedRawSlice(Child, Returns))
        return Slice;
    return nullptr;
  }
  // The raw slice construction a declaration's single return is, or null.
  const InitListExpr *returnedRawSliceOf(const FunctionDecl *Decl) const {
    if (!Decl || !Decl->doesThisDeclarationHaveABody() || !Decl->getBody())
      return nullptr;
    unsigned Returns = 0;
    const InitListExpr *Slice = returnedRawSlice(Decl->getBody(), Returns);
    return Returns == 1 && Slice && Slice->getNumInits() == 2 ? Slice : nullptr;
  }
  // The parameters a declaration's raw slice construction takes its data
  // pointer and its count from. A caller then has to place that extent, which
  // is what the two indices let a call site check.
  bool rawSliceExtentParameters(const FunctionDecl *Decl, unsigned &Pointer,
                                unsigned &Count) const {
    Pointer = Count = 0;
    const InitListExpr *Slice = returnedRawSliceOf(Decl);
    if (!Slice) return false;
    const ParmVarDecl *Data = parameterOf(Slice->getInit(0));
    const ParmVarDecl *Length = parameterOf(Slice->getInit(1));
    if (!Data || !Length || Data == Length) return false;
    if (!Data->getType()->isPointerType() ||
        Data->getType()->getPointeeType()->isFunctionType())
      return false;
    if (!Length->getType()->isIntegralOrEnumerationType()) return false;
    bool FoundPointer = false, FoundCount = false;
    for (unsigned I = 0; I < Decl->getNumParams(); ++I) {
      if (Decl->getParamDecl(I) == Data) { Pointer = I; FoundPointer = true; }
      if (Decl->getParamDecl(I) == Length) { Count = I; FoundCount = true; }
    }
    return FoundPointer && FoundCount;
  }
  // The constant extent carried by a raw-parts slice construction whose
  // pointer names a known constant array. This is the static half of the
  // extent model; slices over unknown storage keep requiring a pair of
  // projections from one source slice.
  bool rawSliceExtentFromParts(const Expr *Pointer, const Expr *Count,
                               uint64_t &Extent) const {
    if (!Pointer || !Count || !Pointer->getType()->isPointerType())
      return false;
    QualType Element = Pointer->getType()->getPointeeType();
    const Expr *Array = Pointer->IgnoreParenImpCasts();
    while (auto *Cast = dyn_cast<CastExpr>(Array)) {
      if (Cast->getCastKind() != CK_NoOp && Cast->getCastKind() != CK_BitCast &&
          Cast->getCastKind() != CK_ArrayToPointerDecay)
        return false;
      Array = Cast->getSubExpr()->IgnoreParenImpCasts();
    }
    auto *Allocation = C.getAsConstantArrayType(Array->getType());
    Expr::EvalResult Size;
    if (!Allocation || Element.isNull() ||
        C.getTypeSizeInChars(Element.getUnqualifiedType()) !=
            C.getTypeSizeInChars(Allocation->getElementType().getUnqualifiedType()) ||
        !Count->EvaluateAsInt(Size, C) || Size.HasSideEffects ||
        Size.Val.getInt().isNegative() || Size.Val.getInt().getActiveBits() > 64)
      return false;
    Extent = Size.Val.getInt().getZExtValue();
    return Extent <= Allocation->getSize().getZExtValue();
  }
  // A local slice initialized from raw parts can retain the constant extent
  // of the array it was built from. Resolve both direct initializer lists and
  // one visible raw-parts call, which is the shape used by the checked
  // standard-library adapters.
  bool sliceKnownExtent(const VarDecl *V, uint64_t &Extent) const {
    if (!V || !V->hasInit()) return false;
    const Expr *Init = V->getInit()->IgnoreParenImpCasts();
    if (const InitListExpr *Slice = rawSliceConstruction(Init))
      return rawSliceExtentFromParts(Slice->getInit(0), Slice->getInit(1),
                                     Extent);
    const auto *Call = dyn_cast<CallExpr>(Init);
    if (!Call) return false;
    const FunctionDecl *Callee = Call->getDirectCallee();
    const InitListExpr *Returned = returnedRawSliceOf(Callee);
    unsigned Pointer = 0, Count = 0;
    if (!Returned || !rawSliceExtentParameters(Callee, Pointer, Count) ||
        Pointer >= Call->getNumArgs() || Count >= Call->getNumArgs())
      return false;
    return rawSliceExtentFromParts(Call->getArg(Pointer), Call->getArg(Count),
                                   Extent);
  }
  // Whether a call's arguments place the extent of a raw slice: the data
  // pointer and the length of one existing slice, or a counted suffix within
  // a known array of the same element size.
  bool sameSliceExpression(const Expr *A, const Expr *B) const {
    return A && B &&
           (Expr::isSameComparisonOperand(A, B) ||
            (variable(A) && variable(A) == variable(B)));
  }
  bool hasSliceBound(const Expr *Count, const VarDecl *Source,
                     const Expr *Start, const State &S) const {
    for (const auto &Fact : S.SliceBounds)
      if (Fact.Source == Source && sameSliceExpression(Fact.Count, Count) &&
          sameSliceExpression(Fact.Start, Start))
        return true;
    return false;
  }
  void applySliceBoundEdge(const CFGBlock *Pred, const CFGBlock *Succ,
                           State &S) const {
    const auto *If = dyn_cast_or_null<IfStmt>(Pred->getTerminatorStmt());
    if (!If) return;
    unsigned Index = 0;
    bool Found = false;
    for (auto I = Pred->succ_begin(), E = Pred->succ_end(); I != E;
         ++I, ++Index)
      if (I->getReachableBlock() == Succ) {
        Found = true;
        break;
      }
    // The false edge is the fall-through path of
    // `if (count > length - start) return;`.
    if (!Found || Index != 1) return;
    if (If->getCond()->HasSideEffects(C)) return;
    const Expr *Condition = If->getCond()->IgnoreParenImpCasts();
    const auto *Compare = dyn_cast<BinaryOperator>(Condition);
    if (!Compare || Compare->getOpcode() != BO_GT) return;
    const Expr *Count = Compare->getLHS()->IgnoreParenImpCasts();
    const auto *Difference =
        dyn_cast<BinaryOperator>(Compare->getRHS()->IgnoreParenImpCasts());
    if (!Difference || Difference->getOpcode() != BO_Sub) return;
    const VarDecl *Source =
        sliceProjectionPlace(Difference->getLHS(), "__circle_len");
    if (!Source) return;
    S.SliceBounds.insert(
        {Source, Difference->getRHS()->IgnoreParenImpCasts(), Count});
  }
  bool placeableRawExtent(const Expr *Pointer, const Expr *Count,
                          const State &S) const {
    if (!Pointer || !Count) return false;
    // `data()` and `size()` on the same receiver name the pointer and extent
    // of one object. This is the checked form of the standard-library
    // `slice(self.data(), self.size())` idiom; the pointer provenance check
    // already ties a data-returning member to its receiver's storage.
    auto ReceiverCall = [&](const Expr *E, llvm::StringRef Name) -> const Expr * {
      const auto *Call = dyn_cast<CallExpr>(E->IgnoreParenImpCasts());
      if (!Call) return nullptr;
      const auto *Method = dyn_cast_or_null<CXXMethodDecl>(callCallee(Call));
      if (!Method || Method->getName() != Name || Call->getNumArgs() == 0)
        return nullptr;
      // Explicit self methods lower to a free call whose first argument is
      // the receiver; ordinary member calls keep it in the object slot.
      if (Method->isExplicitObjectMemberFunction() ||
          (Method->getNumParams() &&
           Method->getParamDecl(0)->getType()->getAs<BorrowValueType>()))
        return Call->getArg(0);
      if (const auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
        return Member->getImplicitObjectArgument();
      return nullptr;
    };
    const Expr *DataReceiver = ReceiverCall(Pointer, "data");
    const Expr *SizeReceiver = ReceiverCall(Count, "size");
    if (DataReceiver && SizeReceiver &&
        (Expr::isSameComparisonOperand(DataReceiver, SizeReceiver) ||
         (variable(DataReceiver) &&
          variable(DataReceiver) == variable(SizeReceiver))))
      return true;
    // `&slice[i]` performs a checked subscript. If the count is the same
    // source's length minus that same runtime index, the check proves the
    // suffix stays inside the source. This is the runtime-start/runtime-length
    // counterpart of the constant subrange rule.
    auto BoundedSubscript = [&](const Expr *E, const VarDecl *&Receiver,
                                const Expr *&Index, bool &Checked) {
      const auto *Address = dyn_cast<UnaryOperator>(E->IgnoreParenImpCasts());
      if (!Address || Address->getOpcode() != UO_AddrOf) return false;
      const Expr *Indexed = evaluationSource(
          Address->getSubExpr()->IgnoreParenImpCasts());
      Checked = false;
      while (true) {
        const auto *Comma = dyn_cast<BinaryOperator>(Indexed);
        if (!Comma || Comma->getOpcode() != BO_Comma) break;
        Checked |= containsBoundsTrap(Comma->getLHS());
        Indexed = Comma->getRHS()->IgnoreParenImpCasts();
      }
      const auto *Subscript = dyn_cast<ArraySubscriptExpr>(Indexed);
      if (!Subscript) return false;
      Receiver = variable(Subscript->getBase());
      Index = evaluationSource(Subscript->getIdx()->IgnoreParenImpCasts());
      return Receiver && Index;
    };
    const VarDecl *PointerReceiver = nullptr;
    const Expr *PointerIndex = nullptr;
    bool PointerChecked = false;
    if (BoundedSubscript(Pointer, PointerReceiver, PointerIndex,
                         PointerChecked) &&
        PointerChecked && !PointerIndex->HasSideEffects(C)) {
      if (hasSliceBound(Count, PointerReceiver, PointerIndex, S))
        return true;
      const auto *Difference =
          dyn_cast<BinaryOperator>(Count->IgnoreParenImpCasts());
      if (Difference && Difference->getOpcode() == BO_Sub) {
        const Expr *Length = Difference->getLHS()->IgnoreParenImpCasts();
        const Expr *CountIndex = Difference->getRHS()->IgnoreParenImpCasts();
        bool SameIndex =
            Expr::isSameComparisonOperand(PointerIndex, CountIndex) ||
            (variable(PointerIndex) && variable(PointerIndex) ==
                                           variable(CountIndex));
        if (SameIndex) {
          if (sliceProjectionPlace(Length, "__circle_len") == PointerReceiver)
            return true;
          if (const Expr *SizeReceiver = ReceiverCall(Length, "size");
              SizeReceiver && variable(SizeReceiver) == PointerReceiver)
            return true;
        }
      }
    }
    auto ProjectionOffset = [&](const Expr *E, llvm::StringRef Field,
                                const VarDecl *&Place, uint64_t &Offset) {
      Place = sliceProjectionPlace(E, Field);
      Offset = 0;
      if (Place) return true;
      // `&slice[i]` names the same data pointer as `slice.data() + i` while
      // keeping the safe element-access spelling. The slice's known constant
      // extent supplies the bound for the independent subrange.
      if (Field == "__circle_data") {
        const auto *Address =
            dyn_cast<UnaryOperator>(E->IgnoreParenImpCasts());
        const Expr *Indexed =
            Address && Address->getOpcode() == UO_AddrOf
                ? evaluationSource(Address->getSubExpr()->IgnoreParenImpCasts())
                : nullptr;
        // Checked slice subscripts lower to a bounds-check comma expression
        // whose last operand is the actual element access.
        while (Indexed) {
          const auto *Comma = dyn_cast<BinaryOperator>(Indexed);
          if (!Comma || Comma->getOpcode() != BO_Comma) break;
          Indexed = Comma->getRHS()->IgnoreParenImpCasts();
        }
        const auto *Subscript =
            Indexed ? dyn_cast<ArraySubscriptExpr>(Indexed) : nullptr;
        Expr::EvalResult Index;
        if (Subscript && evaluationSource(Subscript->getIdx())->EvaluateAsInt(Index, C) &&
            !Index.HasSideEffects && !Index.Val.getInt().isNegative() &&
            Index.Val.getInt().getActiveBits() <= 64) {
          const VarDecl *Slice =
              sliceProjectionPlace(Subscript->getBase(), "__circle_data");
          if (Slice) {
            Place = Slice;
            Offset = Index.Val.getInt().getZExtValue();
            return true;
          }
        }
      }
      const auto *Sub = dyn_cast<BinaryOperator>(E->IgnoreParenImpCasts());
      if (!Sub || (Sub->getOpcode() != BO_Add && Sub->getOpcode() != BO_Sub) ||
          !Sub->getRHS()->getType()->isIntegerType())
        return false;
      if (Field == "__circle_data" && !Sub->getType()->isPointerType())
        return false;
      if (Field == "__circle_len" && !Sub->getType()->isIntegerType())
        return false;
      Expr::EvalResult Value;
      if (!Sub->getRHS()->EvaluateAsInt(Value, C) || Value.HasSideEffects ||
          Value.Val.getInt().isNegative() ||
          Value.Val.getInt().getActiveBits() > 64)
        return false;
      Place = sliceProjectionPlace(Sub->getLHS(), Field);
      if (!Place) return false;
      Offset = Value.Val.getInt().getZExtValue();
      return true;
    };
    const VarDecl *Data = nullptr, *Length = nullptr;
    uint64_t DataOffset = 0, LengthOffset = 0;
    if (ProjectionOffset(Pointer, "__circle_data", Data, DataOffset) &&
        ProjectionOffset(Count, "__circle_len", Length, LengthOffset)) {
      if (Data != Length) return false;
      // The exact source slice, or a suffix whose count is the source length
      // minus the same offset, is a reborrow of the same extent.
      if (DataOffset == LengthOffset) return true;
      // A constant subrange is safe when the source extent is statically
      // known: `data + k, n` must fit inside that extent. A constant prefix
      // (`data, n`) is the same rule with k = 0.
      uint64_t Extent = 0;
      if (!sliceKnownExtent(Data, Extent)) return false;
      Expr::EvalResult Size;
      if (Count->EvaluateAsInt(Size, C) && !Size.HasSideEffects &&
          !Size.Val.getInt().isNegative() &&
          Size.Val.getInt().getActiveBits() <= 64) {
        uint64_t N = Size.Val.getInt().getZExtValue();
        return DataOffset <= Extent && N <= Extent - DataOffset;
      }
      return false;
    }
    if (Data) {
      uint64_t Extent = 0;
      Expr::EvalResult Size;
      if (!sliceKnownExtent(Data, Extent))
        return false;
      if (!Count->EvaluateAsInt(Size, C) || Size.HasSideEffects ||
          Size.Val.getInt().isNegative() ||
          Size.Val.getInt().getActiveBits() > 64)
        return false;
      uint64_t N = Size.Val.getInt().getZExtValue();
      return DataOffset <= Extent && N <= Extent - DataOffset;
    }
    QualType Element = Pointer->getType()->isPointerType()
                           ? Pointer->getType()->getPointeeType() : QualType();
    const Expr *Array = Pointer->IgnoreParenImpCasts();
    // A constant offset narrows the suffix the count has to fit in. Both
    // spellings of a suffix start, `array + k` and `&array[k]`, name one.
    uint64_t Start = 0;
    if (const auto *Add = dyn_cast<BinaryOperator>(Array);
        Add && Add->getOpcode() == BO_Add && Add->getType()->isPointerType()) {
      const Expr *Base = Add->getLHS();
      const Expr *Offset = Add->getRHS();
      if (Offset->getType()->isPointerType()) std::swap(Base, Offset);
      Expr::EvalResult Index;
      if (!Offset->getType()->isIntegerType() || !Offset->EvaluateAsInt(Index, C) ||
          Index.HasSideEffects || Index.Val.getInt().isNegative() ||
          Index.Val.getInt().getActiveBits() > 64)
        return false;
      Start = Index.Val.getInt().getZExtValue();
      Array = Base->IgnoreParenImpCasts();
    } else if (const auto *Address = dyn_cast<UnaryOperator>(Array);
               Address && Address->getOpcode() == UO_AddrOf) {
      const auto *Subscript =
          dyn_cast<ArraySubscriptExpr>(Address->getSubExpr()->IgnoreParenImpCasts());
      Expr::EvalResult Index;
      if (!Subscript || !Subscript->getIdx()->EvaluateAsInt(Index, C) ||
          Index.HasSideEffects || Index.Val.getInt().isNegative() ||
          Index.Val.getInt().getActiveBits() > 64)
        return false;
      Start = Index.Val.getInt().getZExtValue();
      Array = Subscript->getBase()->IgnoreParenImpCasts();
    }
    while (auto *Cast = dyn_cast<CastExpr>(Array)) {
      if (Cast->getCastKind() != CK_NoOp && Cast->getCastKind() != CK_BitCast &&
          Cast->getCastKind() != CK_ArrayToPointerDecay)
        return false;
      Array = Cast->getSubExpr()->IgnoreParenImpCasts();
    }
    auto *Allocation = C.getAsConstantArrayType(Array->getType());
    Expr::EvalResult Size;
    if (!Allocation || Element.isNull() ||
        C.getTypeSizeInChars(Element.getUnqualifiedType()) !=
            C.getTypeSizeInChars(Allocation->getElementType().getUnqualifiedType()) ||
        !Count->EvaluateAsInt(Size, C) || Size.HasSideEffects ||
        Size.Val.getInt().isNegative() ||
        Size.Val.getInt().getActiveBits() > 64)
      return false;
    uint64_t End = Size.Val.getInt().getZExtValue();
    return Start <= Allocation->getSize().getZExtValue() &&
           End <= Allocation->getSize().getZExtValue() - Start;
  }
#endif
  Vars rawPointerRoots(const Expr *E, const State &S) {
#ifdef MODULE_SAFETY_BUILTIN
    if (!E || !C.getLangOpts().CircleBorrowValues) return {};
    E = evaluationSource(E->IgnoreParens());
    if (isa<StringLiteral>(E)) return {LiteralOrigin};
    // The data pointer of a slice names that slice's region. This also lets
    // the pointer side of a constant subrange carry the source provenance;
    // the extent check below keeps the offset inside a known allocation.
    if (const VarDecl *Place = sliceProjectionPlace(E, "__circle_data")) {
      Vars R = roots(Place, S);
      for (auto *Root : R)
        if (S.InvalidRawRoots.count(Root) || S.Moved.count(Root) ||
            S.Relocated.count(Root) ||
            (!Root->hasGlobalStorage() && !S.Ready.count(Root))) return {};
      return R;
    }
    if (Vars Element = sequenceElementRoots(E, S); !Element.empty()) {
      for (auto *Root : Element)
        if (S.InvalidRawRoots.count(Root) || S.Moved.count(Root) ||
            S.Relocated.count(Root) ||
            (!Root->hasGlobalStorage() && !S.Ready.count(Root))) return {};
      return Element;
    }
    if (const auto *Cast = dyn_cast<CastExpr>(E)) {
      if (Cast->getCastKind() == CK_BitCast) {
        auto A = Cast->getSubExpr()->getType(), B = Cast->getType();
        // A cast through a void pointer keeps the referent, and therefore the
        // provenance, of the pointer it converts.
        bool ThroughVoid =
            A->isPointerType() && B->isPointerType() &&
            (A->getPointeeType()->isVoidType() || B->getPointeeType()->isVoidType());
        if (!A->isPointerType() || !B->isPointerType() ||
            (!ThroughVoid &&
             !C.hasSameUnqualifiedType(A->getPointeeType(), B->getPointeeType())))
          return {};
      } else if (Cast->getCastKind() != CK_NoOp &&
                 Cast->getCastKind() != CK_LValueToRValue &&
                 Cast->getCastKind() != CK_ArrayToPointerDecay) return {};
      return rawPointerRoots(Cast->getSubExpr(), S);
    }
    if (const auto *Call = dyn_cast<CallExpr>(E)) {
      const auto *Callee = callCallee(Call);
      if (Callee && Callee->getIdentifier() &&
          Callee->getIdentifier()->getName() == "__slice_pointer" &&
          Call->getNumArgs()) {
        if (Vars Roots = rawPointerRoots(Call->getArg(0), S); !Roots.empty())
          return Roots;
        if (const VarDecl *Place =
                sliceProjectionPlace(Call->getArg(0), "__circle_data"))
          return roots(Place, S);
      }
    }
    Vars Result;
    if (const auto *U = dyn_cast<UnaryOperator>(E);
        U && U->getOpcode() == UO_Deref && nativeBorrowDereference(U))
      // A borrow names its referent: the address derived from it belongs to
      // the loan's source, not to the handle's own storage.
      Result = expressionRoots(U->getSubExpr(), S);
    else if (const auto *U = dyn_cast<UnaryOperator>(E);
             U && U->getOpcode() == UO_AddrOf)
      Result = storageRoots(U->getSubExpr(), S);
    else if (const auto *U = dyn_cast<UnaryOperator>(E);
             U && U->isIncrementDecrementOp() && E->getType()->isPointerType())
      // Stepping a pointer keeps the region that pointer already names.
      Result = rawPointerRoots(U->getSubExpr(), S);
    else if (E->getType()->isArrayType()) Result = storageRoots(E, S);
    else if (const auto *Arithmetic = dyn_cast<BinaryOperator>(E);
             Arithmetic && (Arithmetic->getOpcode() == BO_Add ||
                            Arithmetic->getOpcode() == BO_Sub) &&
             E->getType()->isPointerType()) {
      const bool Subtract = Arithmetic->getOpcode() == BO_Sub;
      const Expr *Base = Arithmetic->getLHS();
      const Expr *Offset = Arithmetic->getRHS();
      // `pointer + integer` and `pointer - integer` both keep the pointer's
      // referent provenance; `integer - pointer` does not form a pointer.
      if (!Subtract && Offset->getType()->isPointerType()) std::swap(Base, Offset);
      if (Offset->getType()->isPointerType() ||
          !Offset->getType()->isIntegerType() || Offset->HasSideEffects(C))
        return {};
      const Expr *Array = Base->IgnoreParenImpCasts();
      while (auto *Cast = dyn_cast<CastExpr>(Array)) Array = Cast->getSubExpr()->IgnoreParenImpCasts();
      if (auto *Allocation = C.getAsConstantArrayType(Array->getType())) {
        // An offset into a known array of a compile-time size stays inside it
        // only while the constant offset does; the offset pointer names that
        // array's region. A runtime or backwards offset from the first
        // element cannot be placed here.
        Expr::EvalResult Index;
        if (!Offset->EvaluateAsInt(Index, C) || Index.HasSideEffects ||
            Index.Val.getInt().isNegative() ||
            Index.Val.getInt().getActiveBits() > 64)
          return {};
        if (Allocation->getSize().getActiveBits() > 64 ||
            (Subtract ? Index.Val.getInt().getZExtValue() != 0
                      : Index.Val.getInt().getZExtValue() >=
                            Allocation->getSize().getZExtValue()))
          return {};
        Result = storageRoots(Array, S);
      } else {
        if (const VarDecl *Place = sliceProjectionPlace(Base, "__circle_data")) {
          uint64_t Extent = 0;
          Expr::EvalResult Index;
          if (!sliceKnownExtent(Place, Extent) ||
              !Offset->EvaluateAsInt(Index, C) || Index.HasSideEffects ||
              Index.Val.getInt().isNegative() ||
              Index.Val.getInt().getActiveBits() > 64 ||
              (Subtract && Index.Val.getInt().getZExtValue() != 0) ||
              (!Subtract &&
               Index.Val.getInt().getZExtValue() >= Extent))
            return {};
          Result = roots(Place, S);
        } else {
        // An offset from a pointer whose allocation this subset cannot see is
        // the same claim the base pointer already makes: unchecked code
        // asserts the element is live at the offset. Its origin is the base's
        // origin whether the offset is constant, runtime-computed, or
        // negative, so two offsets of one origin still conflict
        // conservatively. Only an opaque external pointer can carry this
        // claim; a local or otherwise known owner would need its own placement
        // proof.
          Result = rawPointerRoots(Base, S);
          for (auto *Root : Result)
            if (!ExternalPointerRoots.count(Root)) return {};
        }
      }
    }
    else if (const auto *Conditional = dyn_cast<ConditionalOperator>(E)) {
      Result = rawPointerRoots(Conditional->getTrueExpr(), S);
      auto Other = rawPointerRoots(Conditional->getFalseExpr(), S);
      if (Result.empty() || Other.empty()) return {};
      Result.insert(Other.begin(), Other.end());
    } else if (const auto *Member = dyn_cast<MemberExpr>(E);
               Member && E->getType()->isPointerType()) {
      // A raw pointer stored in a field is a handle into storage the owning
      // object is responsible for. The pointee's region follows the object:
      // `self->p_` in an owning wrapper names `self`, so the data pointer and
      // the length of `slice(self.data(), self.size())` stay in one region.
      Result = expressionRoots(Member->getBase(), S);
      if (Result.empty()) Result = storageRoots(Member->getBase(), S);
    } else if (const auto *MemberCall = dyn_cast<CXXMemberCallExpr>(E);
               MemberCall && E->getType()->isPointerType()) {
      // A member function that hands out a raw pointer is assumed to reach
      // storage owned by its receiver. This is conservative for a member that
      // returns a pointer to unrelated permanent storage.
      if (const Expr *Object = MemberCall->getImplicitObjectArgument())
        Result = expressionRoots(Object, S);
      if (Result.empty())
        if (const Expr *Object = MemberCall->getImplicitObjectArgument())
          Result = receiverRoots(Object, S);
    } else if (const auto *Call = dyn_cast<CallExpr>(E);
               Call && E->getType()->isPointerType()) {
      // Circle spells a receiver method as a call with the object in the
      // first argument slot (`self.data()` lowers like `data(self)`).
      if (const auto *Method =
              dyn_cast_or_null<CXXMethodDecl>(Call->getDirectCallee());
          Method && Call->getNumArgs() &&
          (Method->isImplicitObjectMemberFunction() ||
           (Method->getNumParams() &&
            Method->getParamDecl(0)->getType()->getAs<BorrowValueType>())))
        Result = expressionRoots(Call->getArg(0), S);
      if (Result.empty() && Call->getNumArgs())
        Result = receiverRoots(Call->getArg(0), S);
    } else if (const auto *V = variable(E); V && E->getType()->isPointerType()) {
      if (S.EscapedPointerSlots.count(V)) return {};
      if (const auto *P = dyn_cast<ParmVarDecl>(V);
          P && P->getDeclContext() == F) {
        if (auto *Proto = F->getType()->getAs<FunctionProtoType>())
          if ((F->getLiteralIdentifier() && P->getFunctionScopeIndex() == 0) ||
              Proto->getExtParameterInfo(P->getFunctionScopeIndex())
                  .hasStaticLifetime())
            return {V};
      }
      if (auto I = S.Loans.find(V); I != S.Loans.end()) Result = I->second.Roots;
      else if (auto I = S.RawPointers.find(V); I != S.RawPointers.end()) Result = I->second;
      else if (V->hasGlobalStorage() && V->getType().isConstQualified() && V->hasInit())
        Result = rawPointerRoots(V->getInit(), S);
    }
    for (auto *Root : Result)
      if (S.InvalidRawRoots.count(Root) || S.Moved.count(Root) || S.Relocated.count(Root) ||
          (!Root->hasGlobalStorage() && !S.Ready.count(Root))) return {};
    return Result;
#else
    return {};
#endif
  }
  const FunctionProtoType *callPrototype(const CallExpr *Call) const {
    if (!Call) return nullptr;
    if (auto *Method = modulesafety::indirectMemberCallee(Call))
      return Method->getType()->getAs<FunctionProtoType>();
    auto *Callee = callCallee(Call);
    auto T = Callee ? Callee->getType() : Call->getCallee()->getType();
    if (T->isPointerType()) T = T->getPointeeType();
    return T->getAs<FunctionProtoType>();
  }
  const FunctionDecl *callCallee(const CallExpr *Call) const {
    if (!Call) return nullptr;
    if (const auto *Callee = Call->getDirectCallee()) return Callee;
    // A user-defined literal is a CallExpr whose callee is a DeclRefExpr, but
    // its direct-callee query is not populated by the literal parser.
    if (const auto *Ref =
            dyn_cast<DeclRefExpr>(Call->getCallee()->IgnoreParenImpCasts()))
      return dyn_cast<FunctionDecl>(Ref->getDecl());
    return nullptr;
  }
  Vars generativeCallRoots(const CallExpr *Call, const FunctionProtoType *Proto,
                           const State &S) {
    Vars Result;
    bool RawInputs = false;
    unsigned Offset = isa<CXXOperatorCallExpr>(Call) &&
                      implicitObjectMethod(Call->getDirectCallee()) ? 1u : 0u;
    for (unsigned I = 0; I < Proto->getNumParams(); ++I) {
      auto T = Proto->getParamType(I);
      if (!T->isPointerType() || T->getPointeeType()->isFunctionType()) continue;
      RawInputs = true;
      if (I + Offset >= Call->getNumArgs()) return {};
      auto R = rawPointerRoots(Call->getArg(I + Offset), S);
#ifdef MODULE_SAFETY_BUILTIN
      // A slice's own data pointer names that slice's region, so rebuilding a
      // slice from one slice's data pointer and length borrows its region.
      if (R.empty())
        if (const VarDecl *Place =
                sliceProjectionPlace(Call->getArg(I + Offset), "__circle_data"))
          R = roots(Place, S);
#endif
      if (R.empty()) return {};
      Result.insert(R.begin(), R.end());
    }
    return RawInputs ? Result : Vars{StaticOrigin};
  }
  Vars staticFieldRoots(const Expr *Base, const State &S) {
    if (containsStringLiteral(Base)) return {LiteralOrigin};
    Vars Result;
    for (auto *Root : expressionRoots(Base, S)) {
      Vars Seen;
      if (permanentRoot(Root, S, Seen)) Result.insert(Root);
      else if (auto *V = dyn_cast<VarDecl>(Root);
               V && V->hasInit() && containsStringLiteral(V->getInit()))
        Result.insert(LiteralOrigin);
    }
    // A parameter receiver has no permanent provenance of its own; its static
    // field still promises permanent storage, so name the unknown automatically.
    return Result.empty() ? Vars{StaticOrigin} : Result;
  }
  // Provenance of a call whose declared result has `/static` lifetime. The
  // contract promises only that the referent outlives the call; it does not
  // say whether that storage is mutable. Where the body is visible, keep the
  // root it actually returns so immutable literals and mutable globals stay
  // distinguishable at every later use.
  Vars staticCallRoots(const CallExpr *Call, const FunctionDecl *Callee,
                       const State &S) {
    const FunctionDecl *Definition =
        Callee ? Callee->getDefinition() : nullptr;
    const Expr *Result = nullptr;
    if (Definition && Definition->hasBody()) {
      class Returns : public RecursiveASTVisitor<Returns> {
      public:
        const Expr *Value = nullptr;
        bool VisitReturnStmt(ReturnStmt *R) {
          if (!Value && R->getRetValue()) Value = R->getRetValue();
          return true;
        }
      } Visitor;
      Visitor.TraverseStmt(Definition->getBody());
      Result = Visitor.Value;
    }
    if (!Result) return {StaticOrigin};
    // The definitions this summary reads are ordinary checked functions; a
    // return inside a nested lambda belongs to that lambda, not to `Definition`.
    Result = Result->IgnoreParenImpCasts();
    if (containsStringLiteral(Result)) return {LiteralOrigin};
    State Bound = S;
    if (Definition)
      for (unsigned I = 0; I < Definition->getNumParams() &&
                           I < Call->getNumArgs(); ++I) {
        auto *P = Definition->getParamDecl(I);
        if (P->getType()->isPointerType()) {
          // A pointer parameter can carry a literal or another permanent
          // origin through a checked body; keeping the binding preserves it.
          auto R = rawPointerRoots(Call->getArg(I), S);
          if (!R.empty())
            Bound.Loans[P] = {R, false};
          continue;
        }
        if (hasStaticLifetimeFields(P->getType())) {
          auto R = staticFieldRoots(Call->getArg(I), S);
          if (!R.empty())
            Bound.Loans[P] = {R, false};
          continue;
        }
        if (!objectBorrow(P->getType()) && !P->getType()->isReferenceType())
          continue;
        auto R = referenceRoots(Call->getArg(I), P->getType(), S);
        if (!R.empty())
          Bound.Loans[P] = {R, objectBorrow(P->getType(), true)};
      }
    if (auto *Member = dyn_cast<MemberExpr>(Result))
      if (staticLifetimeField(dyn_cast<FieldDecl>(Member->getMemberDecl())))
        // A method projecting its own static field carries the provenance the
        // receiver was constructed with. `string_constant::text` is the
        // important case: a literal stays a literal instead of becoming the
        // opaque "some permanent storage" sentinel.
        return staticFieldRoots(Member->getBase(), Bound);
    Vars R = expressionRoots(Result, Bound);
    for (auto *Root : R)
      if (Root != StaticOrigin && Root != LiteralOrigin &&
          (!Root->hasGlobalStorage() || Root->getDeclContext() == Definition))
        return {StaticOrigin};
    return R.empty() ? Vars{StaticOrigin} : R;
  }
  Vars expressionRoots(const Expr *E, const State &S) {
    E = evaluationSource(E);
#ifdef MODULE_SAFETY_BUILTIN
    if (E && circleIsCallableValue(E->getType()) && !circleCallableCaptures(E->getType()).empty()) {
      Vars Result;
      for (const auto &[ID, Part] : callableRegions(E, E->getType(), S)) {
        if (Part.empty()) return {};
        Result.insert(Part.begin(), Part.end());
      }
      return Result;
    }
#endif
    if (!E)
      return {};
    const Expr *Original = E;
    for (;;) {
      if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Original))
        Original = Cleanup->getSubExpr();
      else if (auto *Cast = dyn_cast<ImplicitCastExpr>(Original))
        Original = Cast->getSubExpr();
      else if (auto *Paren = dyn_cast<ParenExpr>(Original))
        Original = Paren->getSubExpr();
      else
        break;
    }
    if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Original))
      if (auto *Owner = dyn_cast_or_null<VarDecl>(Temporary->getExtendingDecl())) {
        if (objectBorrow(Temporary->getType())) {
          auto R = expressionRoots(Temporary->getSubExpr(), S);
          if (R.empty())
            return {};
          R.insert(Owner);
          return R;
        }
        return {Owner};
      }
    E = evaluationSource(E->IgnoreParenImpCasts());
    while (auto *Cleanups = dyn_cast<ExprWithCleanups>(E))
      E = Cleanups->getSubExpr()->IgnoreParenImpCasts();
    if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      return expressionRoots(Bound->getSubExpr(), S);
    if (auto *Cast = dyn_cast<CastExpr>(E))
      return expressionRoots(Cast->getSubExpr(), S);
    if (auto *Default = dyn_cast<CXXDefaultInitExpr>(E))
      return expressionRoots(Default->getExpr(), S);
    if (auto *Default = dyn_cast<CXXDefaultArgExpr>(E))
      return expressionRoots(Default->getExpr(), S);
    if (indirectBorrowStorage(E->getType()) && emptyIndirectConstruction(E))
      return {LiteralOrigin};
    // Circle lowers `match` to a statement expression so pattern bindings are
    // scoped to the selected arm. The value expression is the statement
    // expression's final expression and carries the result's provenance.
    if (auto *Statement = dyn_cast<StmtExpr>(E))
      if (auto *Body = Statement->getSubStmt())
        if (auto *Last = dyn_cast_or_null<Expr>(Body->body_back()))
          return expressionRoots(Last, S);
    if (isa<CXXThisExpr>(E) && ThisOrigin)
      return {ThisOrigin};
    if (isa<StringLiteral>(E)) return {LiteralOrigin};
    if (auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && (hasStaticLifetimeFields(E->getType())
#ifdef MODULE_SAFETY_BUILTIN
                      || circleClassHasStaticArguments(E->getType())
#endif
                      )) {
      // A class with a static field carries the provenance its constructor
      // supplied, not the local storage of the class value. A literal
      // operator's string_view therefore keeps the literal's immutable origin
      // instead of collapsing to the opaque permanent sentinel.
      Vars Result;
      for (auto *Arg : Construct->arguments())
        for (auto *Root : expressionRoots(Arg, S)) Result.insert(Root);
      if (!Result.empty()) return Result;
      return {StaticOrigin};
    }
    if (Vars Element = sequenceElementRoots(E, S); !Element.empty())
      return Element;
    if (auto *U = dyn_cast<UnaryOperator>(E); U && nativeRelocation(U))
      return expressionRoots(U->getSubExpr(), S);
    if (auto *B = dyn_cast<BinaryOperator>(E);
        B && B->getOpcode() == BO_Comma)
      // Generated bounds checks precede the selected value in a comma
      // expression. The value, not the check, carries the result's origin.
      return expressionRoots(B->getRHS(), S);
    if (auto *U = dyn_cast<UnaryOperator>(E); U && nativeBorrow(U)) {
      auto R = expressionRoots(U->getSubExpr(), S);
      auto Storage = addressStorageRoots(U->getSubExpr(), S);
      R.insert(Storage.begin(), Storage.end());
      return R;
    }
    if (auto *U = dyn_cast<UnaryOperator>(E); U && U->getOpcode() == UO_Deref) {
#ifdef MODULE_SAFETY_BUILTIN
      if (C.getLangOpts().CircleBorrowValues &&
          !nativeBorrowDereference(U) &&
          U->getSubExpr()->getType()->isPointerType()) {
        const Expr *Pointer = U->getSubExpr()->IgnoreParenImpCasts();
        if (isa<CXXThisExpr>(Pointer) && ThisOrigin)
          return {ThisOrigin};
        if (auto *Address = dyn_cast<UnaryOperator>(Pointer);
            Address && Address->getOpcode() == UO_AddrOf)
          return expressionRoots(Address->getSubExpr(), S);
        return rawPointerRoots(U->getSubExpr(), S);
      }
#endif
      return expressionRoots(U->getSubExpr(), S);
    }
    if (auto *Index = dyn_cast<ArraySubscriptExpr>(E)) {
      // Reading a borrow-valued element reads the array's carried data. Its
      // address only identifies the handle storage, whose lifetime may be
      // shorter (for example an array inside a by-value class parameter).
      // Keep the array's saved field/aggregate summary before pointer decay.
      const Expr *Array = Index->getBase()->IgnoreParenImpCasts();
      if (objectBorrow(Index->getType()) && Array->getType()->isArrayType())
        return expressionRoots(Array, S);
      // Scalar elements reached through a raw pointer borrow the allocation
      // that pointer names; their base expression carries its provenance.
      auto R = rawPointerRoots(Index->getBase(), S);
      if (!R.empty()) return R;
    }
    if (auto *Member = dyn_cast<MemberExpr>(E)) {
      // A static field is permanent, but its bytes can still be immutable
      // (a string literal) or mutable (a global array). Read the provenance
      // the holding object was constructed with and keep the sentinel only
      // when the subset cannot recover a permanent one.
      if (staticLifetimeField(dyn_cast<FieldDecl>(Member->getMemberDecl())))
        return staticFieldRoots(Member->getBase(), S);
#ifdef MODULE_SAFETY_BUILTIN
      if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
          fieldClassRegion(Field))
        return classRegionRoots(Member->getBase(),
              cast<CXXRecordDecl>(Field->getParent()), fieldClassRegion(Field), S);
      if (auto *Deref = dyn_cast<UnaryOperator>(Member->getBase()->IgnoreParenImpCasts());
          Deref && nativeBorrowDereference(Deref) &&
          Deref->getSubExpr()->getType()->getAs<BorrowValueType>())
        return expressionRoots(Member->getBase(), S);
#endif
      if (auto Field = ownedFieldPath(Member); !Field.empty() && S.Fields.count(variable(Member)) && objectBorrow(Member->getType()))
        return fieldRoots(variable(Member), Field, S);
      if (auto Field = ownedFieldPath(Member); !Field.empty())
        if (fieldOrigin(variable(Member), Field))
          return withRetainedOrigins(ownedPlaces(variable(Member), Field), S);
      if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
          Field && !objectBorrow(Field->getType()))
        if (auto *Base = variable(Member->getBase());
            Base && objectBorrow(Base->getType()))
          return storageRoots(Member->getBase(), S);
      return expressionRoots(Member->getBase(), S);
    }
    if (auto *V = variable(E); V && !isa<CallExpr>(E)) {
      auto Loan = S.Loans.find(V);
      if ((Loan == S.Loans.end() || Loan->second.Roots.empty()))
        if (auto I = MatchOrigins.find(V);
            I != MatchOrigins.end() && !I->second.empty())
          return canonicalRegions(I->second, S);
      if ((Loan == S.Loans.end() || Loan->second.Roots.empty()) &&
          V->hasInit() &&
          (objectBorrow(V->getType()) ||
           marked(V, "safecpp.native.match.subject") ||
           marked(V, "safecpp.native.match.binding")) &&
          !S.Moved.count(V) && !S.Relocated.count(V)) {
        return expressionRoots(V->getInit(), S);
      }
      return roots(V, S);
    }
    if (auto *Conditional = dyn_cast<ConditionalOperator>(E)) {
      auto Left = expressionRoots(Conditional->getTrueExpr(), S);
      auto Right = expressionRoots(Conditional->getFalseExpr(), S);
      if (Left.empty() && cannotReturn(Conditional->getTrueExpr()))
        return Right;
      if (Right.empty() && cannotReturn(Conditional->getFalseExpr()))
        return Left;
      if (Left.empty() || Right.empty())
        return {};
      Left.insert(Right.begin(), Right.end());
      return Left;
    }
    if (auto *Lambda = dyn_cast<LambdaExpr>(E);
        Lambda && objectBorrow(Lambda->getType())) {
      Vars Result;
      std::vector<std::pair<Vars, bool>> Captures;
      auto Init = Lambda->capture_init_begin();
      for (const auto &Capture : Lambda->captures()) {
        const Expr *Value = *Init++;
        if (!Capture.capturesVariable())
          return {};
        auto *V = dyn_cast<VarDecl>(Capture.getCapturedVar());
        if (!V)
          return {};
        if (Capture.getCaptureKind() == LCK_ByRef || objectBorrow(V->getType())) {
          auto T = Capture.getCaptureKind() == LCK_ByRef
                       ? C.getLValueReferenceType(V->getType().getNonReferenceType())
                       : V->getType();
          auto Part = referenceRoots(Value, T, S);
          if (Part.empty())
            return {};
          bool Mut = objectBorrow(T, true);
          for (const auto &[Other, Exclusive] : Captures)
            for (auto *Root : Part)
              if (Other.count(Root) && (Mut || Exclusive))
                error(Lambda, "closure captures alias an exclusive borrow");
          Captures.emplace_back(Part, Mut);
          Result.insert(Part.begin(), Part.end());
        }
      }
      return Result;
    }
    if (auto *Init = dyn_cast<InitListExpr>(E)) {
#ifdef MODULE_SAFETY_BUILTIN
      // A raw pointer's own storage says nothing about its pointee lifetime.
      // Preserve origins only for a known array allocation and a constant
      // extent within it; opaque pointer factories need a separate model.
      if (C.circleSliceField(Init->getType(), false) && Init->getNumInits() == 2) {
        const Expr *Pointer = Init->getInit(0);
        if (const Expr *Array = arraySliceSource(Init))
          return expressionRoots(Array, S);
        // The data pointer and the length of one existing slice rebuild that
        // same slice: the same place, the same bytes, so the same region and
        // the same extent. Taking either half from somewhere else is not this
        // rule, and a reinterpretation that changes the element size would
        // make the copied length reach a different distance.
        if (const VarDecl *Place = sliceProjectionPlace(Init->getInit(0), "__circle_data"))
          if (Place == sliceProjectionPlace(Init->getInit(1), "__circle_len") &&
              sameSliceElementSize(Pointer, Place))
            return roots(Place, S);
        return {};
      }
#endif
    }
    if (auto *Init = dyn_cast<InitListExpr>(E);
        Init && (objectBorrow(Init->getType()) || indirectBorrowStorage(Init->getType()))) {
      Vars Result;
      auto *Record = Init->getType()->getAsCXXRecordDecl();
      if (Init->getType()->isArrayType()) {
        std::vector<std::pair<Vars, bool>> Elements;
        std::vector<std::pair<const Expr *, QualType>> Initializers;
        std::vector<Vars> InitializerRoots;
        bool Mut = objectBorrow(Init->getType(), true);
        for (auto *Value : Init->inits()) {
          auto Part = expressionRoots(Value, S);
          if (Part.empty())
            return {};
          Initializers.emplace_back(Value, Value->getType());
          InitializerRoots.push_back(Part);
          for (const auto &[Other, Exclusive] : Elements)
            for (auto *Root : Part)
              if (Other.count(Root) && (Mut || Exclusive))
                error(Init, "array elements alias an exclusive borrow");
          Elements.emplace_back(Part, Mut);
          Result.insert(Part.begin(), Part.end());
        }
        // List initialization is sequenced: an earlier element's temporary
        // loan must survive evaluation of every later initializer.
        ephemeralBorrows(Initializers, Init, S, &InitializerRoots, true);
        return Result;
      }
      if (!Record || !Record->hasDefinition())
        return {};
      unsigned I = 0;
      std::vector<std::pair<const Expr *, QualType>> Initializers;
      for (const auto &Base : Record->getDefinition()->bases())
        if (I < Init->getNumInits())
          Initializers.emplace_back(Init->getInit(I++), Base.getType());
      for (auto *Field : Record->getDefinition()->fields())
        if (I < Init->getNumInits())
          Initializers.emplace_back(Init->getInit(I++), Field->getType());
      // Resolve each initializer once in this state. Both the sibling-effect
      // check and the aggregate payload need these same roots; recursively
      // resolving them in each pass doubles a nested aggregate's work.
      std::vector<Vars> InitializerRoots(Initializers.size());
      for (unsigned J = 0; J < Initializers.size(); ++J) {
        auto [Value, Type] = Initializers[J];
        if (Type->isReferenceType() || objectBorrow(Type) ||
            indirectBorrowStorage(Type))
          InitializerRoots[J] = referenceRoots(Value, Type, S);
      }
      ephemeralBorrows(Initializers, Init, S, &InitializerRoots);
      I = 0;
      struct FieldLoan {
        Vars Roots;
        bool Exclusive;
        const Expr *Origin;
      };
      std::vector<FieldLoan> Fields;
      for (const auto &Base : Record->getDefinition()->bases()) {
        if (objectBorrow(Base.getType()) || indirectBorrowStorage(Base.getType())) {
          if (I >= Init->getNumInits())
            return {};
          auto Part = InitializerRoots[I];
          if (Part.empty())
            return {};
          bool Mut = objectBorrow(Base.getType(), true) ||
                     indirectBorrowStorage(Base.getType(), {}, {}, true);
          for (const auto &[Other, Exclusive, Origin] : Fields)
            for (auto *Root : Part)
              if (Root != LiteralOrigin && Other.count(Root) && (Mut || Exclusive))
                error(Init, "base subobjects alias an exclusive borrow");
          Fields.push_back({Part, Mut, Init->getInit(I)});
          Result.insert(Part.begin(), Part.end());
        }
        ++I;
      }
      for (auto *Field : Record->getDefinition()->fields()) {
        if (objectBorrow(Field->getType()) || indirectBorrowStorage(Field->getType())) {
          if (I >= Init->getNumInits())
            return {};
          auto Part = InitializerRoots[I];
          if (Part.empty())
            return {};
          bool Mut = objectBorrow(Field->getType(), true) ||
                     indirectBorrowStorage(Field->getType(), {}, {}, true);
          for (const auto &[Other, Exclusive, Origin] : Fields)
            for (auto *Root : Part)
              if (Other.count(Root) && (Mut || Exclusive) &&
                  Root != LiteralOrigin &&
                  !disjointOwnedFields(Origin, Init->getInit(I)))
                error(Init, "aggregate fields alias an exclusive borrow");
          Fields.push_back({Part, Mut, Init->getInit(I)});
          Result.insert(Part.begin(), Part.end());
        }
        ++I;
      }
      return Result;
    }
    if (auto *Construct = dyn_cast<CXXConstructExpr>(E);
        Construct && (objectBorrow(Construct->getType()) ||
                      indirectBorrowStorage(Construct->getType()))) {
      const auto *Ctor = Construct->getConstructor();
      if (Ctor->isImplicit() && Construct->getNumArgs() == 1 &&
          (Ctor->isCopyConstructor() || Ctor->isMoveConstructor())) {
        // Copy the element's carried borrows, not the lifetime of its slot.
        Vars Payload;
        if (Ctor->isCopyConstructor() &&
            copiedIndirectElementRoots(Construct->getArg(0),
                                       Construct->getType(), S, Payload))
          return Payload;
        if (auto *Source = variable(Construct->getArg(0)))
          return roots(Source, S);
        return expressionRoots(Construct->getArg(0), S);
      }
      const FunctionDecl *Definition = nullptr;
      if (!Ctor->hasBody(Definition)) {
        Vars Result;
        if (modulesafety::marked(Ctor, "safecpp.stores.self") && CreationTarget &&
            pinnedStorage(Construct->getType()))
          Result.insert(CreationTarget);
        for (auto I : storedParameters(Ctor)) {
          if (I >= Construct->getNumArgs())
            return {};
          auto Part =
              referenceRoots(Construct->getArg(I), Ctor->getParamDecl(I)->getType(), S);
          if (Part.empty())
            return {};
          Result.insert(Part.begin(), Part.end());
        }
        return Result;
      }
      Ctor = cast<CXXConstructorDecl>(Definition);
      State Bound;
      for (unsigned I = 0; I < Ctor->getNumParams() && I < Construct->getNumArgs();
           ++I) {
        auto *P = Ctor->getParamDecl(I);
        Bound.Ready.insert(P);
        if (P->getType()->isReferenceType() || objectBorrow(P->getType()) ||
            indirectBorrowStorage(P->getType()))
          Bound.Loans[P] = {referenceRoots(Construct->getArg(I), P->getType(), S),
                            objectBorrow(P->getType(), true)};
      }
      Vars Result;
      std::vector<std::pair<Vars, bool>> Fields;
      for (auto *Init : Ctor->inits()) {
        QualType Storage;
        if (Init->isMemberInitializer())
          Storage = Init->getMember()->getType();
        else if (Init->isBaseInitializer())
          Storage = QualType(Init->getBaseClass(), 0);
        else if (Init->isDelegatingInitializer())
          Storage = Init->getInit()->getType();
        if (!Storage.isNull() && (objectBorrow(Storage) || indirectBorrowStorage(Storage))) {
          std::vector<const Stmt *> Pending{Init->getInit()};
          while (!Pending.empty()) {
            auto *Node = Pending.back();
            Pending.pop_back();
            if (isa<CXXThisExpr>(Node) &&
                !(CreationTarget && pinnedStorage(Construct->getType())))
              return {};
            for (auto *Child : Node->children())
              if (Child)
                Pending.push_back(Child);
          }
          auto *SavedThis = ThisOrigin;
          if (CreationTarget && pinnedStorage(Construct->getType()))
            ThisOrigin = CreationTarget;
          auto Part = expressionRoots(Init->getInit(), Bound);
          ThisOrigin = SavedThis;
          if (auto *Member =
                  dyn_cast<MemberExpr>(Init->getInit()->IgnoreParenImpCasts());
              Member && isa<FieldDecl>(Member->getMemberDecl()) &&
              cast<FieldDecl>(Member->getMemberDecl())->getType()->isReferenceType())
            if (auto *Reference =
                    dyn_cast<DeclRefExpr>(Member->getBase()->IgnoreParenImpCasts()))
              if (auto *Parameter = dyn_cast<ParmVarDecl>(Reference->getDecl()))
                for (unsigned I = 0;
                     I < Ctor->getNumParams() && I < Construct->getNumArgs(); ++I)
                  if (Ctor->getParamDecl(I) == Parameter)
                    if (auto *Source = variable(Construct->getArg(I));
                        Source && !Source->getType()->isReferenceType() &&
                        !roots(Source, S).count(Source))
                      Part.erase(Source);
          if (Part.empty())
            return {};
          bool Mut = objectBorrow(Storage, true) ||
                     indirectBorrowStorage(Storage, {}, {}, true);
          for (const auto &[Other, Exclusive] : Fields)
            for (auto *Root : Part)
              if (Root != LiteralOrigin && Other.count(Root) && (Mut || Exclusive))
                error(Construct, "constructor fields alias an exclusive borrow");
          Fields.emplace_back(Part, Mut);
          Result.insert(Part.begin(), Part.end());
        }
      }
      // A constructor body may populate a member after its empty initializer.
      // Its declared class region still binds the result to these arguments.
#ifdef MODULE_SAFETY_BUILTIN
      for (auto *Field : Ctor->getParent()->fields())
        if (unsigned Region = fieldClassRegion(Field))
          for (unsigned I = 0;
               I < Ctor->getNumParams() && I < Construct->getNumArgs(); ++I) {
            auto *P = Ctor->getParamDecl(I);
            unsigned Source = constructorParameterRegion(P, Ctor->getParent(), Ctor);
            if (!Source || !circleClassRegionOutlives(Ctor->getParent(), Source, Region))
              continue;
            auto Part = referenceRoots(Construct->getArg(I), P->getType(), S);
            if (Part.empty()) return {};
            Result.insert(Part.begin(), Part.end());
          }
#endif
      // A phantom lifetime field has no physical initializer. Its region is
      // bound by the constructor arguments that carry the same lifetime, so
      // that is where a result constructed from those arguments borrows from.
      if (Result.empty() &&
          modulesafety::hasPhantomLifetimeFields(Construct->getType())) {
        for (unsigned I = 0;
             I < Ctor->getNumParams() && I < Construct->getNumArgs(); ++I) {
          auto *P = Ctor->getParamDecl(I);
          if (!P->getType()->isReferenceType() && !objectBorrow(P->getType()))
            continue;
          auto Part = referenceRoots(Construct->getArg(I), P->getType(), S);
          Result.insert(Part.begin(), Part.end());
        }
      }
      return Result;
    }
    if (auto *Call = dyn_cast<CallExpr>(E)) {
      const FunctionDecl *Callee = callCallee(Call);
      if (!Callee) Callee = modulesafety::indirectMemberCallee(Call);
#ifdef MODULE_SAFETY_BUILTIN
      if (Callee && Callee->getIdentifier() &&
          Callee->getIdentifier()->getName() == "__slice_pointer" &&
          Call->getNumArgs())
        return rawPointerRoots(Call->getArg(0), S);
      if (!Callee) {
        if (auto *FT = callPrototype(Call)) {
          if (unsigned ID = circleFunctionRegion(FT, 0); circleRegionIsCapture(ID))
            return callableRegionRoots(Call->getCallee(), ID, S);
          if (FT->getReturnBorrowClassRegion()) {
            Vars Result;
            for (auto I : FT->getReturnBorrowSources()) {
              if (I >= Call->getNumArgs()) return {};
              auto Part = classRegionRoots(Call->getArg(I), circleClassRecord(FT->getParamType(I)),
                                           FT->getReturnBorrowClassRegion(), S);
              if (Part.empty()) return {};
              Result.insert(Part.begin(), Part.end());
            }
            return Result;
          }
          if (FT->hasGenerativeReturnLifetime()) return generativeCallRoots(Call, FT, S);
          if (FT->getReturnBorrow() == 0x40000000u)
            // Keep the concrete permanent origin when the body is visible.
            // A literal operator's result must stay a literal rather than
            // becoming the opaque mutable-static sentinel.
            return Callee ? staticCallRoots(Call, Callee, S)
                          : Vars{StaticOrigin};
          auto Sources = FT->getReturnBorrowSources();
          std::set<unsigned> Regions(Sources.begin(), Sources.end());
          Vars Result;
          for (auto I : Regions) {
            if (I >= Call->getNumArgs())
              return {};
            auto Part = argumentResultRoots(Call->getArg(I), FT, I, S);
            if (Part.empty())
              return {};
            Result.insert(Part.begin(), Part.end());
          }
          if (!Regions.empty())
            return Result;
        }
      }
#endif
      if (Callee) {
#ifdef MODULE_SAFETY_BUILTIN
        if (unsigned Region = storedClassResultRegion(Callee)) {
          unsigned Offset = isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee) ? 1u : 0u;
          Vars Result;
          for (auto I : borrowedParameters(Callee)) {
            if (I + Offset >= Call->getNumArgs()) return {};
            auto Part = classRegionRoots(Call->getArg(I + Offset),
                    circleClassRecord(Callee->getParamDecl(I)->getType()), Region, S);
            if (Part.empty()) return {};
            Result.insert(Part.begin(), Part.end());
          }
          return Result;
        }
#endif
#ifdef MODULE_SAFETY_BUILTIN
        if (modulesafety::returnsGenerative(Callee))
          return generativeCallRoots(Call, callPrototype(Call), S);
#endif
        if (modulesafety::returnsStatic(Callee) ||
            hasStaticLifetimeFields(Callee->getReturnType())
#ifdef MODULE_SAFETY_BUILTIN
            || circleClassHasStaticArguments(Callee->getReturnType())
#endif
            )
          return staticCallRoots(Call, Callee, S);
#ifdef MODULE_SAFETY_BUILTIN
        // A choice returned by an explicit object method can carry a payload
        // borrowed through the class's lifetime parameter. The receiver's
        // phantom field records that region; the receiver's own storage is
        // not part of the payload's lifetime.
        if (auto *Method = dyn_cast<CXXMethodDecl>(Callee);
            Method && Method->isExplicitObjectMemberFunction() &&
            objectBorrow(Method->getReturnType()) &&
            projectedLifetimeRecord(Method->getReturnType()) && Call->getNumArgs()) {
          if (Vars R = receiverPhantomRoots(Call->getArg(0), S); !R.empty())
            return R;
          // A choice result whose payload borrows through the receiver does
          // not need a phantom field when the receiver's own loan is the
          // source of the projection (for example `optional<ref>` from
          // `ref_cell::try_borrow`).
          if (Vars R = receiverRoots(Call->getArg(0), S); !R.empty())
            return R;
        }
#endif
        unsigned Offset =
            isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee) ? 1u : 0u;
        if (marked(Callee, "safecpp.borrow.this")) {
          if (auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
            return receiverRoots(Member->getImplicitObjectArgument(), S);
          if (Offset && Call->getNumArgs())
            return receiverRoots(Call->getArg(0), S);
        }
        auto Regions = borrowedParameters(Callee);
        Vars Result;
        for (auto I : Regions) {
          if (I + Offset >= Call->getNumArgs())
            return {};
          auto Part = argumentResultRoots(Call->getArg(I + Offset),
              Callee->getType()->getAs<FunctionProtoType>(), I, S);
          if (Part.empty())
            return {};
          Result.insert(Part.begin(), Part.end());
        }
        if (!Regions.empty())
          return Result;
      }
    }
    return {};
  }
  Vars directMatchBindingRoots(const Expr *E, const State &S) {
    if (!E) return {};
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      return directMatchBindingRoots(Cleanup->getSubExpr(), S);
    if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E))
      return directMatchBindingRoots(Bound->getSubExpr(), S);
    if (auto *Statement = dyn_cast<StmtExpr>(E))
      if (auto *Body = Statement->getSubStmt())
        if (auto *Last = dyn_cast_or_null<Expr>(Body->body_back()))
          return directMatchBindingRoots(Last, S);
    if (auto *Choice = dyn_cast<ConditionalOperator>(E)) {
      if (cannotReturn(Choice->getFalseExpr()))
        return directMatchBindingRoots(Choice->getTrueExpr(), S);
      if (cannotReturn(Choice->getTrueExpr()))
        return directMatchBindingRoots(Choice->getFalseExpr(), S);
      auto L = directMatchBindingRoots(Choice->getTrueExpr(), S);
      auto R = directMatchBindingRoots(Choice->getFalseExpr(), S);
      if (L.empty() || R.empty()) return {};
      L.insert(R.begin(), R.end());
      return L;
    }
    if (auto *U = dyn_cast<UnaryOperator>(E)) {
      if (U->getOpcode() == UO_Deref || U->getOpcode() == UO_Extension ||
          nativeBorrow(U) || nativeRelocation(U))
        return directMatchBindingRoots(U->getSubExpr(), S);
    }
    if (auto *V = variable(E);
        V && marked(V, "safecpp.native.match.binding")) {
      if (auto I = S.Loans.find(V);
          I != S.Loans.end() && !I->second.Roots.empty())
        return canonicalRegions(I->second.Roots, S);
      if (auto I = MatchOrigins.find(V);
          I != MatchOrigins.end() && !I->second.empty())
        return canonicalRegions(I->second, S);
      if (V->hasInit()) {
        State Fallback = S;
        Fallback.Moved.clear();
        Fallback.Relocated.clear();
        auto R = expressionRoots(V->getInit(), Fallback);
        resolveMatchStorage(R, Fallback);
        return R;
      }
    }
    return {};
  }
  Vars addressStorageRoots(const Expr *E, const State &S) {
    if (!E) return {};
    E = evaluationSource(E->IgnoreParenImpCasts());
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E))
      return addressStorageRoots(Cleanup->getSubExpr(), S);
    if (auto *Cast = dyn_cast<CastExpr>(E))
      return addressStorageRoots(Cast->getSubExpr(), S);
    if (auto *Default = dyn_cast<CXXDefaultArgExpr>(E))
      return addressStorageRoots(Default->getExpr(), S);
    if (auto *Default = dyn_cast<CXXDefaultInitExpr>(E))
      return addressStorageRoots(Default->getExpr(), S);
    if (auto *Binary = dyn_cast<BinaryOperator>(E)) {
      if (Binary->getOpcode() == BO_Comma)
        return addressStorageRoots(Binary->getRHS(), S);
      if (Binary->isAssignmentOp())
        return addressStorageRoots(Binary->getLHS(), S);
    }
    if (auto *Conditional = dyn_cast<AbstractConditionalOperator>(E)) {
      auto Left = addressStorageRoots(Conditional->getTrueExpr(), S);
      auto Right = addressStorageRoots(Conditional->getFalseExpr(), S);
      if (Left.empty() && cannotReturn(Conditional->getTrueExpr())) return Right;
      if (Right.empty() && cannotReturn(Conditional->getFalseExpr())) return Left;
      if (Left.empty() || Right.empty()) return {};
      Left.insert(Right.begin(), Right.end());
      return Left;
    }
    if (auto *Statement = dyn_cast<StmtExpr>(E))
      if (auto *Body = Statement->getSubStmt(); !Body->body_empty())
        return addressStorageRoots(dyn_cast<Expr>(Body->body_back()), S);
#ifdef MODULE_SAFETY_BUILTIN
    if (isa<DeclRefExpr>(E) && E->getType()->getAs<BorrowValueType>())
      if (auto *Handle = fieldOrigin(variable(E), {})) return {Handle};
#endif
    return storageRoots(E, S);
  }
  Vars storageRoots(const Expr *E, const State &S) {
    if (!E) return {};
    if (ThisOrigin && isa<CXXConstructorDecl>(F))
      if (auto *Member = dyn_cast<MemberExpr>(borrowedPlace(E));
          Member && isa<CXXThisExpr>(Member->getBase()->IgnoreParenImpCasts()))
        if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
            Field && fieldClassRegion(Field)) {
          if (auto *Place = fieldOrigin(ThisOrigin, {Field})) return {Place};
          return {ThisOrigin};
        }
    const Expr *Place = evaluationSource(E->IgnoreParenImpCasts());
    if (const auto *Deref = dyn_cast<UnaryOperator>(Place);
        Deref && nativeBorrowDereference(Deref))
      return expressionRoots(Deref->getSubExpr(), S);
    if (const auto *Member = dyn_cast<MemberExpr>(Place))
      if (const auto *Deref = dyn_cast<UnaryOperator>(Member->getBase()->IgnoreParenImpCasts());
          Deref && nativeBorrowDereference(Deref))
        return storageRoots(Member->getBase(), S);
    if (auto *V = variable(E)) {
      if (!V->getType()->isReferenceType()) {
        auto Path = ownedFieldPath(E);
        if (!Path.empty() && fieldOrigin(V, Path)) return ownedPlaces(V, Path);
        auto Places = ownedPlaces(V);
#ifdef MODULE_SAFETY_BUILTIN
        // Receiver/storage access follows the existing borrow relationship.
        // Only taking the handle's address adds its separate local storage;
        // including it here would contaminate pointee-return summaries.
        if (V->getType()->getAs<BorrowValueType>())
          if (auto *Handle = fieldOrigin(V, {})) Places.erase(Handle);
#endif
        return Places;
      }
      auto R = roots(V, S);
      Vars Exact;
      for (auto *Root : R)
        if (C.hasSameType(Root->getType().getNonReferenceType().getUnqualifiedType(),
                          V->getType().getNonReferenceType().getUnqualifiedType()))
          Exact.insert(Root);
      return Exact.empty() ? R : Exact;
    }
    return expressionRoots(E, S);
  }
  Vars borrowStorageRoots(const Expr *E, const State &S, unsigned Depth = 0) {
    if (!E || Depth > 64) return {};
    E = evaluationSource(E->IgnoreParens());
    auto Next = [&](const Expr *Value) { return borrowStorageRoots(Value, S, Depth + 1); };
    if (auto *Cast = dyn_cast<CastExpr>(E)) {
      if (isa<ImplicitCastExpr>(Cast) || Cast->getCastKind() == CK_NoOp)
        return Next(Cast->getSubExpr());
      return {};
    }
    if (auto *Cleanup = dyn_cast<ExprWithCleanups>(E)) return Next(Cleanup->getSubExpr());
    if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(E)) return Next(Temporary->getSubExpr());
    if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(E)) return Next(Bound->getSubExpr());
    if (auto *Default = dyn_cast<CXXDefaultArgExpr>(E)) return Next(Default->getExpr());
    if (auto *Default = dyn_cast<CXXDefaultInitExpr>(E)) return Next(Default->getExpr());
    if (auto *Unary = dyn_cast<UnaryOperator>(E)) {
      if (nativeBorrow(Unary) || nativeBorrowDereference(Unary) || nativeRelocation(Unary))
        return Next(Unary->getSubExpr());
      return {};
    }
    auto Join = [&](const Expr *Left, const Expr *Right) {
      auto A = Next(Left), B = Next(Right);
      if (A.empty() || B.empty()) return Vars{};
      A.insert(B.begin(), B.end());
      return A;
    };
    if (auto *Choice = dyn_cast<ConditionalOperator>(E))
      return Join(Choice->getTrueExpr(), Choice->getFalseExpr());
    if (auto *Choice = dyn_cast<BinaryConditionalOperator>(E))
      return Join(Choice->getCommon(), Choice->getFalseExpr());
    if (auto *Binary = dyn_cast<BinaryOperator>(E)) {
      if (Binary->getOpcode() == BO_Comma) return Next(Binary->getRHS());
      if (Binary->isAssignmentOp()) return Next(Binary->getLHS());
      return {};
    }
    if (isa<CXXThisExpr>(E)) return ThisOrigin ? ownedPlaces(ThisOrigin) : Vars{};
    if (auto *Member = dyn_cast<MemberExpr>(E)) {
      // Union members overlap and a generated choice switches active payload
      // storage. A record-field summary cannot identify that storage through
      // the union; keep the existing match/union provenance rules instead.
      if (Member->getType()->isUnionType()) return {};
      if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
          Field && Field->getParent()->isUnion()) return {};
      auto Type = Member->getType();
      bool Handle = Type->isReferenceType();
#ifdef MODULE_SAFETY_BUILTIN
      Handle |= bool(Type->getAs<BorrowValueType>());
#endif
      if (Handle) return {}; // Stored record-borrow projections need their own summary.
      if (auto *Owner = variable(E); Owner && !Owner->getType()->isReferenceType()
#ifdef MODULE_SAFETY_BUILTIN
          && !Owner->getType()->getAs<BorrowValueType>()
#endif
          ) {
        auto Path = ownedFieldPath(E);
        if (!Path.empty() && fieldOrigin(Owner, Path)) return ownedPlaces(Owner, Path);
      }
      return Next(Member->getBase());
    }
    if (auto *Ref = dyn_cast<DeclRefExpr>(E)) {
      auto *V = dyn_cast<VarDecl>(Ref->getDecl());
      if (!V) return {};
      bool Handle = V->getType()->isReferenceType();
#ifdef MODULE_SAFETY_BUILTIN
      Handle |= bool(V->getType()->getAs<BorrowValueType>());
#endif
      if (!Handle) return ownedPlaces(V);
      auto I = S.BorrowStorage.find(V);
      return I != S.BorrowStorage.end() ? I->second : Vars{};
    }
#ifdef MODULE_SAFETY_BUILTIN
    if (auto *Call = dyn_cast<CallExpr>(E)) {
      auto *Proto = callPrototype(Call);
      if (!Proto || Proto->getReturnBorrowClassRegion() ||
          (!Call->getType()->getAs<BorrowValueType>() && !Call->isGLValue())) return {};
      auto Sources = Proto->getReturnBorrowSources();
      if (Sources.empty()) return {};
      unsigned Destination = circleFunctionRegion(Proto, 0);
      bool ProjectsData = false;
      circleForEachFunctionRegionSource(Proto, Destination,
          [&](unsigned, unsigned Region) { ProjectsData |= Region != 0; });
      if (ProjectsData) return {};
      unsigned Offset = isa<CXXOperatorCallExpr>(Call) &&
                        implicitObjectMethod(callCallee(Call)) ? 1u : 0u;
      Vars Result;
      for (unsigned I : Sources) {
        if (I >= Proto->getNumParams() || I + Offset >= Call->getNumArgs()) return {};
        auto Parameter = Proto->getParamType(I);
        QualType Referent;
        if (auto *Borrow = Parameter->getAs<BorrowValueType>()) Referent = Borrow->getPointeeType();
        else if (Parameter->isReferenceType()) Referent = Parameter->getPointeeType();
        else return {};
        // An elided legacy source can describe carried data as well as the
        // source's own storage. Only an explicit region graph separates them.
        if (!Destination && objectBorrow(Referent)) return {};
        auto Part = Next(Call->getArg(I + Offset));
        if (Part.empty()) return {};
        Result.insert(Part.begin(), Part.end());
      }
      return Result;
    }
#endif
    return {};
  }
  Loan argumentLoan(const Expr *Value, QualType Type, const State &S) {
    bool Mut = Type->isReferenceType()
        ? (!Type->getPointeeType().isConstQualified() || objectBorrow(Type->getPointeeType(), true))
        : objectBorrow(Type, true);
    Loan Result{indirectBorrowStorage(Type) ? storageRoots(Value, S)
                                          : expressionRoots(Value, S), Mut};
    // Capability refinement must preserve the same user-storage identities
    // as declaration binding. Generated match subjects and bindings end at
    // the arm boundary; they are not owners of the returned borrow.
    resolveMatchStorage(Result.Roots, S);
    if (!Mut) Result.WriteRoots.emplace();
#ifdef MODULE_SAFETY_BUILTIN
    QualType Payload = Type;
    bool Handle = Type->isReferenceType(), MutableStorage = Handle &&
                                            !Type->getPointeeType().isConstQualified();
    if (Handle) Payload = Type->getPointeeType();
    if (const auto *Borrow = Type->getAs<BorrowValueType>()) {
      Handle = true;
      MutableStorage = !C.circleBorrowIsShared(Borrow);
      Payload = Borrow->getPointeeType();
    }
    if (indirectBorrowStorage(Type) || !projectedLifetimeRecord(Payload)) return Result;
    if (auto *Record = Payload->getAsCXXRecordDecl();
        Record && marked(Record, "safecpp.native.choice")) return Result;
    if (Handle && Value->getType()->isPointerType()) return Result;
    auto Storage = Handle ? borrowStorageRoots(Value, S) : Vars{};
    if (Handle && Storage.empty()) return Result;
    FieldLoans Fields;
    if (!projectedPayload(borrowedPlace(Value), Payload, S, Fields) || Fields.empty()) return Result;
    Vars Data, Writes;
    if (MutableStorage) Writes = Storage;
    for (const auto &[Path, L] : Fields) {
      if (L.Roots.empty()) return Result;
      for (auto *Root : L.Roots) {
        Data.insert(Root);
        if (L.exclusiveAt(Root)) Writes.insert(Root);
      }
    }
    // Opaque writes retain a union of possible data origins. A holder whose
    // carried borrows are all shared cannot acquire write permission to those
    // referents merely because its own fields were replaced.
    if (!objectBorrow(Payload, true)) {
      auto Retained = retainedOrigins(Storage, S);
      Data.insert(Retained.begin(), Retained.end());
    }
    for (auto *Root : Result.Roots)
      if (Mut && !Data.count(Root) && !Storage.count(Root)) Writes.insert(Root);
    Result.Roots.insert(Storage.begin(), Storage.end());
    Result.Roots.insert(Data.begin(), Data.end());
    Result.WriteRoots = std::move(Writes);
#endif
    return Result;
  }
  void accessArgument(const Expr *Value, const Loan &L, const Stmt *At, State &S,
                      bool Reinitializes = false) {
    if (auto *V = variable(Value); V && L.WriteRoots)
      access(V, L.Exclusive, At, S, Reinitializes, ownedFieldPath(Value), &*L.WriteRoots, &L.Roots);
    else accessExpression(Value, L.Exclusive, At, S, Reinitializes);
  }
  std::vector<Loan> argumentBorrows(
      const std::vector<std::pair<const Expr *, QualType>> &Values, const Stmt *At, State &S) {
    std::vector<Loan> Arguments;
    for (auto [Value, Type] : Values) {
      if (!Type->isReferenceType() && !objectBorrow(Type)) continue;
      auto L = argumentLoan(Value, Type, S);
      auto *Move = dyn_cast<CXXConstructExpr>(Value->IgnoreParenImpCasts());
      const auto *Transfer = relocation(Value);
      const auto *Source = Transfer ? variable(Transfer->getSubExpr()) : nullptr;
      // The native transfer already checked access/ownership and retired the
      // whole source at its CFG element. Its prvalue carries those loans;
      // checking the flattened roots again would discard their ancestors.
      bool CheckedTransfer = Source && Source->getType()->isRecordType() &&
                             ownsMoveSource(Transfer->getSubExpr()) &&
                             ownedFieldPath(Transfer->getSubExpr()).empty() &&
                             S.Relocated.count(Source);
      if (!CheckedTransfer &&
          !(Move && Move->getConstructor()->isMoveConstructor() && objectBorrow(Move->getType()))) {
        accessArgument(Value, L, At, S);
      }
      for (const auto &Other : Arguments)
        for (auto *Root : L.Roots)
          if (Other.Roots.count(Root) && (L.exclusiveAt(Root) || Other.exclusiveAt(Root))) {
            error(At, "aliased arguments violate exclusive borrowing");
            break;
          }
      Arguments.push_back(std::move(L));
    }
    return Arguments;
  }
  void accessStorage(const Expr *E, const Stmt *At, State &S,
                     bool Initializing = false) {
    if (auto *V = variable(E)) {
      if (!S.Ready.count(V) && !Initializing)
        error(At, "mutation of an uninitialized container");
      if (S.Moved.count(V))
        error(At, "use of a moved container");
    }
    if (auto *V = variable(E)) {
      auto Path = ownedFieldPath(E);
      if (auto I = S.RelocatedFields.find(V); I != S.RelocatedFields.end())
        for (const auto &Missing : I->second)
          if (Path.empty() || prefixPath(Path, Missing) || prefixPath(Missing, Path))
            error(At, "borrow slot lifetime has ended; replacement is required");
    }
    auto R = storageRoots(E, S);
    for (const auto &[Alias, L] : S.Loans) {
      if (Alias == variable(E))
        continue;
      for (auto *Root : R)
        if (L.Roots.count(Root))
          error(At, "container mutation conflicts with a live storage borrow");
    }
  }
  void accessExpression(const Expr *E, bool Write, const Stmt *At, State &S,
                        bool Reinitializes = false) {
#ifdef MODULE_SAFETY_BUILTIN
    // The generated pair has pointer fields rather than borrow fields, but a
    // proven array conversion still accesses through its source loan.
    if (C.isCircleSliceRecord(E->getType()))
      if (auto *Receiver = borrowedReceiver(E)) {
        access(Receiver, Write, At, S, Reinitializes);
        return;
      }
#endif
    if (auto *V = variable(E)) {
      // Writing a subobject does not restore its containing object. Reference
      // fields also survive C++ moves, so assigning a moved borrow-carrying
      // record cannot recreate the provenance that its move transferred.
      Reinitializes &= wholeObject(E) &&
                       !objectBorrow(V->getType().getNonReferenceType());
      if (!Reinitializes && S.Moved.count(V))
        error(At, "use of a moved value");
      access(V, Write, At, S, Reinitializes, ownedFieldPath(E));
    } else if (const VarDecl *Receiver =
                   objectBorrow(E->getType()) &&
                           !E->getType()->isReferenceType()
                       ? borrowedReceiver(E)
                       : nullptr) {
      access(Receiver, Write, At, S);
    } else {
      const Expr *Element = E;
      for (;;) {
        Element = evaluationSource(Element);
        if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Element))
          Element = Cleanup->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Element))
          Element = Temporary->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Bound = dyn_cast<CXXBindTemporaryExpr>(Element))
          Element = Bound->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Cast = dyn_cast<CastExpr>(Element))
          Element = Cast->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Paren = dyn_cast<ParenExpr>(Element))
          Element = Paren->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Unary = dyn_cast<UnaryOperator>(Element);
                 Unary &&
                 (nativeBorrow(Unary) || nativeBorrowDereference(Unary)))
          Element = Unary->getSubExpr()->IgnoreParenImpCasts();
        else if (auto *Comma = dyn_cast<BinaryOperator>(Element);
                 Comma && Comma->getOpcode() == BO_Comma)
          Element = Comma->getRHS()->IgnoreParenImpCasts();
        else
          break;
      }
      // A fresh aggregate has no named loan yet. Access its carried values
      // through their actual source expressions, which retain their parent
      // permissions. Accessing the flattened roots instead would turn a
      // reborrow through `p` into a second independent write to `*p`.
      if (const auto *List = dyn_cast<InitListExpr>(Element);
          List && objectBorrow(List->getType()) &&
          C.hasSameUnqualifiedType(List->getType(), E->getType())) {
        std::vector<std::pair<const Expr *, QualType>> Values;
        if (const auto *Array = C.getAsArrayType(List->getType())) {
          for (const auto *Init : List->inits())
            Values.emplace_back(Init, Array->getElementType());
        } else if (const auto *Record = List->getType()->getAsCXXRecordDecl();
                   Record && Record->hasDefinition() && Record->isAggregate() &&
                   !Record->isUnion() && !Record->getNumBases() &&
                   !Record->hasUserDeclaredDestructor() &&
                   !marked(Record, "safecpp.native.choice")) {
          unsigned I = 0;
          for (const auto *Field : Record->getDefinition()->fields()) {
#ifdef MODULE_SAFETY_BUILTIN
            // Phantom/indirect storage needs its existing whole-value model.
            if (Field->isCirclePhantom()) { Values.clear(); break; }
#endif
            if (I < List->getNumInits())
              Values.emplace_back(List->getInit(I++), Field->getType());
          }
        }
        if (llvm::any_of(Values, [](const auto &Value) {
              return Value.second->isReferenceType() || objectBorrow(Value.second);
            })) {
          // The normal argument checker also checks constituent exclusivity,
          // moved values and expired owners; no root conflict is bypassed.
          argumentBorrows(Values, At, S);
          return;
        }
      }
      const Expr *Object = nullptr;
      if (sequenceStorageBase(Element, Object))
        if (const VarDecl *Owner = variable(Object)) {
          access(Owner, Write, At, S);
          return;
        }
#ifdef MODULE_SAFETY_BUILTIN
      // A slice element read reaches through the slice's data projection.
      // Keep the named slice as the access site so the reborrow is checked
      // against that slice's own loan, not as a second loan on the owner.
      const Expr *Projection = Element;
      if (auto *Index = dyn_cast<ArraySubscriptExpr>(Element))
        Projection = Index->getBase();
      if (const VarDecl *Owner =
              sliceProjectionPlace(Projection, "__circle_data")) {
        access(Owner, Write, At, S);
        return;
      }
#endif
      for (auto *Root : expressionRoots(E, S)) {
        if (!Reinitializes && S.Moved.count(Root))
          error(At, "use of a moved value");
        access(Root, Write, At, S);
      }
    }
  }
  struct Effects {
    Vars Read, Write;
    bool UnknownGlobals = false;
  };
  struct GlobalEffects {
    Vars Written;
    bool Unknown = false;
    // Opaque execution cannot be explained by writes through a borrowed
    // parameter/receiver; distinguish it from those legitimate mutations.
    bool Opaque = false;
  };
  // Traverse the complete reachable call graph for each query. Caching a
  // partially visited recursive graph would lose effects on a cycle.
  GlobalEffects globalEffects(const FunctionDecl *Root) {
    GlobalEffects Result;
    std::vector<const FunctionDecl *> Pending{Root};
    std::set<const FunctionDecl *> Seen;
    while (!Pending.empty()) {
      auto *Fn = Pending.back(); Pending.pop_back();
      if (!Fn) { Result.Unknown = true; Result.Opaque = true; continue; }
      if (!Seen.insert(Fn->getCanonicalDecl()).second) continue;
      if (auto *Method = dyn_cast<CXXMethodDecl>(Fn); Method && Method->isTrivial()) continue;
      if (auto *Dtor = dyn_cast<CXXDestructorDecl>(Fn)) {
        auto AddDrop = [&](QualType T) {
          auto *R = C.getBaseElementType(T)->getAsCXXRecordDecl();
          if (R && R->hasDefinition()) Pending.push_back(R->getDefinition()->getDestructor());
        };
        for (auto *Field : Dtor->getParent()->fields()) AddDrop(Field->getType());
        for (const auto &Base : Dtor->getParent()->bases()) AddDrop(Base.getType());
      }
      if (Fn->getBuiltinID()) {
        bool Indirect = false;
        for (auto *P : Fn->parameters())
          Indirect |= P->getType()->isPointerType() || P->getType()->isReferenceType();
        Result.Unknown |= Indirect;
        Result.Opaque |= Indirect;
        continue;
      }
      const FunctionDecl *Definition = nullptr;
      auto *Body = Fn->hasBody(Definition) ? Definition->getBody() : nullptr;
      if (!Body) {
        Result.Unknown = true;
        // The supported runtime trusts standard allocation/deallocation. A
        // visible replacement body is still traversed and checked below.
        Result.Opaque |= !Fn->isReplaceableGlobalAllocationFunction();
        continue;
      }
      Fn = Definition;
      for (auto *P : Fn->parameters())
        if (auto *Record = P->getType()->getAsCXXRecordDecl(); Record &&
            Record->hasDefinition() && Record->hasNonTrivialDestructor() &&
            Record->isParamDestroyedInCallee()) Pending.push_back(Record->getDestructor());
      class Find : public RecursiveASTVisitor<Find> {
        GlobalEffects &Result;
        std::vector<const FunctionDecl *> &Pending;
        const FunctionDecl *Fn;
        bool localStore(const Expr *E) {
          auto *V = variable(E);
          return V && V->hasLocalStorage() && !V->getType()->isReferenceType() &&
                 V->getDeclContext() == Fn && !V->isInitCapture();
        }
        void store(const Expr *E) {
          if (auto *V = variable(E); V && V->hasGlobalStorage())
            Result.Written.insert(V->getCanonicalDecl());
          else if (!localStore(E)) Result.Unknown = true;
        }
      public:
        Find(GlobalEffects &R, std::vector<const FunctionDecl *> &P, const FunctionDecl *F)
            : Result(R), Pending(P), Fn(F) {}
        bool VisitVarDecl(VarDecl *V) {
          if (V->hasLocalStorage() && !V->getType()->isReferenceType()) {
            auto *Record = Fn->getASTContext().getBaseElementType(V->getType())->getAsCXXRecordDecl();
            if (Record && Record->hasDefinition() && Record->getDefinition()->hasNonTrivialDestructor())
              Pending.push_back(Record->getDefinition()->getDestructor());
          }
          return true;
        }
        bool VisitAsmStmt(AsmStmt *) { Result.Unknown = true; Result.Opaque = true; return true; }
        bool TraverseCXXDefaultArgExpr(CXXDefaultArgExpr *E) { return TraverseStmt(E->getExpr()); }
        bool TraverseCXXDefaultInitExpr(CXXDefaultInitExpr *E) { return TraverseStmt(E->getExpr()); }
        bool VisitDeclRefExpr(DeclRefExpr *E) {
          if (auto *V = dyn_cast<VarDecl>(E->getDecl()); V && V->hasGlobalStorage()) {
            bool Indirect = V->getType()->isPointerType() || V->getType()->isReferenceType();
            Result.Unknown |= Indirect;
            Result.Opaque |= Indirect;
          }
          return true;
        }
        bool VisitCallExpr(CallExpr *E) {
          auto *Callee = E->getDirectCallee();
          if (auto *M = dyn_cast_or_null<CXXMethodDecl>(Callee); M && M->isVirtual()) {
            Result.Unknown = true;
            Result.Opaque = true;
          }
          if (auto *M = dyn_cast_or_null<CXXMethodDecl>(Callee);
              M && M->isImplicitObjectMemberFunction() && (!M->isConst() ||
                objectBorrow(M->getThisType()->getPointeeType(), true) ||
                modulesafety::marked(M, "safecpp.unsafe.mutates.storage"))) {
            if (auto *Member = dyn_cast<CXXMemberCallExpr>(E))
              store(Member->getImplicitObjectArgument());
            else if (auto *Operator = dyn_cast<CXXOperatorCallExpr>(E);
                     Operator && Operator->getNumArgs()) store(Operator->getArg(0));
          }
          Pending.push_back(Callee);
          return true;
        }
        bool VisitCXXConstructExpr(CXXConstructExpr *E) {
          Pending.push_back(E->getConstructor()); return true;
        }
        bool VisitCXXBindTemporaryExpr(CXXBindTemporaryExpr *E) {
          Pending.push_back(E->getTemporary()->getDestructor()); return true;
        }
        bool VisitCXXNewExpr(CXXNewExpr *E) {
          Pending.push_back(E->getOperatorNew()); return true;
        }
        bool VisitCXXDeleteExpr(CXXDeleteExpr *E) {
          Pending.push_back(E->getOperatorDelete()); return true;
        }
        bool VisitBinaryOperator(BinaryOperator *E) {
          if (E->isAssignmentOp()) store(E->getLHS());
          if (BinaryOperator::getOpcodeStr(E->getOpcode()) == ":=")
            if (auto *Record = E->getLHS()->getType()->getAsCXXRecordDecl())
              Pending.push_back(Record->getDestructor());
          return true;
        }
        bool VisitUnaryOperator(UnaryOperator *E) {
          if (E->isIncrementDecrementOp()) store(E->getSubExpr());
          return true;
        }
        bool TraverseLambdaExpr(LambdaExpr *E) {
          for (auto *Init : E->capture_inits()) TraverseStmt(Init);
          return true;
        }
        bool TraverseUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *) { return true; }
        bool TraverseCXXNoexceptExpr(CXXNoexceptExpr *) { return true; }
        bool TraverseExpressionTraitExpr(ExpressionTraitExpr *) { return true; }
      } Visitor(Result, Pending, Fn);
      if (auto *Ctor = dyn_cast<CXXConstructorDecl>(Fn))
        for (auto *Init : Ctor->inits()) Visitor.TraverseStmt(Init->getInit());
      Visitor.TraverseStmt(const_cast<Stmt *>(Body));
    }
    return Result;
  }
  bool mutableGlobal(const VarDecl *V) const {
    // LiteralOrigin names bytes whose value the program cannot change, so no
    // call invalidates a borrow of them. StaticOrigin stays conservative: a
    // `/static` result or static-lifetime field may name mutable permanent
    // storage, and any global write may invalidate that borrow.
    return V && V != LiteralOrigin &&
           V->hasGlobalStorage() &&
           (!V->getType().isConstQualified() || objectBorrow(V->getType(), true));
  }
  void globalCall(const FunctionDecl *Fn, const Stmt *At, const State &S) {
    Vars Borrowed;
    for (const auto &[Alias, Loan] : S.Loans) {
      if (S.Moved.count(Alias) && objectBorrow(Alias->getType())) continue;
      for (auto *Root : Loan.Roots) {
#ifdef MODULE_SAFETY_BUILTIN
        // Instantiating closed code supplies an unbounded capability, not a
        // loan of every mutable global. Once invoked, its data result gets
        // its own ordinary static-origin loan and remains subject to effects.
        if (Root == StaticOrigin) {
          bool CodeOnly = circleIsCallableValue(Alias->getType());
          if (auto I = S.Fields.find(Alias); I != S.Fields.end()) {
            bool Found = false, Data = false;
            for (const auto &[Path, FieldLoan] : I->second)
              if (FieldLoan.Roots.count(Root)) {
                Found = true;
                Data |= Path.empty() || !circleIsCallableValue(Path.back()->getType());
              }
            CodeOnly |= Found && !Data;
          }
          if (CodeOnly) continue;
        }
#endif
        if (mutableGlobal(Root)) Borrowed.insert(Root->getCanonicalDecl());
      }
    }
    if (Borrowed.empty()) return;
    auto Changes = globalEffects(Fn);
    for (auto *Root : Borrowed)
      if (Changes.Unknown || Changes.Written.count(Root) ||
          (Root == StaticOrigin && !Changes.Written.empty()))
        error(At, "call may invalidate a live borrow of mutable global storage");
  }
  Effects effects(const Expr *E, const State &S, bool Calls = false, bool Globals = false) {
    E = evaluationSource(E);
    Effects Result;
    if (!E)
      return Result;
    if (auto *D = dyn_cast<DeclRefExpr>(E)) {
      if (auto *V = variable(D))
        Result.Read = roots(V, S);
      return Result;
    }
    if (isa<UnaryExprOrTypeTraitExpr>(E) || isa<CXXNoexceptExpr>(E) ||
        isa<LambdaExpr>(E))
      return Result;
    for (auto *Child : E->children())
      if (auto *Sub = dyn_cast_or_null<Expr>(Child)) {
        auto Part = effects(Sub, S, Calls, Globals);
        Result.Read.insert(Part.Read.begin(), Part.Read.end());
        Result.Write.insert(Part.Write.begin(), Part.Write.end());
        Result.UnknownGlobals |= Part.UnknownGlobals;
      }
    if (auto *U = dyn_cast<UnaryOperator>(E); U && U->isIncrementDecrementOp()) {
      auto R = roots(variable(U->getSubExpr()), S);
      Result.Write.insert(R.begin(), R.end());
    }
    if (auto *U = dyn_cast<UnaryOperator>(E); U && nativeRelocation(U)) {
      auto R = ownsMoveSource(U->getSubExpr())
                   ? storageRoots(U->getSubExpr(), S)
                   : receiverRoots(U->getSubExpr(), S);
      Result.Write.insert(R.begin(), R.end());
    }
    if (auto *B = dyn_cast<BinaryOperator>(E); B && B->isAssignmentOp()) {
      auto R = roots(variable(B->getLHS()), S);
      Result.Write.insert(R.begin(), R.end());
    }
    if (Calls) {
      if (Globals) {
        const FunctionDecl *Fn = nullptr;
        bool HasCall = false;
        if (auto *Call = dyn_cast<CallExpr>(E)) {
          Fn = Call->getDirectCallee();
          if (!Fn) Fn = modulesafety::indirectMemberCallee(Call);
          HasCall = true;
        }
        if (auto *Ctor = dyn_cast<CXXConstructExpr>(E)) { Fn = Ctor->getConstructor(); HasCall = true; }
        if (HasCall) {
          auto G = globalEffects(Fn);
          Result.Write.insert(G.Written.begin(), G.Written.end());
          Result.UnknownGlobals |= G.Unknown;
        }
      }
      auto Write = [&](const Expr *Value) {
        auto R = receiverRoots(Value, S);
        Result.Write.insert(R.begin(), R.end());
      };
      auto WriteParameter = [&](const Expr *Value, QualType Type) {
        auto L = argumentLoan(Value, Type, S);
        if (L.WriteRoots)
          Result.Write.insert(L.WriteRoots->begin(), L.WriteRoots->end());
        else if (L.Exclusive) Write(Value);
      };
      if (auto *Construct = dyn_cast<CXXConstructExpr>(E);
          Construct &&
          (Construct->getConstructor()->isMoveConstructor() ||
           transferredBorrow(Construct->getConstructor())) &&
          Construct->getNumArgs())
      {
        auto *Value = Construct->getArg(
            transferredBorrow(Construct->getConstructor()).value_or(0));
        if (Construct->getConstructor()->isTrivial() && ownsMoveSource(Value)) {
          auto R = storageRoots(Value, S);
          Result.Write.insert(R.begin(), R.end());
        } else Write(Value);
      }
      if (auto *Call = dyn_cast<CallExpr>(E)) {
        auto *Fn = Call->getDirectCallee();
        if (!Fn) Fn = modulesafety::indirectMemberCallee(Call);
        auto *Proto = callPrototype(Call);
        unsigned Offset =
            isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Fn) ? 1u
                                                                                 : 0u;
        unsigned Count = Fn ? Fn->getNumParams() : Proto ? Proto->getNumParams() : 0u;
        for (unsigned I = 0; I < Count && I + Offset < Call->getNumArgs(); ++I) {
          auto T = Fn ? Fn->getParamDecl(I)->getType() : Proto->getParamType(I);
          if ((T->isReferenceType() && !T->getPointeeType().isConstQualified()) ||
              objectBorrow(T, true))
            WriteParameter(Call->getArg(I + Offset), T);
        }
        if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Fn);
            Method && Method->isImplicitObjectMemberFunction() &&
            (consumingReceiver(Method) || !Method->isConst() ||
             objectBorrow(C.getCanonicalTagType(Method->getParent()), true))) {
          if (auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
            WriteParameter(Member->getImplicitObjectArgument(),
                C.getLValueReferenceType(Method->isConst()
                    ? C.getConstType(C.getCanonicalTagType(Method->getParent()))
                    : QualType(C.getCanonicalTagType(Method->getParent()))));
          else if (Offset && Call->getNumArgs())
            Write(Call->getArg(0));
        }
      }
      if (auto *Construct = dyn_cast<CXXConstructExpr>(E))
        for (unsigned I = 0; I < Construct->getNumArgs() &&
                             I < Construct->getConstructor()->getNumParams(); ++I)
          WriteParameter(Construct->getArg(I), Construct->getConstructor()->getParamDecl(I)->getType());
    }
    return Result;
  }
  // Reference arguments live through the entire call, including evaluation
  // of sibling arguments. A transient reference is not represented by a
  // local VarDecl loan; check these effects explicitly, in either order.
  void ephemeralBorrows(const std::vector<std::pair<const Expr *, QualType>> &Args,
                        const Stmt *At, const State &S,
                        const std::vector<Vars> *Resolved = nullptr,
                        bool Sequenced = false) {
    if (Args.size() < 2) return;
    for (unsigned I = 0; I < Args.size(); ++I) {
      auto [Value, Type] = Args[I];
      if (!Type->isReferenceType() && !objectBorrow(Type))
        continue;
      auto Borrow = Resolved ? (*Resolved)[I] : referenceRoots(Value, Type, S);
      bool Globals = llvm::any_of(Borrow, [&](const VarDecl *Root) { return mutableGlobal(Root); });
      for (unsigned J = 0; J < Args.size(); ++J) {
        if (I == J || (Sequenced && J < I))
          continue;
        auto Changes = effects(Args[J].first, S, true, Globals);
        for (auto *Root : Borrow)
          if (Changes.Write.count(Root) || (mutableGlobal(Root) && Changes.UnknownGlobals))
            error(At, "argument evaluation invalidates a temporary borrow");
      }
    }
  }
  void callArgumentBorrows(const FunctionDecl *Callee,
                          const std::vector<std::pair<const Expr *, QualType>> &Args,
                          const Stmt *At, const State &S) {
    std::optional<GlobalEffects> Changes;
    for (auto [Value, Type] : Args) {
      if (!Type->isReferenceType() && !objectBorrow(Type)) continue;
      auto Borrow = referenceRoots(Value, Type, S);
      // A temporary holder has no extending declaration, but its external
      // loans remain valid only while their owners survive the entire call.
      if (Borrow.empty() && objectBorrow(Type.getNonReferenceType()))
        Borrow = expressionRoots(Value, S);
      const Expr *Place = borrowedPlace(Value);
      auto *Direct = dyn_cast_or_null<DeclRefExpr>(Place);
      auto *Storage = Direct ? dyn_cast<VarDecl>(Direct->getDecl()) : nullptr;
      bool ExclusiveStorage = Type->isReferenceType() &&
          !Type->getPointeeType().isConstQualified() && Storage &&
          !Storage->getType()->isReferenceType() &&
          C.hasSameType(Storage->getType().getUnqualifiedType(),
                        Type.getNonReferenceType().getUnqualifiedType());
      for (auto *Root : Borrow) {
        if (!mutableGlobal(Root)) continue;
        if (!Changes) Changes = globalEffects(Callee);
        bool ThroughStorage = ExclusiveStorage && Root == Storage;
        if (Changes->Written.count(Root->getCanonicalDecl()) ||
            (Root == StaticOrigin && !Changes->Written.empty()) ||
            // Unknown static storage handed to a call for the duration of that
            // call cannot be shown mutable here; string literals are the
            // important case. Recovered mutable origins still fail below, and
            // a live `/static` loan keeps the stricter rule in `globalCall`.
            (Changes->Unknown && Root != StaticOrigin &&
             (!ThroughStorage || Changes->Opaque)))
          error(At, "callee may invalidate a temporary argument borrow of mutable global storage");
      }
    }
  }
  void forgetMutableUnionOrigins(const Expr *Value, QualType Type, State &S) {
    // A mutable borrow-carrying record can change a union through a field,
    // even when the declared parameter/receiver is not itself a union.
    bool ChangesTag = Type->isReferenceType()
        ? ((!Type->getPointeeType().isConstQualified() &&
            Type->getPointeeType()->isUnionType()) ||
           objectBorrow(Type->getPointeeType(), true))
        : objectBorrow(Type, true);
    if (ChangesTag)
      for (auto *Owner : expressionRoots(Value, S))
        S.ActiveUnions.erase(Owner);
  }
  void unsequenced(const Expr *Left, const Expr *Right, const Stmt *At,
                   const State &S) {
    auto A = effects(Left, S), B = effects(Right, S);
    for (auto *V : A.Write)
      if (B.Write.count(V) || B.Read.count(V))
        error(At, "unsequenced modification and access to the same value");
    for (auto *V : B.Write)
      if (A.Read.count(V))
        error(At, "unsequenced modification and access to the same value");
    // A returned reference may outlive its producing call until the sibling
    // operand is evaluated. Calls in that operand can invalidate global
    // storage even when they have no explicit owner argument.
    bool LeftGlobal = llvm::any_of(A.Read, [&](const VarDecl *V) { return mutableGlobal(V); });
    bool RightGlobal = llvm::any_of(B.Read, [&](const VarDecl *V) { return mutableGlobal(V); });
    if (LeftGlobal) {
      auto Changes = effects(Right, S, true, true);
      for (auto *V : A.Read)
        if (mutableGlobal(V) && (Changes.Write.count(V) || Changes.UnknownGlobals))
          error(At, "operand evaluation may invalidate global storage access");
    }
    if (RightGlobal) {
      auto Changes = effects(Left, S, true, true);
      for (auto *V : B.Read)
        if (mutableGlobal(V) && (Changes.Write.count(V) || Changes.UnknownGlobals))
          error(At, "operand evaluation may invalidate global storage access");
    }
  }
  const VarDecl *unionOwner(const Expr *Base, const State &S, bool Report = true) {
    Base = borrowedPlace(Base);
    while (auto *Cast = dyn_cast<CastExpr>(Base)) {
      if (Cast->getCastKind() != CK_NoOp) break;
      Base = borrowedPlace(Cast->getSubExpr());
    }
    if (auto *D = dyn_cast<DeclRefExpr>(Base)) {
      auto *V = dyn_cast<VarDecl>(D->getDecl());
      if (V && V->getType()->isReferenceType()) {
        auto Owners = roots(V, S);
        if (Owners.size() == 1)
          return *Owners.begin();
        if (Report) error(Base, "union reference has ambiguous storage provenance");
        return nullptr;
      }
      return V;
    }
    if (isa<CXXThisExpr>(Base))
      return ThisOrigin;
    if (Report) error(Base, "union member requires a directly tracked storage owner");
    return nullptr;
  }
  const FieldDecl *unionInitialField(const Expr *Init, const State &S) {
    if (!Init)
      return nullptr;
    if (auto *U = relocation(Init)) {
      auto I = S.ActiveUnions.find(variable(U->getSubExpr()));
      return I == S.ActiveUnions.end() ? nullptr : I->second;
    }
    Init = Init->IgnoreParenImpCasts();
    if (auto *List = dyn_cast<InitListExpr>(Init))
      return List->getInitializedFieldInUnion();
    if (auto *Construct = dyn_cast<CXXConstructExpr>(Init)) {
      if ((Construct->getConstructor()->isCopyConstructor() ||
           Construct->getConstructor()->isMoveConstructor()) &&
          Construct->getNumArgs()) {
        auto *Owner = unionOwner(Construct->getArg(0), S, false);
        auto It = S.ActiveUnions.find(Owner);
        return It == S.ActiveUnions.end() ? nullptr : It->second;
      }
      if (auto *Body =
              dyn_cast_or_null<CompoundStmt>(Construct->getConstructor()->getBody());
          Body && !Body->body_empty())
        return nullptr;
      for (auto *Field : Construct->getConstructor()->getParent()->fields())
        if (Field->hasInClassInitializer())
          return Field;
      for (auto *Member : Construct->getConstructor()->inits())
        if (Member->isMemberInitializer())
          return Member->getMember();
    }
    return nullptr;
  }
  void requireUnionMember(const MemberExpr *Member, const Stmt *At, State &S) {
    auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
    if (!Field || !Field->getParent()->isUnion())
      return;
    // A `choice` tracks its active alternative through the tag that every
    // generated match arm tests, so its generated storage is not modelled as
    // a user-written union.
    if (modulesafety::marked(Field->getParent(), "safecpp.native.choice.storage"))
      return;
    auto *Owner = unionOwner(Member->getBase(), S);
    if (!Owner)
      return;
    auto It = S.ActiveUnions.find(Owner);
    auto *Active = It == S.ActiveUnions.end() ? nullptr : It->second;
    if (!Active && Owner->hasGlobalStorage())
      Active = unionInitialField(Owner->getInit(), S);
    if (Active != Field)
      error(At, "union member is not active on every control-flow path");
  }
  bool activatesUnionMember(const MemberExpr *Member) {
    const Expr *Current = Member;
    for (unsigned I = 0; I < 8; ++I) {
      auto Parents = parentNodes(*Current);
      if (Parents.size() != 1)
        break;
      if (auto *Assignment = Parents[0].get<BinaryOperator>())
        return Assignment->getOpcode() == BO_Assign &&
               Assignment->getLHS()->IgnoreParenImpCasts() == Member;
      auto *Next = Parents[0].get<Expr>();
      if (!Next || !isa<ParenExpr, ImplicitCastExpr>(Next))
        break;
      Current = Next;
    }
    return false;
  }
  void expireLoans(const Stmt *At, State &S) {
    auto It = LiveAfter.find(At);
    if (It != LiveAfter.end()) {
      for (auto L = S.Loans.begin(); L != S.Loans.end();) {
        if (!It->second.count(L->first)) L = S.Loans.erase(L); else ++L;
      }
    }
  }
  bool projectedAssignment(const CallExpr *Call, State &S) {
    const auto *Method = dyn_cast_or_null<CXXMethodDecl>(Call->getDirectCallee());
    if (!Method || !(Method->isCopyAssignmentOperator() || Method->isMoveAssignmentOperator())) return false;
    if (!projectedRecord(C.getCanonicalTagType(Method->getParent()))) {
#ifdef MODULE_SAFETY_BUILTIN
      if (C.getLangOpts().CircleBorrowValues &&
          objectBorrow(C.getCanonicalTagType(Method->getParent()))) {
        error(Call, "borrow aggregate assignment requires a projected field effect summary");
        return true;
      }
#endif
      return false;
    }
    if (!Method->isImplicit() || !Method->isDefaulted() || !Method->isTrivial()) {
      error(Call, "custom borrow aggregate assignment requires a field effect summary");
      return true;
    }
    const Expr *Object = nullptr;
    unsigned Offset = 0;
    if (const auto *Operator = dyn_cast<CXXOperatorCallExpr>(Call)) {
      if (Operator->getNumArgs()) Object = Operator->getArg(0);
      Offset = 1;
    } else if (const auto *Member = dyn_cast<CXXMemberCallExpr>(Call))
      Object = Member->getImplicitObjectArgument();
    auto *Target = variable(Object);
    if (!Object || !wholeObject(Object) || !Target || !S.Fields.count(Target) ||
        Call->getNumArgs() <= Offset) {
      error(Call, "aggregate assignment requires a known projected owning object");
      return true;
    }
    accessStorage(Object, Call, S);
    const Expr *Value = Call->getArg(Offset);
#ifdef MODULE_SAFETY_BUILTIN
    if (circleClassHasStaticArguments(Target->getType()))
      staticFieldValue(Value, Call, S);
#endif
    FieldLoans Incoming;
    if (!projectedPayload(Value, Target->getType(), S, Incoming)) {
      error(Call, "assigned aggregate field provenance cannot be established");
      return true;
    }
    bool Moving = Method->isMoveAssignmentOperator();
    if (!Moving && objectBorrow(Target->getType(), true))
      error(Call, "copy assignment duplicates an exclusive field");
    auto *Source = variable(Value);
    if (const auto *U = relocation(Value)) Source = variable(U->getSubExpr());
    for (const auto &[Path, Borrow] : Incoming) {
      for (const auto &[Alias, Existing] : S.Loans) {
        if (Alias == Target || Alias == Source || S.Moved.count(Alias)) continue;
        for (auto *Root : Borrow.Roots)
          if (Existing.Roots.count(Root) && (Borrow.exclusiveAt(Root) || Existing.exclusiveAt(Root)))
            error(Call, "aggregate assignment conflicts with a live borrow");
      }
      for (const auto &[OtherPath, Other] : Incoming)
        if (OtherPath != Path)
          for (auto *Root : Borrow.Roots)
            if (Other.Roots.count(Root) && (Borrow.exclusiveAt(Root) || Other.exclusiveAt(Root)))
              error(Call, "aggregate assignment aliases exclusive fields");
    }
#ifdef MODULE_SAFETY_BUILTIN
    rememberCallableFields(Target, Value, Target->getType(), S);
#endif
    if (Moving && Source && Source != Target) {
      if (!ownsMoveSource(Value)) error(Call, "aggregate move assignment requires ownership");
      const Expr *Place = Value;
      if (const auto *U = relocation(Value)) Place = U->getSubExpr();
      auto Path = ownedFieldPath(Place);
      if (!Path.empty() && S.Fields.count(Source))
        retireFields(Source, Path, S);
      else {
        S.Moved.insert(Source);
        S.Loans.erase(Source);
      }
    }
    S.Fields[Target] = std::move(Incoming);
    refreshFields(Target, S);
    return true;
  }
  void statement(const Stmt *At, State &S) {
    if (auto I = Context.SliceIndices.find(At); I != Context.SliceIndices.end())
      for (const auto &[Base, Index] : I->second) {
        auto R = expressionRoots(Base, S);
        if (auto *Receiver = variable(Base)) R.insert(Receiver);
        auto Changes = effects(Index, S, true, true);
        for (auto *Root : R)
          if (Changes.Write.count(Root) ||
              (mutableGlobal(Root) && Changes.UnknownGlobals))
            error(At, "slice index evaluation may invalidate the captured slice loan");
      }
#ifdef MODULE_SAFETY_BUILTIN
    if (const auto *B = dyn_cast<BinaryOperator>(At);
        B && (B->isAssignmentOp() || BinaryOperator::getOpcodeStr(B->getOpcode()) == ":=") &&
        B->getLHS()->getType()->getAs<BorrowValueType>() &&
        isa<DeclRefExpr>(B->getLHS()->IgnoreParenImpCasts()))
      if (const auto *V = variable(B->getLHS()); V && staticBorrowVariable(V))
        staticFieldValue(B->getRHS(), At, S, true);
    if (C.getLangOpts().CircleBorrowValues) {
      if (const auto *U = dyn_cast<UnaryOperator>(At)) {
        if (const auto *V = variable(U->getSubExpr()); V && V->getType()->isPointerType()) {
          if (U->getOpcode() == UO_AddrOf) S.EscapedPointerSlots.insert(V);
          if (U->isIncrementDecrementOp()) S.RawPointers[V].clear();
        }
      }
      if (const auto *B = dyn_cast<BinaryOperator>(At); B && B->isAssignmentOp())
        if (isa<DeclRefExpr>(B->getLHS()->IgnoreParenImpCasts()))
          if (const auto *V = variable(B->getLHS()); V && V->getType()->isPointerType())
            S.RawPointers[V] = B->getOpcode() == BO_Assign
                ? rawPointerRoots(B->getRHS(), S) : Vars{};
      if (const auto *Delete = dyn_cast<CXXDeleteExpr>(At)) {
        auto R = rawPointerRoots(Delete->getArgument(), S);
        S.InvalidRawRoots.insert(R.begin(), R.end());
      }
      if (const auto *Call = dyn_cast<CallExpr>(At)) {
        auto *Proto = callPrototype(Call);
        if (Proto && Proto->hasGenerativeReturnLifetime()) {
          auto R = generativeCallRoots(Call, Proto, S);
          if (R.empty()) contractError(At, "generative raw call requires known live pointer provenance");
#ifdef MODULE_SAFETY_BUILTIN
          // A slice result carries the extent its construction named. Where a
          // checked callee hands that extent to its callers, this call has to
          // place it: the data pointer and length of one existing slice, or a
          // counted suffix of a known array. A call whose callee is not visible
          // here cannot show the pair, so its slice result stays refused. In
          // unchecked code the caller makes the claim itself, and the checks
          // below are reported through the region-suppressed path.
          if (!C.circleSliceElement(Proto->getReturnType()).isNull()) {
            const FunctionDecl *Decl = Call->getDirectCallee();
            const InitListExpr *Slice = returnedRawSliceOf(Decl);
            if (!Decl)
              error(At, "slice extent of an indirect call must be placed at the "
                        "call site");
            // A construction whose extent the callee placed itself needs
            // nothing here; one that takes the extent from its parameters
            // leaves the call to place it.
            else if (Slice && !placeableRawExtent(Slice->getInit(0),
                                                  Slice->getInit(1), S)) {
              unsigned Pointer = 0, Count = 0;
              if (!rawSliceExtentParameters(Decl, Pointer, Count) ||
                  Pointer >= Call->getNumArgs() || Count >= Call->getNumArgs() ||
                  !placeableRawExtent(Call->getArg(Pointer),
                                      Call->getArg(Count), S))
                error(At, "slice extent must be the length of a slice or a counted "
                          "suffix of a known array");
            }
          }
#endif
          bool Exclusive = objectBorrow(Proto->getReturnType(), true);
          const VarDecl *Receiver = nullptr;
          if (auto *Method = dyn_cast<CXXMethodDecl>(F);
              Method && Method->isExplicitObjectMemberFunction() &&
              Method->getNumParams())
            Receiver = Method->getParamDecl(0);
          else if (ThisOrigin)
            Receiver = ThisOrigin;
          for (const auto &[Alias, Existing] : S.Loans) {
            if (Alias == Receiver && (!Exclusive || Existing.Exclusive))
              continue;
            // The call's own pointer inputs are the source of the generative
            // result. Reborrowing that region is not a conflict with the loan
            // it was derived from; an independent alias would already have
            // conflicted when it was formed.
            if (Existing.Roots == R && referencesVar(Call, Alias))
              continue;
            if (!S.Moved.count(Alias) || !objectBorrow(Alias->getType()))
              for (auto *Root : R)
                if (Existing.Roots.count(Root) && (Exclusive || Existing.exclusiveAt(Root)))
                  contractError(At, "generative raw call conflicts with a live borrow");
          }
        } else {
          // A raw pointer supplied to an opaque operation may be freed or
          // otherwise invalidate its referent. Copied aliases lose the proof.
          for (const auto *Arg : Call->arguments())
            if (Arg->getType()->isPointerType() && !Arg->getType()->getPointeeType()->isFunctionType()) {
              auto R = rawPointerRoots(Arg, S);
              auto Pointee = Arg->getType()->getPointeeType();
              if (R.empty() || Pointee->isVoidType() || Pointee->isPointerType() ||
                  Pointee->isRecordType()) {
                // An opaque pointer graph may reach a copied pointer's
                // referent, not just the address of its current holder.
                R.insert(ExternalPointerRoots.begin(), ExternalPointerRoots.end());
                for (const auto &[Pointer, Origins] : S.RawPointers)
                  R.insert(Origins.begin(), Origins.end());
              }
              for (auto *Root : R)
                // Literal bytes have static storage and no safe write path, so
                // an opaque call cannot invalidate them.
                if (Root != LiteralOrigin) S.InvalidRawRoots.insert(Root);
            }
        }
      }
    }
    if (const auto *Cast = dyn_cast<CastExpr>(At);
        Cast && circleClassHasStaticArguments(Cast->getType()))
      staticFieldValue(Cast->getSubExpr(), At, S);
#endif
    if (auto *List = dyn_cast<InitListExpr>(At);
        List && hasStaticLifetimeFields(List->getType())) {
      auto *Record = List->getType()->getAsCXXRecordDecl()->getDefinition();
      unsigned I = Record->getNumBases();
      for (auto *Field : Record->fields()) {
#ifdef MODULE_SAFETY_BUILTIN
        if (Field->isCirclePhantom()) continue;
#endif
        if (staticLifetimeField(Field)) {
          if (I < List->getNumInits()) staticFieldValue(List->getInit(I), At, S);
          else contractError(At, "static field requires an initialized permanent borrow");
        }
        ++I;
      }
    }
    if (auto *Cast = dyn_cast<CastExpr>(At);
        Cast && hasStaticLifetimeFields(Cast->getType()) &&
        !C.hasSameUnqualifiedType(Cast->getType(), Cast->getSubExpr()->getType())) {
#ifdef MODULE_SAFETY_BUILTIN
      if (isa<ImplicitCastExpr>(Cast) && Cast->getCastKind() == CK_NoOp &&
          C.circleSliceField(Cast->getSubExpr()->getType(), false))
        staticFieldValue(Cast->getSubExpr(), At, S);
      else
#endif
        contractError(At, "static field representation cast is not modeled");
    }
    if (auto *B = dyn_cast<BinaryOperator>(At);
        B && (B->isAssignmentOp() || BinaryOperator::getOpcodeStr(B->getOpcode()) == ":="))
      if (auto *Member = dyn_cast<MemberExpr>(B->getLHS()->IgnoreParenImpCasts());
          Member && staticLifetimeField(dyn_cast<FieldDecl>(Member->getMemberDecl())) &&
          !B->getRHS()->getType()->isVoidType())
        staticFieldValue(B->getRHS(), At, S);
    if (auto *B = dyn_cast<BinaryOperator>(At);
        B && (B->isAssignmentOp() || BinaryOperator::getOpcodeStr(B->getOpcode()) == ":="))
      if (auto *Member = dyn_cast<MemberExpr>(B->getLHS()->IgnoreParenImpCasts());
          Member && isa<FieldDecl>(Member->getMemberDecl()) &&
          (fieldClassRegion(cast<FieldDecl>(Member->getMemberDecl())) ||
           nativeCallableValue(B->getLHS()->getType())) &&
          objectBorrow(B->getLHS()->getType()) && !B->getRHS()->getType()->isVoidType())
        classFieldValue(cast<FieldDecl>(Member->getMemberDecl()), B->getRHS(),
                        Member->getBase(), At, S);
    if (auto *E = dyn_cast<Expr>(At); E && ThisOrigin &&
        S.Moved.count(ThisOrigin) && expressionRoots(E, S).count(ThisOrigin))
      error(At, "use of a moved receiver");
    if (auto *Handler = dyn_cast<CXXCatchStmt>(At))
      if (auto *V = Handler->getExceptionDecl()) {
        S.Ready.insert(V);
        S.Moved.erase(V);
        if (V->getType()->isReferenceType())
          S.Loans[V] = {{V}, !V->getType()->getPointeeType().isConstQualified()};
      }
    if (auto *D = dyn_cast<DeclStmt>(At)) {
      for (auto *Item : D->decls())
        if (auto *V = dyn_cast<VarDecl>(Item)) {
          bool Deferred = marked(V, "safecpp.deferred.init");
          if (!Deferred && (V->hasInit() || V->hasGlobalStorage()))
            S.Ready.insert(V);
          else
            S.Ready.erase(V);
          S.Moved.erase(V);
          S.Relocated.erase(V);
          S.RelocatedFields.erase(V);
          initializeFields(V, S);
          if (V->hasInit() && staticBorrowVariable(V)) staticFieldValue(V->getInit(), At, S, true);
#ifdef MODULE_SAFETY_BUILTIN
          if (C.getLangOpts().CircleBorrowValues && V->getType()->isPointerType())
            S.RawPointers[V] = V->hasInit() ? rawPointerRoots(V->getInit(), S) : Vars{};
#endif
          if (Deferred)
            for (auto *Place : ownedPlaces(V)) S.Relocated.insert(Place);
          const VarDecl *IndirectTransfer = nullptr;
          if (V->hasInit() && indirectBorrowStorage(V->getType())) {
            const Expr *Init = V->getInit()->IgnoreParenImpCasts();
            if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Init))
              Init = Cleanup->getSubExpr()->IgnoreParenImpCasts();
            if (auto *Construct = dyn_cast<CXXConstructExpr>(Init);
                Construct && Construct->getConstructor()->isMoveConstructor() &&
                Construct->getNumArgs())
              IndirectTransfer = variable(Construct->getArg(0));
            if (auto *Move = relocation(Init))
              IndirectTransfer = variable(Move->getSubExpr());
            if (!IndirectTransfer)
              if (auto *Move = relocation(V->getInit()))
                IndirectTransfer = variable(Move->getSubExpr());
          }
          if (!Deferred && V->hasInit() && indirectBorrowStorage(V->getType())) {
            auto Origins = expressionRoots(V->getInit(), S);
            Origins.erase(V);
            Origins.erase(IndirectTransfer);
            if (IndirectTransfer)
              for (auto *Place : ownedPlaces(IndirectTransfer))
                Origins.erase(Place);
            if (auto *Move = relocation(V->getInit()))
              Origins.erase(variable(Move->getSubExpr()));
            if (Origins.empty() && emptyIndirectConstruction(V->getInit()))
              Origins.insert(LiteralOrigin);
            S.RetainedBorrows[V] = std::move(Origins);
          }
          if (V->getType()->isUnionType()) {
            S.ActiveUnions.erase(V);
            if (auto *Field = unionInitialField(V->getInit(), S))
              S.ActiveUnions[V] = Field;
          }
          if (!V->getType()->isReferenceType() && objectBorrow(V->getType()) &&
              V->hasInit() && !Deferred) {
#ifdef MODULE_SAFETY_BUILTIN
            if (circleClassHasStaticArguments(V->getType()))
              staticFieldValue(V->getInit(), At, S);
#endif
            auto *SavedTarget = CreationTarget;
            CreationTarget = V;
            auto R = expressionRoots(V->getInit(), S);
            CreationTarget = SavedTarget;
            R.erase(IndirectTransfer);
            if (IndirectTransfer)
              for (auto *Place : ownedPlaces(IndirectTransfer)) R.erase(Place);
            if (indirectBorrowStorage(V->getType()))
              if (auto *Move = relocation(V->getInit()))
                R.erase(variable(Move->getSubExpr()));
            resolveMatchStorage(R, S);
            FieldLoans ProjectedPayload;
            bool HasProjection =
                projectedRecord(V->getType()) &&
                projectedPayload(V->getInit(), V->getType(), S,
                                 ProjectedPayload);
            if (R.empty() && HasProjection)
              for (const auto &[Path, Loan] : ProjectedPayload)
                R.insert(Loan.Roots.begin(), Loan.Roots.end());
            // A `match` pattern binding projects the subject's existing loan.
            // Rebinding the active payload is not a second exclusive borrow of
            // the whole choice, so the subject and its source are ancestors of
            // this loan rather than independent conflicts.
            Vars ProjectionAncestors;
            if (marked(V, "safecpp.native.match.binding"))
              if (auto *Subject = variable(V->getInit());
                  Subject && marked(Subject, "safecpp.native.match.subject")) {
                ProjectionAncestors = parents(Subject, S);
                ProjectionAncestors.insert(Subject);
              }
            if (marked(V, "safecpp.native.match.binding")) {
              if (auto *Subject = matchSubjectBase(V->getInit())) {
                ProjectionAncestors.insert(Subject);
                auto Part = parents(Subject, S);
                ProjectionAncestors.insert(Part.begin(), Part.end());
              }
              ProjectionAncestors.insert(R.begin(), R.end());
            }
            // A generated choice result projected from an explicit object
            // receiver is a reborrow through that receiver's class lifetime.
            // The receiver's own loan is not an independent conflicting
            // borrow, but it still has to stay live while the result is used.
            if (ProjectionAncestors.empty())
              if (auto *Call =
                      dyn_cast<CallExpr>(V->getInit()->IgnoreParenImpCasts());
                  Call && Call->getNumArgs() && projectedRecord(V->getType()))
                if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(
                        Call->getDirectCallee());
                    Method && Method->isExplicitObjectMemberFunction())
                  if (auto *Receiver = variable(Call->getArg(0))) {
                    ProjectionAncestors = parents(Receiver, S);
                    ProjectionAncestors.insert(Receiver);
                  }
            if (R.empty() && marked(V, "safecpp.native.match.binding"))
              if (auto *Rel = relocation(V->getInit()))
                if (auto *Owner = variable(Rel->getSubExpr())) {
                  R = roots(Owner, S);
                  R.erase(Owner);
                }
            bool Exclusive = objectBorrow(V->getType(), true);
            const VarDecl *Transferred = nullptr;
            if (auto *U = relocation(V->getInit()))
              Transferred = variable(U->getSubExpr());
            auto *Receiver = borrowedReceiver(V->getInit());
            auto ValueAncestors = valueParents(V->getInit(), S);
            ProjectionAncestors.insert(ValueAncestors.begin(), ValueAncestors.end());
            if (auto *Construct =
                    dyn_cast<CXXConstructExpr>(V->getInit()->IgnoreParenImpCasts());
                Construct && Construct->getNumArgs()) {
              auto Transfer = transferredBorrow(Construct->getConstructor());
              if (Construct->getConstructor()->isMoveConstructor() || Transfer)
                Transferred = variable(Construct->getArg(Transfer.value_or(0)));
            }
            auto *BorrowedRecord = V->getType()->getAsCXXRecordDecl();
            bool Choice = BorrowedRecord &&
                          marked(BorrowedRecord, "safecpp.native.choice");
            bool PhantomOnly = phantomOnlyBorrow(V->getType());
            if (R.empty() && !Choice && !PhantomOnly)
              error(At, "object borrow provenance cannot be established");
            if (V->hasGlobalStorage())
              for (auto *Root : R)
                if ((Root->hasLocalStorage() && Root != V) ||
                    Root->getTLSKind() != VarDecl::TLS_None)
                  error(At, "global borrow requires a permanent "
                            "non-thread-local owner");
            Loan NewLoan{R, Exclusive, ProjectionAncestors};
            auto Capabilities = argumentLoan(V->getInit(), V->getType(), S);
            NewLoan.WriteRoots = std::move(Capabilities.WriteRoots);
            if (NewLoan.WriteRoots)
              NewLoan.Roots.insert(Capabilities.Roots.begin(), Capabilities.Roots.end());
            for (auto &[Alias, L] : S.Loans) {
              if (Alias == variable(V->getInit()) || Alias == Transferred ||
                  Alias == Receiver ||
                  ProjectionAncestors.count(Alias) ||
                  (S.Moved.count(Alias) && objectBorrow(Alias->getType())))
                continue;
              for (auto *Root : NewLoan.Roots)
                if (L.Roots.count(Root) && (NewLoan.exclusiveAt(Root) || L.exclusiveAt(Root)))
                  error(At, "object borrow conflicts with a live borrow");
            }
            S.BorrowStorage[V] = borrowStorageRoots(V->getInit(), S);
            S.Loans[V] = std::move(NewLoan);
#ifdef MODULE_SAFETY_BUILTIN
            rememberCallableFields(V, V->getInit(), V->getType(), S);
#endif
            if (marked(V, "safecpp.native.match.subject") ||
                marked(V, "safecpp.native.match.binding"))
              MatchOrigins[V] = R;
            if (projectedRecord(V->getType())) {
              if (!HasProjection)
                error(At, "aggregate field provenance cannot be established");
              S.Fields[V] = std::move(ProjectedPayload);
              refreshFields(V, S);
            }
            if (Transferred) {
              const Expr *Value = V->getInit();
              if (const auto *U = relocation(Value)) {
                auto Path = ownedFieldPath(U->getSubExpr());
                if (!Path.empty() && S.Fields.count(Transferred))
                  retireFields(Transferred, Path, S);
                else eraseLoan(Transferred, S);
              } else eraseLoan(Transferred, S);
            }
          }
          if (V->getType()->isReferenceType() && V->hasInit()) {
            auto *Origin = variable(V->getInit());
            auto R = referenceRoots(V->getInit(), V->getType(), S);
            resolveMatchStorage(R, S);
            if (!R.empty()) {
              bool Exclusive = !V->getType()->getPointeeType().isConstQualified() ||
                               objectBorrow(V->getType()->getPointeeType(), true);
              auto Parents = parents(Origin, S);
              if (Origin && (Origin->getType()->isReferenceType() ||
                             objectBorrow(Origin->getType())))
                Parents.insert(Origin);
              // A match binding is a projection of the subject's loan. Its
              // roots are therefore ancestors, not independent borrowers of
              // the same storage.
              if (marked(V, "safecpp.native.match.binding") ||
                  marked(V, "safecpp.native.match.subject")) {
                Parents.insert(R.begin(), R.end());
                if (auto *Subject = matchSubjectBase(V->getInit())) {
                  Parents.insert(Subject);
                  auto Part = parents(Subject, S);
                  Parents.insert(Part.begin(), Part.end());
                }
              }
              Loan NewLoan{R, Exclusive, Parents};
              auto Capabilities = argumentLoan(V->getInit(), V->getType(), S);
              NewLoan.WriteRoots = Capabilities.WriteRoots;
              if (NewLoan.WriteRoots)
                NewLoan.Roots.insert(Capabilities.Roots.begin(), Capabilities.Roots.end());
              for (auto &[Alias, L] : S.Loans) {
                // Re-processing the same declaration on another CFG path
                // replaces its previous loan; it is not a second borrower.
                if (Alias == V || Parents.count(Alias) ||
                    (marked(V, "safecpp.native.match.binding") &&
                     marked(Alias, "safecpp.native.match.binding")))
                  continue;
                for (auto *Root : NewLoan.Roots)
                  if (L.Roots.count(Root) && (NewLoan.exclusiveAt(Root) || L.exclusiveAt(Root)))
                    error(At, "borrow conflicts with a live borrow");
              }
              access(Origin, false, At, S, false, ownedFieldPath(V->getInit()));
              S.BorrowStorage[V] = borrowStorageRoots(V->getInit(), S);
              S.Loans[V] = std::move(NewLoan);
              if (marked(V, "safecpp.native.match.subject") ||
                  marked(V, "safecpp.native.match.binding"))
                MatchOrigins[V] = R;
            } else {
              const Expr *Init = V->getInit();
              // IgnoreParenImpCasts also removes MaterializeTemporaryExpr; keep
              // that node so its extending declaration remains available.
              for (;;) {
                if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Init))
                  Init = Cleanup->getSubExpr();
                else if (auto *Cast = dyn_cast<ImplicitCastExpr>(Init))
                  Init = Cast->getSubExpr();
                else if (auto *Paren = dyn_cast<ParenExpr>(Init))
                  Init = Paren->getSubExpr();
                else
                  break;
              }
              auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Init);
              if (!Temporary || Temporary->getExtendingDecl() != V)
                error(At, "reference provenance cannot be established");
              else
                S.Loans[V] = {{V}, !V->getType()->getPointeeType().isConstQualified()};
            }
          }
        }
    }
    if (auto *Member = dyn_cast<MemberExpr>(At);
        Member && !activatesUnionMember(Member))
      requireUnionMember(Member, At, S);
    if (auto *Cast = dyn_cast<ImplicitCastExpr>(At))
      if (Cast->getCastKind() == CK_LValueToRValue)
        access(variable(Cast->getSubExpr()), false, At, S, false,
               ownedFieldPath(Cast->getSubExpr()));
    if (auto *B = dyn_cast<BinaryOperator>(At)) {
      bool Replace = BinaryOperator::getOpcodeStr(B->getOpcode()) == ":=";
      if (Replace || B->isAssignmentOp()) S.SliceBounds.clear();
      if (Replace) {
        bool DropOnly = B->getRHS()->getType()->isVoidType();
        auto *Target = variable(B->getLHS());
        auto TargetField = ownedFieldPath(B->getLHS());
        auto T = B->getLHS()->getType();
        Vars ReplacementOrigins;
        bool ReplacesIndirectStorage = Target && indirectBorrowStorage(T);
        if (ReplacesIndirectStorage && !DropOnly) {
          ReplacementOrigins = expressionRoots(B->getRHS(), S);
          if (auto *Move = relocation(B->getRHS()))
            for (auto *Place : ownedPlaces(variable(Move->getSubExpr()),
                                          ownedFieldPath(Move->getSubExpr())))
              ReplacementOrigins.erase(Place);
          if (ReplacementOrigins.empty() && emptyIndirectConstruction(B->getRHS()))
            ReplacementOrigins.insert(LiteralOrigin);
        }
        auto Payload = !DropOnly && objectBorrow(T) ? expressionRoots(B->getRHS(), S) : Vars{};
        auto Places = ownedPlaces(Target);
        if (!Target) {
          // A return lifetime bounds possible referents; it does not prove
          // object identity. Choice drop clears the actual target's tag in
          // CodeGen, so conservatively retire every possible origin here.
          // Other records have no such protection against owner cleanup.
          auto Possible = expressionRoots(B->getLHS(), S);
          auto *Record = T->getAsCXXRecordDecl();
          if (!DropOnly || !Record ||
              !marked(Record, "safecpp.native.choice") || Possible.empty())
            error(At, "replacement destination identity cannot be established");
          for (auto *Root : Possible) {
            if (S.Moved.count(Root) || S.Relocated.count(Root))
              error(At, "drop through borrow refers to moved storage");
            auto Owned = ownedPlaces(Root);
            Places.insert(Owned.begin(), Owned.end());
          }
        }
        if (!TargetField.empty()) {
          auto *Origin = fieldOrigin(Target, TargetField);
          Places = Origin ? ownedPlaces(Target, TargetField) : Vars{};
          if (!Origin || !S.Ready.count(Target) || S.Relocated.count(Target) || S.Moved.count(Target))
            error(At, "field replacement requires a live owning parent");
          FieldPath Parent;
          for (unsigned I = 0; I + 1 < TargetField.size(); ++I) {
            Parent.push_back(TargetField[I]);
            auto *ParentOrigin = fieldOrigin(Target, Parent);
            if (!ParentOrigin || !S.Ready.count(ParentOrigin) || S.Moved.count(ParentOrigin) ||
                S.Relocated.count(ParentOrigin)) error(At, "field replacement requires a live owning parent");
          }
        }
        for (auto *Root : Payload)
          if (Places.count(Root)) error(At, "replacement value borrows the destination storage");
        for (const auto &[Alias, Loan] : S.Loans) {
          if (Alias == Target || (S.Moved.count(Alias) && objectBorrow(Alias->getType()))) continue;
          for (auto *Root : Places)
            if (Loan.Roots.count(Root)) error(At, "replacement conflicts with a live storage borrow");
        }
        auto *Record = T->getAsCXXRecordDecl();
        auto *Dtor = Record ? Record->getDestructor() : nullptr;
        if (Dtor && Emit && !Context.Unchecked.count(At)) Check(Dtor, At->getBeginLoc());
        if (Target)
          checkDropBorrows(Dtor, TargetField.empty() ? Target :
                          fieldOrigin(Target, TargetField), At, S);
        if (!Target && Dtor) globalCall(Dtor, At, S);
        if (Target && !S.Relocated.count(Target) && Dtor) {
          State Dropping = S;
          if (!Payload.empty()) {
            auto *Held = ImplicitParamDecl::Create(C, F, At->getBeginLoc(), nullptr, T, ImplicitParamKind::Other);
            Dropping.Loans[Held] = {Payload, objectBorrow(T, true)};
          }
          globalCall(Dtor, At, Dropping);
          if (objectBorrow(T, true)) access(Target, true, At, Dropping);
        }
        if (Target) {
          // Drop the old value with its old dependencies, then install the
          // replacement's carried origins at the actual field or whole owner.
          if (ReplacesIndirectStorage) {
            for (auto *Place : Places) S.RetainedBorrows.erase(Place);
            auto *Storage = TargetField.empty() ? Target : fieldOrigin(Target, TargetField);
            if (Storage && !DropOnly)
              S.RetainedBorrows[Storage] = std::move(ReplacementOrigins);
          }
          for (auto *Place : Places) {
            if (DropOnly) { S.Relocated.insert(Place); S.Moved.insert(Place); S.Ready.erase(Place); }
            else { S.Relocated.erase(Place); S.Moved.erase(Place); S.Ready.insert(Place); }
          }
          if (!TargetField.empty()) {
            if (DropOnly) S.RelocatedFields[Target].insert(TargetField);
            else if (auto I = S.RelocatedFields.find(Target); I != S.RelocatedFields.end()) {
              for (auto P = I->second.begin(); P != I->second.end();)
                if (prefixPath(TargetField, *P)) P = I->second.erase(P); else ++P;
              if (I->second.empty()) S.RelocatedFields.erase(I);
            }
          } else S.RelocatedFields.erase(Target);
          if (TargetField.empty()) S.Loans.erase(Target);
#ifdef MODULE_SAFETY_BUILTIN
          if (DropOnly) {
            if (auto I = S.Callables.find(Target); I != S.Callables.end()) {
              for (auto P = I->second.begin(); P != I->second.end();) {
                if (prefixPath(TargetField, P->first)) P = I->second.erase(P); else ++P;
              }
            }
          } else rememberCallableFields(Target, B->getRHS(), T, S, TargetField);
#endif
          if (!DropOnly && objectBorrow(T)) {
            if (Payload.empty()) error(At, "replacement borrow provenance cannot be established");
            S.Loans[Target] = {Payload, objectBorrow(T, true)};
          }
          if (TargetField.empty()) {
            S.ActiveUnions.erase(Target);
            if (auto *Field = unionInitialField(B->getRHS(), S)) S.ActiveUnions[Target] = Field;
          }
        }
        if (!Target && DropOnly)
          for (auto *Place : Places) {
            S.Relocated.insert(Place);
            S.Moved.insert(Place);
            S.Ready.erase(Place);
          }
      }
      // C++20 sequences assignment, comma, shifts and short-circuit operands.
      // Ordinary arithmetic/comparison/bitwise operands remain unsequenced.
      if (!B->isAssignmentOp() && !B->isShiftOp() && B->getOpcode() != BO_Comma &&
          B->getOpcode() != BO_LAnd && B->getOpcode() != BO_LOr)
        unsequenced(B->getLHS(), B->getRHS(), At, S);
      if (B->isAssignmentOp() && !Replace) {
        auto *V = variable(B->getLHS());
        if (!V) {
          // A write through a borrow reaches the place the borrow names: the
          // place, together with the member path within it, is what decides
          // whether the write revives a value the program moved out.
          const Expr *Written = B->getLHS()->IgnoreParens();
          if (auto *U = dyn_cast<UnaryOperator>(Written);
              U && U->getOpcode() == UO_Deref) {
            const Expr *Borrowed = U->getSubExpr()->IgnoreParens();
            if (const auto *Cast = dyn_cast<ImplicitCastExpr>(Borrowed);
                Cast && Cast->getCastKind() == CK_BitCast)
              Borrowed = Cast->getSubExpr()->IgnoreParens();
            auto Path = ownedFieldPath(Borrowed);
            while (auto *Member = dyn_cast<MemberExpr>(Borrowed->IgnoreParenImpCasts()))
              Borrowed = Member->getBase()->IgnoreParenImpCasts();
            if (auto *Var = variable(Borrowed))
              access(Var, /*Write=*/true, At, S, /*Reinitializes=*/false, Path);
          }
        }
        bool RebindBorrow = false;
        auto TargetPath = ownedFieldPath(B->getLHS());
#ifdef MODULE_SAFETY_BUILTIN
        RebindBorrow = B->getOpcode() == BO_Assign &&
            (B->getLHS()->getType()->getAs<BorrowValueType>() ||
             (nativeCallableValue(B->getLHS()->getType()) &&
              !circleCallableCaptures(B->getLHS()->getType()).empty()));
#endif
        if (RebindBorrow) {
          // Assigning a borrow handle changes its storage and provenance;
          // assigning through *handle changes the referent instead.
          bool Direct = isa<DeclRefExpr>(B->getLHS()->IgnoreParenImpCasts());
          // An element slot reached through a raw pointer is storage the
          // container owns as a whole; the write starts a fresh borrow handle
          // there and there is no projected owner field to update.
          const auto *LHS = B->getLHS()->IgnoreParenImpCasts();
          bool ElementSlot = isa<UnaryOperator>(LHS) &&
                             cast<UnaryOperator>(LHS)->getOpcode() == UO_Deref;
          if ((!V && !ElementSlot) ||
              (V && !Direct && (TargetPath.empty() || !S.Fields.count(V))))
            error(At, "field rebinding requires a known projected owning object");
          // A deferred native borrow slot is initialized by this assignment.
          // Its storage is not a container that must already be live.
          accessStorage(B->getLHS(), At, S, Direct);
          auto R = expressionRoots(B->getRHS(), S);
          bool Exclusive = objectBorrow(B->getLHS()->getType(), true);
          Loan NewLoan{R, Exclusive};
          auto Capabilities = argumentLoan(B->getRHS(), B->getLHS()->getType(), S);
          NewLoan.WriteRoots = Capabilities.WriteRoots;
          if (NewLoan.WriteRoots)
            NewLoan.Roots.insert(Capabilities.Roots.begin(), Capabilities.Roots.end());
          const VarDecl *Transferred = nullptr;
          if (auto *U = relocation(B->getRHS()))
            Transferred = variable(U->getSubExpr());
          if (R.empty()) error(At, "assigned borrow provenance cannot be established");
          auto *Source = variable(B->getRHS());
          auto *Receiver = borrowedReceiver(B->getRHS());
          Vars Ancestors;
          if (Receiver)
            Ancestors.insert(Receiver);
          if (Direct)
            Ancestors = valueParents(B->getRHS(), S);
          for (const auto &[Alias, L] : S.Loans) {
            if (Alias == V || Alias == Source || Alias == Transferred ||
                Alias == Receiver ||
                Ancestors.count(Alias) ||
                (S.Moved.count(Alias) && objectBorrow(Alias->getType())))
              continue;
            for (auto *Root : NewLoan.Roots)
              if (L.Roots.count(Root) && (NewLoan.exclusiveAt(Root) || L.exclusiveAt(Root)))
                error(At, "assigned borrow conflicts with a live borrow");
          }
          if (V && !TargetPath.empty() && S.Fields.count(V)) {
            FieldPath TransferPath;
            if (Transferred == V)
              TransferPath = ownedFieldPath(relocation(B->getRHS())->getSubExpr());
            for (const auto &[Path, L] : S.Fields[V])
              if (Path != TargetPath && Path != TransferPath)
                for (auto *Root : NewLoan.Roots)
                  if (L.Roots.count(Root) && (NewLoan.exclusiveAt(Root) || L.exclusiveAt(Root)))
                    error(At, "field rebinding aliases another exclusive field");
            S.Fields[V][TargetPath] = {R, Exclusive, Ancestors};
            refreshFields(V, S);
          } else if (V) {
            NewLoan.Parents = Ancestors;
            S.BorrowStorage[V] = borrowStorageRoots(B->getRHS(), S);
            S.Loans[V] = std::move(NewLoan);
          }
#ifdef MODULE_SAFETY_BUILTIN
          if (V && nativeCallableValue(B->getLHS()->getType()))
            S.Callables[V][TargetPath] = callableRegions(B->getRHS(), B->getLHS()->getType(), S);
#endif
          if (V && Direct) S.Ready.insert(V);
          if (Transferred) {
            auto SourcePath = ownedFieldPath(relocation(B->getRHS())->getSubExpr());
            if (!SourcePath.empty() && S.Fields.count(Transferred))
              retireFields(Transferred, SourcePath, S);
            else eraseLoan(Transferred, S);
          }
        } else {
        if (B->isCompoundAssignmentOp())
          access(V, false, At, S, false, ownedFieldPath(B->getLHS()));
        bool Whole = wholeObject(B->getLHS());
        access(V, true, At, S, Whole && V &&
               !objectBorrow(V->getType().getNonReferenceType()), ownedFieldPath(B->getLHS()));
        if (auto *Member = dyn_cast<MemberExpr>(B->getLHS()->IgnoreParenImpCasts()))
          if (auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
              Field && Field->getParent()->isUnion())
            if (auto *Owner = unionOwner(Member->getBase(), S)) {
              if (B->getOpcode() == BO_Assign) {
                S.ActiveUnions[Owner] = Field;
                S.Ready.insert(Owner);
              } else
                requireUnionMember(Member, At, S);
            }
        if (Whole && V && !V->getType()->isReferenceType()) {
          restoreFields(V, S);
        }
        }
      }
    }
    if (auto *U = dyn_cast<UnaryOperator>(At)) {
      if (U->isIncrementDecrementOp()) S.SliceBounds.clear();
      if (nativeBorrow(U))
        accessExpression(U->getSubExpr(), false, At, S);
#ifdef MODULE_SAFETY_BUILTIN
      // Reaching a place through a borrow is an access of the place the borrow
      // names, so the borrow's own liveness — and that of the owner its field
      // loans name — is what decides whether the access is still within the
      // referent's lifetime. The dereference is formed on the pointer the
      // borrow is reached through, so that cast is stripped before the place
      // is named: the member path is what carries the loan.
      if (U->getOpcode() == UO_Deref) {
        const Expr *Borrow = U->getSubExpr()->IgnoreParens();
        if (const auto *Cast = dyn_cast<ImplicitCastExpr>(Borrow);
            Cast && Cast->getCastKind() == CK_BitCast)
          Borrow = Cast->getSubExpr()->IgnoreParens();
        if (Borrow->getType()->getAs<BorrowValueType>())
          accessExpression(Borrow, false, At, S);
      }
#endif
      if (nativeRelocation(U)) {
        // The unexpanded pattern of `rel tup.1.[:] ...` names the whole
        // pack field, while each expansion relocates one element. Checking
        // the pattern would retire the entire tuple before the concrete
        // element relocations are visited.
        if (U->getSubExpr()->containsUnexpandedParameterPack())
          return;
        auto *Source = variable(U->getSubExpr());
        auto Field = ownedFieldPath(U->getSubExpr());
        bool BorrowObject = false;
        bool GeneratedMatchBinding =
            Source && marked(Source, "safecpp.native.match.subject");
#ifdef MODULE_SAFETY_BUILTIN
        BorrowObject = U->getSubExpr()->getType()->getAs<BorrowValueType>();
#endif
        if (!GeneratedMatchBinding && !Field.empty() &&
            objectBorrow(U->getType()) && !S.Fields.count(Source))
          error(At, "field relocation requires a known projected owning object");
        if (BorrowObject) {
          // Transferring a handle must validate its referents while the
          // source loan still identifies them. A later argument check sees
          // a prvalue and cannot recover this access through the handle.
          access(Source, false, At, S, false, Field);
          accessStorage(U->getSubExpr(), At, S);
          // Relocating through a borrow spends the borrow: ownership of the
          // referent moves into the relocation's result, so the borrow names
          // nothing the program may reach through this handle again. The
          // referent itself lives on in the new owner.
          // Only a borrow that is the whole place is spent: relocating one
          // member of a borrowed record leaves the borrow of the other members
          // intact.
          if (ownedFieldPath(U->getSubExpr()).empty())
            if (auto *V = variable(U->getSubExpr())) {
              S.Spent.insert(V);
              S.Ready.erase(V);
              S.Moved.insert(V);
            }
        }
        else {
          access(Source, false, At, S, false, Field);
          if (objectBorrow(U->getType()) && ownsMoveSource(U->getSubExpr()))
            accessStorage(U->getSubExpr(), At, S);
          else access(Source, true, At, S, false, Field);
        }
        if (Source) {
          if (!Field.empty()) {
            S.RelocatedFields[Source].insert(Field);
            for (auto *Origin : ownedPlaces(Source, Field)) {
              S.Relocated.insert(Origin);
              S.Moved.insert(Origin);
              S.Ready.erase(Origin);
            }
          }
          else {
            for (auto *Place : ownedPlaces(Source)) {
              S.Relocated.insert(Place);
              S.Moved.insert(Place);
              S.Ready.erase(Place);
            }
          }
        }
      }
      if (U->isIncrementDecrementOp()) {
        access(variable(U->getSubExpr()), false, At, S, false, ownedFieldPath(U->getSubExpr()));
        access(variable(U->getSubExpr()), true, At, S, false, ownedFieldPath(U->getSubExpr()));
      }
    }
    if (auto *E = dyn_cast<CXXConstructExpr>(At)) {
      auto *Ctor = E->getConstructor();
      if (!Ctor->isCopyOrMoveConstructor() && hasClassLifetimeFields(E->getType()))
        for (auto *Field : Ctor->getParent()->fields()) {
          if (!fieldClassRegion(Field)) continue;
          bool Initialized = Field->hasInClassInitializer();
          for (auto *Init : Ctor->inits())
            Initialized |= Init->isMemberInitializer() && Init->getMember() == Field &&
                           !isa<ImplicitValueInitExpr>(Init->getInit());
          if (!Initialized)
            contractError(At, "class field requires an initialized borrow");
        }
      globalCall(E->getConstructor(), At, S);
      std::vector<std::pair<const Expr *, QualType>> Args;
      for (unsigned I = 0;
           I < E->getNumArgs() && I < E->getConstructor()->getNumParams(); ++I)
        Args.emplace_back(E->getArg(I),
                          E->getConstructor()->getParamDecl(I)->getType());
      argumentLifetimeContracts(Ctor->getType()->getAs<FunctionProtoType>(),
                                Args, At, S);
      ephemeralBorrows(Args, At, S);
      callArgumentBorrows(E->getConstructor(), Args, At, S);
      argumentBorrows(Args, At, S);
      // Match ordinary calls: an opaque pointer parameter can designate any
      // union, so a constructor cannot preserve caller activity facts.
      for (auto &[Value, Type] : Args)
        if (Type->isPointerType() && !Type->isFunctionPointerType())
          S.ActiveUnions.clear();
      if (!(E->getConstructor()->isTrivial() &&
            E->getConstructor()->isCopyOrMoveConstructor()))
        for (auto &[Value, Type] : Args)
          forgetMutableUnionOrigins(Value, Type, S);
      auto Transfer = transferredBorrow(E->getConstructor());
      if ((E->getConstructor()->isMoveConstructor() || Transfer) && E->getNumArgs()) {
        if (objectBorrow(E->getType()) && !movedDropSafe(E->getType()))
          error(At, "moving a borrowed object requires a trivial or audited "
                    "moved-from destructor");
        unsigned Index = Transfer.value_or(0);
        if (!ownsMoveSource(E->getArg(Index)))
          error(At, "move construction cannot consume ownership through a borrow");
        auto R = objectBorrow(E->getType()) ? Vars{variable(E->getArg(Index))}
                                            : expressionRoots(E->getArg(Index), S);
        R.erase(nullptr);
        for (auto *V : R) {
          access(V, false, At, S);
          if (E->getConstructor()->isTrivial() && objectBorrow(E->getType()) &&
              ownsMoveSource(E->getArg(Index)))
            accessStorage(E->getArg(Index), At, S);
          else access(V, true, At, S);
        }
        S.Moved.insert(R.begin(), R.end());
      }
      S.SliceBounds.clear();
    }
    if (auto *Call = dyn_cast<CallExpr>(At)) {
      if (projectedAssignment(Call, S)) { expireLoans(At, S); return; }
      auto *Callee = Call->getDirectCallee();
      if (!Callee) Callee = modulesafety::indirectMemberCallee(Call);
      globalCall(Callee, At, S);
      auto *Prototype = callPrototype(Call);
      if (Callee || Prototype) {
        std::vector<std::pair<const Expr *, QualType>> Evaluations;
        unsigned Skip =
            isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee)
                ? 1u
                : 0u;
        unsigned Count = Callee ? Callee->getNumParams() : Prototype->getNumParams();
        for (unsigned I = 0; I < Count && I + Skip < Call->getNumArgs(); ++I)
          Evaluations.emplace_back(Call->getArg(I + Skip),
                                   Callee ? Callee->getParamDecl(I)->getType()
                                          : Prototype->getParamType(I));
        if (auto *Member = dyn_cast<CXXMemberCallExpr>(Call);
            Member && implicitObjectMethod(Callee)) {
          auto *Object = Member->getImplicitObjectArgument();
          auto ObjectType = Object->getType();
          if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee); Method && Method->isConst())
            ObjectType = C.getConstType(ObjectType);
          Evaluations.emplace_back(Object, C.getLValueReferenceType(ObjectType));
        } else if (Skip && Call->getNumArgs()) {
          auto *Object = Call->getArg(0);
          auto ObjectType = Object->getType();
          if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee); Method && Method->isConst())
            ObjectType = C.getConstType(ObjectType);
          Evaluations.emplace_back(Object, C.getLValueReferenceType(ObjectType));
        }
        // Caller arguments are evaluated before the explicit object receiver
        // loan is bound. `receiver^.method(receiver.size())` therefore reads
        // the same object before the mutable call loan begins.
        auto Ephemeral = Evaluations;
        if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee);
            Method && Method->isExplicitObjectMemberFunction() &&
            !Ephemeral.empty())
          Ephemeral.erase(Ephemeral.begin());
        ephemeralBorrows(Ephemeral, At, S);
        argumentLifetimeContracts(Prototype, Evaluations, At, S, Call->getCallee());
        callArgumentBorrows(Callee, Evaluations, At, S);
        // An opaque object pointer can alias any union storage. Forget facts
        // rather than preserving initialization facts across an audited call.
        if (!Context.Generated.count(Call))
          for (unsigned I = 0; I < Count; ++I) {
            auto T = Callee ? Callee->getParamDecl(I)->getType()
                            : Prototype->getParamType(I);
            if (T->isPointerType() && !T->isFunctionPointerType())
              S.ActiveUnions.clear();
          }
        for (unsigned I = 0; I < Count && I + Skip < Call->getNumArgs(); ++I) {
          auto T =
              Callee ? Callee->getParamDecl(I)->getType() : Prototype->getParamType(I);
          auto *Assignment = dyn_cast_or_null<CXXMethodDecl>(Callee);
          if (!(Assignment && Assignment->isTrivial() &&
                (Assignment->isCopyAssignmentOperator() ||
                 Assignment->isMoveAssignmentOperator())))
            forgetMutableUnionOrigins(Call->getArg(I + Skip), T, S);
        }
        unsigned Offset =
            isa<CXXOperatorCallExpr>(Call) && implicitObjectMethod(Callee) ? 1u : 0u;
        auto ArgumentValues = Evaluations;
        if (implicitObjectMethod(Callee) && !ArgumentValues.empty()) ArgumentValues.pop_back();
        auto Arguments = argumentBorrows(ArgumentValues, At, S);
        // A callee may take its receiver as an explicit object parameter — a
        // borrow of the receiver in the checked modes — rather than as the
        // implicit object this block handles. The consuming contract applies
        // to whichever argument names the receiver, and the receiver's own
        // access has already been checked above.
        if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee);
            Method && !Method->isStatic() && !implicitObjectMethod(Method) &&
            modulesafety::marked(Method, "safecpp.native.consumes.receiver") &&
            Call->getNumArgs()) {
          const Expr *Place = borrowedPlace(Call->getArg(0));
          if (auto *Rel = relocation(Place)) Place = Rel->getSubExpr();
          if (auto *Owner = variable(Place)) {
            // The explicit object parameter is the consuming handle. Its
            // borrow fields still name external owners, which remain live.
            S.Ready.erase(Owner);
            S.Moved.insert(Owner);
            for (auto *Part : ownedPlaces(Owner)) {
              S.Ready.erase(Part);
              S.Moved.insert(Part);
            }
          } else
            for (auto *V : expressionRoots(Place, S)) {
              S.Ready.erase(V);
              S.Moved.insert(V);
            }
        }
        if (auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee);
            Method && implicitObjectMethod(Method)) {
          bool StorageOnly =
              modulesafety::marked(Callee, "safecpp.unsafe.mutates.storage");
          bool ReceiverMutates =
              !Method->isConst() ||
              objectBorrow(C.getCanonicalTagType(Method->getParent()), true);
          if (auto *MemberCall = dyn_cast<CXXMemberCallExpr>(Call);
              MemberCall && isa<CXXDestructorDecl>(Method)) {
            const Expr *Destroyed = MemberCall->getImplicitObjectArgument();
            if (auto *V = variable(Destroyed)) {
              FieldPath Path = ownedFieldPath(Destroyed);
              if (!Path.empty() && fieldOrigin(V, Path)) {
                S.RelocatedFields[V].insert(Path);
                for (auto *Place : ownedPlaces(V, Path)) {
                  S.Ready.erase(Place);
                  S.Moved.insert(Place);
                }
              } else {
                S.Ready.erase(V);
                S.Moved.insert(V);
              }
            }
          }
          const Expr *Object = nullptr;
          if (auto *MemberCall = dyn_cast<CXXMemberCallExpr>(Call)) {
            Object = MemberCall->getImplicitObjectArgument();
            if (StorageOnly)
              accessStorage(Object, At, S);
            else
              accessArgument(Object, argumentLoan(Object,
                  C.getLValueReferenceType(Method->isConst()
                      ? C.getConstType(C.getCanonicalTagType(Method->getParent()))
                      : QualType(C.getCanonicalTagType(Method->getParent()))), S), At, S,
                  Method->isCopyAssignmentOperator() || Method->isMoveAssignmentOperator());
          }
          if (auto *Operator = dyn_cast<CXXOperatorCallExpr>(Call);
              Operator && Operator->getNumArgs()) {
            Object = Operator->getArg(0);
            if (StorageOnly)
              accessStorage(Object, At, S);
            else
              accessArgument(Object, argumentLoan(Object,
                  C.getLValueReferenceType(Method->isConst()
                      ? C.getConstType(C.getCanonicalTagType(Method->getParent()))
                      : QualType(C.getCanonicalTagType(Method->getParent()))), S), At, S,
                  Method->isCopyAssignmentOperator() || Method->isMoveAssignmentOperator());
          }
          if (Object) {
            bool Assignment = Method->isCopyAssignmentOperator() ||
                              Method->isMoveAssignmentOperator();
            if (Assignment && Method->getParent()->isUnion() && Method->isTrivial() &&
                Call->getNumArgs() > Offset) {
              auto *Target = unionOwner(Object, S);
              const Expr *Value = Call->getArg(Offset);
              const FieldDecl *Field = unionInitialField(Value, S);
              if (!Field && Value->isGLValue()) {
                auto *Source = unionOwner(Value, S, false);
                auto I = S.ActiveUnions.find(Source);
                if (I != S.ActiveUnions.end()) Field = I->second;
              }
              if (Target) {
                S.ActiveUnions.erase(Target);
                if (Field) S.ActiveUnions[Target] = Field;
                restoreFields(Target, S);
              }
            }
            if (Assignment && wholeObject(Object))
              if (auto *Target = variable(Object);
                  Target && !objectBorrow(Target->getType().getNonReferenceType())) {
                restoreFields(Target, S);
              }
            auto Owners = expressionRoots(Object, S);
            if (ReceiverMutates &&
                !(Method->isTrivial() &&
                  (Method->isCopyAssignmentOperator() ||
                   Method->isMoveAssignmentOperator())))
              for (auto *Owner : Owners)
                S.ActiveUnions.erase(Owner);
            // The callee relocates its receiver, so the caller's object no
            // longer holds a value: naming it again is the use of a moved
            // value, whether the receiver was reached directly or through the
            // exclusive borrow the callee took of it.
            // Only a callee that relocates its receiver ends the caller's
            // ownership here: an ordinary consuming receiver (`&&`) keeps the
            // object alive to its original scope end, which the checks below
            // require to be a safe moved-from destructor.
            if (modulesafety::marked(Method, "safecpp.native.consumes.receiver")) {
              const Expr *Consumed =
                  isa<CXXOperatorCallExpr>(Call)
                      ? (Call->getNumArgs() ? Call->getArg(0) : nullptr)
                      : Object;
              const Expr *Place = borrowedPlace(Consumed);
              if (auto *Rel = relocation(Place)) Place = Rel->getSubExpr();
              if (auto *Owner = variable(Place)) {
                // Consuming a borrow-carrying object moves its handle and
                // owned subobjects, not the external referents the handle
                // names.
                S.Ready.erase(Owner);
                S.Moved.insert(Owner);
                for (auto *Part : ownedPlaces(Owner)) {
                  S.Ready.erase(Part);
                  S.Moved.insert(Part);
                }
              } else
                for (auto *V : expressionRoots(Place, S)) {
                  S.Ready.erase(V);
                  S.Moved.insert(V);
                }
            }
            for (unsigned I : modulesafety::adoptedParameters(Callee))
              if (I + Offset < Call->getNumArgs()) {
                auto From = expressionRoots(Call->getArg(I + Offset), S);
                if (From.empty())
                  contractError(At, "adopted borrow has unknown provenance");
                for (auto *Root : From)
                  if (!Owners.count(Root))
                    contractError(At, "container element borrows outside the "
                                      "declared owner region");
              }
            auto Receiver = argumentLoan(Object,
                C.getLValueReferenceType(Method->isConst()
                    ? C.getConstType(C.getCanonicalTagType(Method->getParent()))
                    : QualType(C.getCanonicalTagType(Method->getParent()))), S);
            auto R = StorageOnly ? storageRoots(Object, S) : Receiver.Roots;
            for (const auto &Other : Arguments)
              for (auto *Root : R)
                if (Other.Roots.count(Root) && (Receiver.exclusiveAt(Root) || Other.exclusiveAt(Root)))
                  error(At, "method receiver aliases an exclusive argument");
            if (consumingReceiver(Method)) {
              // C++ still destroys the receiver at its original scope end.
              // The declaration checker therefore requires moved-drop safety.
              // A borrowed receiver grants access, never ownership transfer.
              auto *Source = variable(Object);
              const Expr *Place = consumingSubobjectPlace(Object);
              FieldPath Path = ownedFieldPath(Place);
              if (!Source && Path.size() && Owners.count(ThisOrigin))
                Source = ThisOrigin;
              bool Whole = wholeObject(Place);
              bool Partial = Source && !Whole && !Path.empty();
              if (Source && Source->getType()->isReferenceType())
                error(At, "consuming receiver cannot consume through a borrow");
              if (Source && !Partial) {
                auto OwnedType = Source->getType().getNonReferenceType();
                if (pinnedStorage(OwnedType))
                  error(At, "consuming receiver cannot consume pinned storage");
                if (!movedDropSafe(OwnedType))
                  error(At, "consuming receiver requires a trivial or audited "
                            "moved-from destructor for the actual owner");
              }
              if (Partial) {
                auto SubType = Path.back()->getType();
                const CXXRecordDecl *Parent =
                    Source->getType().getNonReferenceType()
                        ->getAsCXXRecordDecl();
                bool ParentSafe = true;
                for (const auto *Field : Path) {
                  if (Parent && Parent->hasDefinition() &&
                      (Parent->isUnion() || Parent->getNumBases() ||
                       (Parent->hasUserDeclaredDestructor() &&
                        !marked(Parent, "safecpp.unsafe.moved.drop"))))
                    ParentSafe = false;
                  Parent = Field->getType()->getAsCXXRecordDecl();
                }
                if (!ParentSafe || pinnedStorage(SubType) ||
                    !movedDropSafe(SubType))
                  error(At, "consuming a subobject requires an owned path and "
                            "a trivial or audited moved-from destructor");
              }
              if (Owners.count(ThisOrigin) &&
                  !consumingReceiver(dyn_cast<CXXMethodDecl>(F)))
                error(At, "consuming receiver requires ownership of this");
              if (auto *Ref = dyn_cast<DeclRefExpr>(Place);
                  Ref && Ref->refersToEnclosingVariableOrCapture())
                error(At, "consuming receiver cannot consume through a capture");
              if (Source && Source != ThisOrigin &&
                  (Source->isInitCapture() || !Source->hasLocalStorage() ||
                   Source->getDeclContext() != F))
                error(At, "consuming receiver requires a local owner");
              if (auto *Borrow = dyn_cast<UnaryOperator>(Place);
                  Borrow && nativeBorrow(Borrow))
                error(At, "consuming receiver cannot consume through a borrow");
              auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Place);
              bool OwnsTemporary = Temporary && !Temporary->getExtendingDecl();
              if (!Source && !Owners.count(ThisOrigin) && Object->isGLValue() &&
                  !OwnsTemporary)
                error(At, "consuming receiver has unknown ownership provenance");
              if (Source && !Whole)
                if (!Partial)
                  error(At, "consuming a subobject requires partial-move support");
              if (!Source && Owners.count(ThisOrigin)) {
                auto *Deref = dyn_cast<UnaryOperator>(Place);
                if (!(Deref && Deref->getOpcode() == UO_Deref &&
                      isa<CXXThisExpr>(Deref->getSubExpr()->IgnoreParenImpCasts())) &&
                    !isa<CXXThisExpr>(Place))
                  error(At, "consuming a subobject requires partial-move support");
              }
              if (Partial) {
                access(Source, true, At, S, false, Path);
                S.RelocatedFields[Source].insert(Path);
                for (auto *Origin : ownedPlaces(Source, Path)) {
                  S.Relocated.insert(Origin);
                  S.Moved.insert(Origin);
                  S.Ready.erase(Origin);
                }
              } else {
                // Retire the holder, not the external objects its fields
                // borrow.
                Vars Consumed;
                if (Source) Consumed.insert(Source);
                else if (Owners.count(ThisOrigin)) Consumed.insert(ThisOrigin);
                for (auto *Owner : Consumed) {
                  access(Owner, true, At, S);
                  for (auto *Place : ownedPlaces(Owner)) S.Moved.insert(Place);
                  S.ActiveUnions.erase(Owner);
                }
              }
            }
          }
          if (Method->isMoveAssignmentOperator() && Call->getNumArgs() > Offset) {
            if (!ownsMoveSource(Call->getArg(Offset)))
              error(At, "move assignment cannot consume ownership through a borrow");
            auto R = expressionRoots(Call->getArg(Offset), S);
            for (auto *V : R) {
              access(V, false, At, S);
              access(V, true, At, S);
            }
            S.Moved.insert(R.begin(), R.end());
          }
        }
      }
      retainCallBorrows(Call, S);
      S.SliceBounds.clear();
    }
    if (auto *Return = dyn_cast<ReturnStmt>(At)) {
      if (F->getReturnType()->isReferenceType() || objectBorrow(F->getReturnType()) ||
          indirectBorrowStorage(F->getReturnType())) {
        auto From = borrowedParameters(F);
        auto R = referenceRoots(Return->getRetValue(), F->getReturnType(), S);
        resolveMatchStorage(R, S);
        auto MatchRoots = directMatchBindingRoots(Return->getRetValue(), S);
        if (!MatchRoots.empty())
          R = std::move(MatchRoots);
        bool ThisContract = marked(F, "safecpp.borrow.this") && ThisOrigin;
        const ParmVarDecl *ExplicitSelf = nullptr;
        if (auto *Method = dyn_cast<CXXMethodDecl>(F);
            Method && Method->isExplicitObjectMemberFunction() &&
            Method->getNumParams())
          ExplicitSelf = Method->getParamDecl(0);
        bool StaticContract = modulesafety::returnsStatic(F);
        unsigned ClassRegion = storedClassResultRegion(F);
#ifdef MODULE_SAFETY_BUILTIN
        // A result that carries several regions is verified field by field:
        // every region the result type names must be supplied by the parameter
        // bound to it, so two regions cannot be swapped or merged.
        if (circleIsCallableValue(F->getReturnType())) {
          unsigned Region = 0;
          auto *FT = F->getType()->getAs<FunctionProtoType>();
          for (unsigned Capture : circleCallableCaptures(F->getReturnType())) {
            unsigned Destination = circleProjectedFunctionRegion(FT, 0, ++Region);
            auto Origins = callableRegionRoots(Return->getRetValue(), Capture, S);
            bool Valid = Destination && !Origins.empty();
            for (auto *Root : Origins) {
              Vars Seen;
              Valid &= permanentRoot(Root, S, Seen) ||
                       circleFunctionRegionOutlives(FT, functionRootRegion(Root), Destination);
            }
            if (!Valid) contractError(At, "returned callback does not preserve its captured lifetime region");
          }
        }
        bool MultiRegionResult =
            !ClassRegion && modulesafety::multiRegionClassValue(F->getReturnType());
#else
        bool MultiRegionResult = false;
#endif
        bool EmptyChoiceReturn = false;
#ifdef MODULE_SAFETY_BUILTIN
        if (R.empty() && projectedRecord(F->getReturnType())) {
          FieldLoans Payload;
          EmptyChoiceReturn =
              projectedPayload(Return->getRetValue(), F->getReturnType(), S,
                               Payload) &&
              Payload.empty();
        }
#endif
        if (modulesafety::returnsGenerative(F)) {
          // External pointer parameters are abstract referent regions, not
          // permanent storage. Calls reconnect them to the caller's owners.
          bool Valid = !R.empty();
          for (auto *Origin : R) {
            Vars Seen;
            Valid &= !S.InvalidRawRoots.count(Origin) &&
                     (permanentRoot(Origin, S, Seen) || ExternalPointerRoots.count(Origin));
          }
          // A slice built from raw parts also carries an extent. In a body
          // whose own claims the checker does not verify, the extent is a
          // claim of that body, exactly as the dereference of its pointer is,
          // and every call reconnects the result to the provenance of its own
          // arguments; a caller that supplies a raw pointer and a count is
          // itself in unsafe code. A checked body may only claim an extent it
          // can place here, which is what the roots of the construction
          // already decide.
          bool ClaimedExtent = false;
#ifdef MODULE_SAFETY_BUILTIN
          if (R.empty())
            if (const InitListExpr *Slice = rawSliceConstruction(Return->getRetValue());
                Slice && !C.circleSliceElement(F->getReturnType()).isNull()) {
              // The pointer half is reconnected at every call, so it has to
              // name an abstract referent or permanent storage: a local is not
              // a source a caller can supply.
              auto Roots = rawPointerRoots(Slice->getInit(0), S);
              bool Valid = !Roots.empty();
              for (auto *Origin : Roots) {
                Vars Seen;
                Valid &= !S.InvalidRawRoots.count(Origin) &&
                         (permanentRoot(Origin, S, Seen) ||
                          ExternalPointerRoots.count(Origin));
              }
              // A body the checker does not verify makes the claim itself. A
              // checked body may only hand the extent on to its callers, and
              // then only when the extent is exactly the count its own
              // parameters name, so every checked call can place it.
              unsigned Pointer = 0, Count = 0;
              ClaimedExtent = Valid &&
                  (ContractsOnly || rawSliceExtentParameters(F, Pointer, Count));
            }
#endif
          if (!Valid && !ClaimedExtent) {
            if (!R.empty())
              contractError(At, "generative return lifetime cannot expose a local or input-bound owner");
#ifdef MODULE_SAFETY_BUILTIN
            else if (unprovenSliceExtent(Return->getRetValue()))
              contractError(At, "raw slice extent is not proven within a known allocation");
#endif
            else
              contractError(At, "generative raw borrow construction provenance is not yet modeled");
          }
        } else if (StaticContract) {
          bool Valid = !R.empty();
          for (auto *Origin : R) {
            Vars Seen;
            Valid &= permanentRoot(Origin, S, Seen);
          }
          if (!Valid)
            contractError(At, "static return lifetime contract requires permanent non-thread-local borrow origins");
        } else if (MultiRegionResult) {
#ifdef MODULE_SAFETY_BUILTIN
          classResultFields(Return->getRetValue(), F->getReturnType(), At, S);
#endif
        } else if (ClassRegion) {
          bool Valid = !R.empty();
          for (auto *Origin : R) {
            Vars Seen;
            bool Allowed = permanentRoot(Origin, S, Seen);
            if (auto I = ClassRegions.find(Origin); I != ClassRegions.end())
              for (auto Index : From)
                if (Index < F->getNumParams()) {
                  auto *P = F->getParamDecl(Index);
                  Allowed |= I->second.Parameter == P &&
#ifdef MODULE_SAFETY_BUILTIN
                             circleClassRegionOutlives(I->second.Record, I->second.Index, ClassRegion) &&
#else
                             I->second.Index == ClassRegion &&
#endif
                             S.Ready.count(P) && !S.Moved.count(P) && !S.Relocated.count(P);
                }
            Valid &= Allowed;
          }
          if (!Valid)
            contractError(At, "class result lifetime contract does not borrow from its declared stored region");
        } else if (!EmptyChoiceReturn &&
                   ((From.empty() && !ThisContract && !ExplicitSelf) || R.empty()))
          contractError(At, "returned borrow has unknown lifetime provenance");
        else
          for (auto *Origin : R) {
            bool Allowed =
                ThisContract && (Origin == ThisOrigin || CaptureRegions.count(Origin) ||
                                 CapturedVariables.count(Origin));
            Allowed |= ExplicitSelf && Origin == ExplicitSelf;
#ifdef MODULE_SAFETY_BUILTIN
            // A permanent referent satisfies every quantified native result
            // lifetime, even when the result's public contract is shorter.
            if (F->getReturnType()->getAs<BorrowValueType>() ||
                circleSimpleClassValueRegion(F->getReturnType())) {
              Vars Seen;
              Allowed |= permanentRoot(Origin, S, Seen);
            }
#endif
            for (auto I : From)
              if (I < F->getNumParams()) {
                auto *P = F->getParamDecl(I);
                if (Origin == P &&
                    (P->getType()->isReferenceType() ||
                     !objectBorrow(P->getType()) ||
#ifdef MODULE_SAFETY_BUILTIN
                     (I == 0 && P->getType()->getAs<BorrowValueType>() &&
                      isa<CXXMethodDecl>(F) &&
                      cast<CXXMethodDecl>(F)->isExplicitObjectMemberFunction())
#else
                     false
#endif
                     ))
                  Allowed = true;
                if (auto It = ParameterRegions.find(Origin);
                    It != ParameterRegions.end() && It->second == P) {
                  bool Related = true;
#ifdef MODULE_SAFETY_BUILTIN
                  auto *Type = F->getType()->getAs<FunctionProtoType>();
                  auto Bindings = Type->getLifetimeBindings();
                  // Parameter-source summaries collapse a multi-region value
                  // to one index; recover its individual field obligation.
                  if ((circleFunctionHasClassProjection(Type, I + 1) ||
                       modulesafety::multiRegionClassValue(P->getType())) &&
                      !Bindings.empty() && Bindings[0])
                    Related = functionRegionOutlives(Type,
                        functionRootRegion(Origin), Bindings[0]);
#endif
                  Allowed |= Related;
                }
              }
            if (!Allowed)
              contractError(At, "returned reference does not borrow from the declared "
                        "lifetime source");
          }
      }
    }
    // Non-lexical borrows expire after the last CFG use, rather than holding
    // every loan to the end of its enclosing C++ scope.
    auto It = LiveAfter.find(At);
    if (It != LiveAfter.end()) {
      for (auto L = S.Loans.begin(); L != S.Loans.end();)
        if (!It->second.count(L->first) &&
            !isa<ParmVarDecl>(L->first)) {
          auto *Dead = L->first;
          ++L;
          eraseLoan(Dead, S);
        } else
          ++L;
    }
  }
  void unwindLocals(State &S, unsigned Handler) {
    // Keep external aliases' roots: reading them after unwind must fail.
    for (auto *Local : HandlerLocals[Handler]) {
      // Cleanup invokes nontrivial drops even when Clang's EH edge skips
      // their ordinary CFG elements. Such drops may mutate borrowed unions.
      auto *Record = C.getBaseElementType(Local->getType())->getAsCXXRecordDecl();
      if (Record && !Record->hasTrivialDestructor() && S.Ready.count(Local) &&
          !S.Relocated.count(Local) && !Context.UnsafeVars.count(Local)) {
        checkDropBorrows(Record->getDestructor(), Local, F->getBody(), S);
        globalCall(Record->getDestructor(), F->getBody(), S);
      }
      if (Record && !Record->hasTrivialDestructor() &&
          objectBorrow(Local->getType(), true))
        for (auto *Origin : roots(Local, S))
          S.ActiveUnions.erase(Origin);
      endFields(Local, S);
      eraseLoan(Local, S);
      S.ActiveUnions.erase(Local);
    }
  }
  State transfer(const CFGBlock *B, State S) {
    auto &Exceptions = ExceptionalOut[B->getBlockID()];
    Exceptions.clear();
    for (auto &Element : *B) {
      State Before = S;
      if (auto St = Element.getAs<CFGStmt>())
        statement(St->getStmt(), S);
      if (auto Init = Element.getAs<CFGInitializer>())
        if (auto *I = Init->getInitializer(); I->isMemberInitializer() &&
            staticLifetimeField(I->getMember()))
          staticFieldValue(I->getInit(), I->getInit(), S);
      if (auto Init = Element.getAs<CFGInitializer>())
        if (auto *I = Init->getInitializer(); I->isMemberInitializer() &&
            (fieldClassRegion(I->getMember()) ||
             nativeCallableValue(I->getMember()->getType()))) {
          classFieldValue(I->getMember(), I->getInit(), nullptr, I->getInit(), S);
          if (ThisOrigin) {
            S.Fields[ThisOrigin][{I->getMember()}] = {
              expressionRoots(I->getInit(), S), objectBorrow(I->getMember()->getType(), true)};
#ifdef MODULE_SAFETY_BUILTIN
            rememberCallableFields(ThisOrigin, I->getInit(), I->getMember()->getType(), S, {I->getMember()});
#endif
          }
        }
      if (auto Init = Element.getAs<CFGInitializer>(); Init && ThisOrigin)
        if (auto *I = Init->getInitializer(); I->isMemberInitializer())
          if (auto *Place = fieldOrigin(ThisOrigin, {I->getMember()})) {
            S.Ready.insert(Place);
            S.RetainedBorrows[Place] = expressionRoots(I->getInit(), S);
          }
      if (auto Dtor = Element.getAs<CFGImplicitDtor>()) {
        const Stmt *At = F->getBody();
        bool UnsafeDtor = false;
        const VarDecl *Object = nullptr;
        auto *DropDtor = Dtor->getDestructorDecl(C);
        bool DropOnlyDtor =
            DropDtor && marked(DropDtor, "safecpp.drop.only");
        if (auto Automatic = Element.getAs<CFGAutomaticObjDtor>()) {
          At = Automatic->getTriggerStmt();
          Object = Automatic->getVarDecl();
          UnsafeDtor = Context.UnsafeVars.count(Object);
          if (!DropOnlyDtor && !UnsafeDtor && !S.Relocated.count(Object) &&
              objectBorrow(Object->getType()) &&
              !(S.Moved.count(Object) && movedDropSafe(Object->getType())))
            access(Object, objectBorrow(Object->getType(), true), At, S);
        }
        if (auto Deleted = Element.getAs<CFGDeleteDtor>())
          At = Deleted->getDeleteExpr();
        if (auto Temporary = Element.getAs<CFGTemporaryDtor>())
          At = Temporary->getBindTemporaryExpr();
        if (auto *D = DropDtor; D && !D->isTrivial()) {
          if (Object && !S.Relocated.count(Object))
            checkDropBorrows(D, Object, At, S);
          if (Object && objectBorrow(Object->getType(), true))
            for (auto *Origin : roots(Object, S))
              S.ActiveUnions.erase(Origin);
          if (auto Temporary = Element.getAs<CFGTemporaryDtor>())
            if (objectBorrow(Temporary->getBindTemporaryExpr()->getType(), true))
              for (auto *Origin : expressionRoots(
                       Temporary->getBindTemporaryExpr(), S))
                S.ActiveUnions.erase(Origin);
        }
        if (Emit && !UnsafeDtor && !Context.Unchecked.count(At))
          if (auto *D = Dtor->getDestructorDecl(C); D && !D->isTrivial())
            Check(D, At->getBeginLoc());
        if (!Object || !S.Relocated.count(Object))
          globalCall(Dtor->getDestructorDecl(C), At, S);
        // Lifetime ends when destruction begins, including a throwing drop.
        if (Object) {
          endFields(Object, S);
          eraseLoan(Object, S);
          S.ActiveUnions.erase(Object);
        }
      }
      if (auto Handler = ExceptionHandlers.find(&Element);
          Handler != ExceptionHandlers.end()) {
        // A failing operation may have consumed an argument, but may not
        // initialize its destination. Destruction invalidates its storage.
        State Failure = joinStates(std::move(Before), S);
        if (auto St = Element.getAs<CFGStmt>())
          if (auto *B = dyn_cast<BinaryOperator>(St->getStmt());
              B && BinaryOperator::getOpcodeStr(B->getOpcode()) == ":=" && implicitRuntimeThrow(B)) {
            auto *Owner = variable(B->getLHS());
            auto Field = ownedFieldPath(B->getLHS());
            auto Places = ownedPlaces(Owner);
            if (!Field.empty()) {
              Failure.RelocatedFields[Owner].insert(Field);
              Places = ownedPlaces(Owner, Field);
            }
            for (auto *Place : Places) {
              Failure.Relocated.insert(Place); Failure.Moved.insert(Place); Failure.Ready.erase(Place);
            }
          }
        unsigned ID = Handler->second->getBlockID();
        unwindLocals(Failure, ID);
        if (Element.getAs<CFGMemberDtor>() || Element.getAs<CFGBaseDtor>())
          Failure.Ready.erase(ThisOrigin);
        if (auto I = Exceptions.find(ID); I != Exceptions.end())
          I->second = joinStates(std::move(I->second), Failure);
        else Exceptions.emplace(ID, std::move(Failure));
      }
      if (auto End = Element.getAs<CFGLifetimeEnds>()) {
        auto *V = End->getVarDecl();
        endFields(V, S);
        S.ActiveUnions.erase(V);
        eraseLoan(V, S);
        S.Fields.erase(V);
      }
      if (auto End = Element.getAs<CFGScopeEnd>()) {
        auto *Scope = dyn_cast_or_null<CompoundStmt>(End->getTriggerStmt());
        for (auto &[V, VS] : Context.Scopes)
          if (VS == Scope) {
            endFields(V, S);
            S.ActiveUnions.erase(V);
            S.Moved.erase(V);
            eraseLoan(V, S);
            S.Fields.erase(V);
          }
      }
    }
    return S;
  }
  void liveness(const CFG &Graph) {
    std::vector<Vars> In(Graph.getNumBlockIDs()), Out(Graph.getNumBlockIDs());
    bool Changed = true;
    while (Changed) {
      Changed = false;
      for (auto *B : Graph) {
        Vars Live;
        for (auto Succ : B->succs())
          if (auto *Next = Succ.getReachableBlock())
            Live.insert(In[Next->getBlockID()].begin(), In[Next->getBlockID()].end());
        for (auto &Element : *B)
          if (auto I = ExceptionHandlers.find(&Element);
              I != ExceptionHandlers.end()) {
            auto &HandlerLive = In[I->second->getBlockID()];
            Live.insert(HandlerLive.begin(), HandlerLive.end());
          }
        Out[B->getBlockID()] = Live;
        for (auto It = B->rbegin(); It != B->rend(); ++It) {
          if (auto Init = It->getAs<CFGInitializer>()) {
            Uses U;
            U.TraverseStmt(Init->getInitializer()->getInit());
            Live.insert(U.Used.begin(), U.Used.end());
          }
          if (auto Dtor = It->getAs<CFGAutomaticObjDtor>();
              Dtor && Dtor->getDestructorDecl(C) &&
              !Dtor->getDestructorDecl(C)->isTrivial()) {
            auto *Variable = Dtor->getVarDecl();
            auto *Record = Variable
                               ? C.getBaseElementType(Variable->getType())
                                     ->getAsCXXRecordDecl()
                               : nullptr;
            // A generated choice destructor only drops the active payload.
            // Its presence does not keep an outer borrow result live after
            // the result's last use.
            if (!Record || !marked(Record, "safecpp.native.choice"))
              Live.insert(Variable);
          }
          if (auto St = It->getAs<CFGStmt>()) {
            auto *S = St->getStmt();
            if (auto *D = dyn_cast<DeclStmt>(S))
              for (auto *Item : D->decls())
                if (auto *V = dyn_cast<VarDecl>(Item))
                  Live.erase(V);
            Uses U;
            U.TraverseStmt(const_cast<Stmt *>(S));
            Live.insert(U.Used.begin(), U.Used.end());
          }
        }
        if (In[B->getBlockID()] != Live) {
          In[B->getBlockID()] = std::move(Live);
          Changed = true;
        }
      }
    }
    for (auto *B : Graph) {
      Vars Live = Out[B->getBlockID()];
      for (auto It = B->rbegin(); It != B->rend(); ++It) {
        if (auto Init = It->getAs<CFGInitializer>()) {
          Uses U;
          U.TraverseStmt(Init->getInitializer()->getInit());
          Live.insert(U.Used.begin(), U.Used.end());
        }
        if (auto Dtor = It->getAs<CFGAutomaticObjDtor>();
            Dtor && Dtor->getDestructorDecl(C) &&
            !Dtor->getDestructorDecl(C)->isTrivial()) {
          auto *Variable = Dtor->getVarDecl();
          auto *Record = Variable
                             ? C.getBaseElementType(Variable->getType())
                                   ->getAsCXXRecordDecl()
                             : nullptr;
          if (!Record || !marked(Record, "safecpp.native.choice"))
            Live.insert(Variable);
        }
        if (auto St = It->getAs<CFGStmt>()) {
          auto *S = St->getStmt();
          LiveAfter[S] = Live;
          if (auto *D = dyn_cast<DeclStmt>(S))
            for (auto *Item : D->decls())
              if (auto *V = dyn_cast<VarDecl>(Item))
                Live.erase(V);
          Uses U;
          U.TraverseStmt(const_cast<Stmt *>(S));
          Live.insert(U.Used.begin(), U.Used.end());
        }
      }
    }
  }

public:
  Analysis(ASTContext &C, FunctionDecl *F, CheckCall Check, bool ContractsOnly = false)
      : C(C), F(F), Check(std::move(Check)), ContractsOnly(ContractsOnly) {}
  void run() {
    if (!F->doesThisDeclarationHaveABody() || F->isDependentContext())
      return;
    if (const auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && Method->isImplicit() && Method->isDefaulted() && Method->isTrivial() &&
        (Method->isCopyAssignmentOperator() || Method->isMoveAssignmentOperator()) &&
        projectedRecord(C.getCanonicalTagType(Method->getParent()))) return;
    if (auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && Method->isImplicit() && Method->isLambdaStaticInvoker()) {
      // Clang stores an empty AST stub here and emits a forwarding call in
      // CodeGen. Validate the operator and every concrete specialization,
      // rather than treating the stub as user-written fallthrough.
      auto *Operator = Method->getParent()->getLambdaCallOperator();
      Check(Operator, F->getLocation());
      if (auto *Template = Operator->getDescribedFunctionTemplate())
        for (auto *Specialization : Template->specializations())
          Check(Specialization, F->getLocation());
      return;
    }
    auto *Coroutine = dyn_cast<CoroutineBodyStmt>(F->getBody());
    Stmt *Body = Coroutine ? Coroutine->getBody() : F->getBody();
    // Check normal exits independently of warning flags and exception edges.
    // The ownership CFG below includes EH edges, which are not fallthrough.
    if (!Coroutine && (F->isNoReturn() ||
                       (!F->getReturnType()->isVoidType() && !F->isMain()))) {
      CFG::BuildOptions ReturnOptions;
      ReturnOptions.AddImplicitDtors = true;
      ReturnOptions.AddTemporaryDtors = true;
      auto Returns = CFG::buildCFG(F, Body, &C, ReturnOptions);
      Emit = true;
      if (!Returns) {
        error(Body, "cannot verify return paths of safe function");
        return;
      }
      std::set<const CFGBlock *> Reachable;
      std::deque<const CFGBlock *> Work{&Returns->getEntry()};
      // Without EH edges, catch dispatch blocks reached by throwing calls
      // have no predecessors. Their handlers must still return or throw.
      for (auto *B : *Returns)
        if (B->pred_empty() && isa_and_nonnull<CXXTryStmt>(B->getTerminatorStmt()))
          Work.push_back(B);
      while (!Work.empty()) {
        auto *B = Work.front();
        Work.pop_front();
        if (!Reachable.insert(B).second || B->hasNoReturnElement())
          continue;
        for (auto Next : B->succs())
          if (auto *N = Next.getReachableBlock())
            Work.push_back(N);
      }
      for (auto Pred : Returns->getExit().preds()) {
        auto *B = Pred.getReachableBlock();
        if (!B || !Reachable.count(B) || B->hasNoReturnElement())
          continue;
        const Stmt *Last = nullptr;
        for (auto It = B->rbegin(); It != B->rend(); ++It)
          if (auto E = It->getAs<CFGStmt>()) {
            Last = E->getStmt();
            break;
          }
        if (isa_and_nonnull<CXXThrowExpr, CXXTryStmt>(Last) ||
            (!Last && isa_and_nonnull<CXXTryStmt>(B->getTerminatorStmt())))
          continue;
        if (F->isNoReturn()) {
          error(Body, "noreturn function can complete normally");
          continue;
        }
        if (isa_and_nonnull<ReturnStmt>(Last)) continue;
        error(Body, "non-void function can reach its end without returning a value");
      }
      Emit = false;
    }
    if (auto *Method = dyn_cast<CXXMethodDecl>(F); Method && Method->isImplicitObjectMemberFunction())
      ThisOrigin =
          ImplicitParamDecl::Create(C, F, F->getLocation(), nullptr,
                                    Method->getThisType(), ImplicitParamKind::Other);
    Context.TraverseStmt(Body);
    if (isa<CXXConstructorDecl, CXXDestructorDecl>(F))
      if (auto *Try = dyn_cast<CXXTryStmt>(Body)) {
        class DeadObject : public RecursiveASTVisitor<DeadObject> {
        public:
          std::vector<const CXXThisExpr *> Uses;
          bool VisitCXXThisExpr(CXXThisExpr *E) { Uses.push_back(E); return true; }
          bool TraverseUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *) {
            return true;
          }
          bool TraverseCXXNoexceptExpr(CXXNoexceptExpr *) { return true; }
          bool TraverseExpressionTraitExpr(ExpressionTraitExpr *) { return true; }
        } Visitor;
        for (unsigned I = 0; I < Try->getNumHandlers(); ++I)
          Visitor.TraverseStmt(Try->getHandler(I)->getHandlerBlock());
        Emit = true;
        for (auto *Use : Visitor.Uses)
          error(Use, "function-try handler accesses an object whose members "
                     "have already been destroyed");
        Emit = false;
      }
    CFG::BuildOptions Options;
    Options.setAllAlwaysAdd();
    Options.AddScopes = true;
    // Member/base initializers execute before the body and may consume or
    // borrow parameters. Their effects must participate in the same fixed point.
    Options.AddInitializers = true;
    Options.AddImplicitDtors = true;
    Options.AddTemporaryDtors = true;
    Options.AddEHEdges = true;
    Options.AddLifetime = true;
    auto Graph = CFG::buildCFG(F, Body, &C, Options);
    if (!Graph) {
      Emit = true;
      error(Body, "cannot build control-flow graph for safe function");
      return;
    }
    // Clang 22 omits constructor EH edges. Recover the nearest lexical
    // dispatch and propagate a conservative pre/post-construction state.
    std::map<const CXXTryStmt *, const CFGBlock *> Handlers;
    for (auto *Block : Graph->try_blocks())
      if (auto *Try = dyn_cast_or_null<CXXTryStmt>(Block->getTerminatorStmt())) {
        Handlers[Try] = Block;
        class Locals : public RecursiveASTVisitor<Locals> {
        public:
          Vars Found;
          bool VisitVarDecl(VarDecl *V) {
            if (V->hasLocalStorage()) Found.insert(V);
            return true;
          }
          bool TraverseLambdaExpr(LambdaExpr *) { return true; }
        } Collector;
        Collector.TraverseStmt(const_cast<CompoundStmt *>(Try->getTryBlock()));
        HandlerLocals[Block->getBlockID()] = std::move(Collector.Found);
      }
    auto NearestHandler = [&](DynTypedNode Node) -> const CXXTryStmt * {
      while (true) {
        auto Parents = parentNodes(Node);
        if (Parents.size() != 1) return nullptr;
        if (auto *Try = Parents[0].get<CXXTryStmt>();
            Try && Node.get<Stmt>() == Try->getTryBlock())
          return Try;
        if (Parents[0].get<FunctionDecl>()) return nullptr;
        Node = Parents[0];
      }
    };
    auto DefaultMayThrow = [](const Expr *Expression) {
      class PotentialThrow : public RecursiveASTVisitor<PotentialThrow> {
        InitListVisitSet<> InitLists;
      public:
        bool Found = false;
        bool shouldVisitImplicitCode() const { return true; }
        bool dataTraverseStmtPre(Stmt *S) { return InitLists.enter(S); }
        bool VisitStmt(Stmt *S) {
          Found |= implicitRuntimeThrow(dyn_cast<Expr>(S));
          return true;
        }
        bool VisitCallExpr(CallExpr *E) {
          const FunctionProtoType *Type = nullptr;
          if (auto *F = E->getDirectCallee())
            Type = F->getType()->getAs<FunctionProtoType>();
          else {
            auto T = E->getCallee()->getType();
            if (T->isPointerType()) T = T->getPointeeType();
            Type = T->getAs<FunctionProtoType>();
          }
          Found |= !Type || !Type->isNothrow();
          return true;
        }
        bool VisitCXXConstructExpr(CXXConstructExpr *E) {
          Found |= !E->getConstructor()->getType()
                        ->castAs<FunctionProtoType>()->isNothrow();
          return true;
        }
        bool VisitCXXBindTemporaryExpr(CXXBindTemporaryExpr *E) {
          Found |= !E->getTemporary()->getDestructor()->getType()
                        ->castAs<FunctionProtoType>()->isNothrow();
          return true;
        }
        bool VisitCXXThrowExpr(CXXThrowExpr *) { Found = true; return true; }
        bool VisitInitListExpr(InitListExpr *E) {
          if (auto *Filler = E->getArrayFiller()) TraverseStmt(Filler);
          return true;
        }
        bool TraverseLambdaExpr(LambdaExpr *E) {
          for (auto *Init : E->capture_inits()) TraverseStmt(Init);
          return true;
        }
        bool TraverseUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *) {
          return true;
        }
        bool TraverseCXXNoexceptExpr(CXXNoexceptExpr *) { return true; }
        bool TraverseExpressionTraitExpr(ExpressionTraitExpr *) { return true; }
        bool TraverseConstantExpr(ConstantExpr *E) {
          return E->isImmediateInvocation() || TraverseStmt(E->getSubExpr());
        }
      } Visitor;
      Visitor.TraverseStmt(const_cast<Expr *>(Expression));
      return Visitor.Found;
    };
    for (auto *Block : *Graph)
      for (auto &Element : *Block) {
        const FunctionDecl *Operation = nullptr;
        const CXXTryStmt *Target = nullptr;
        bool MayThrow = false;
        if (auto Item = Element.getAs<CFGStmt>()) {
          auto *Node = Item->getStmt();
          MayThrow = implicitRuntimeThrow(dyn_cast<Expr>(Node));
          MayThrow |= isa<CXXThrowExpr>(Node);
          if (auto *Construct = dyn_cast<CXXConstructExpr>(Node))
            Operation = Construct->getConstructor();
          if (auto *Default = dyn_cast<CXXDefaultInitExpr>(Node))
            MayThrow = DefaultMayThrow(Default->getExpr());
          if (auto *Default = dyn_cast<CXXDefaultArgExpr>(Node))
            MayThrow = DefaultMayThrow(Default->getExpr());
          if (auto *List = dyn_cast<InitListExpr>(Node))
            if (auto *Filler = List->getArrayFiller())
              MayThrow = DefaultMayThrow(Filler);
          if (Operation || MayThrow) {
            Target = NearestHandler(DynTypedNode::create(*Node));
            if (!Target && isa<CXXConstructorDecl>(F))
              if (auto *Try = dyn_cast<CXXTryStmt>(Body))
                for (auto *Init : cast<CXXConstructorDecl>(F)->inits()) {
                  class Contains : public RecursiveASTVisitor<Contains> {
                  public:
                    const Stmt *Wanted; bool Found = false;
                    explicit Contains(const Stmt *S) : Wanted(S) {}
                    bool VisitStmt(Stmt *S) { Found |= S == Wanted; return true; }
                  } Search(Node);
                  Search.TraverseStmt(Init->getInit());
                  if (Search.Found) Target = Try;
                }
          }
        }
        if (auto Dtor = Element.getAs<CFGImplicitDtor>()) {
          Operation = Dtor->getDestructorDecl(C);
          if (auto Automatic = Element.getAs<CFGAutomaticObjDtor>())
            Target = NearestHandler(DynTypedNode::create(*Automatic->getTriggerStmt()));
          if (auto Temporary = Element.getAs<CFGTemporaryDtor>())
            Target = NearestHandler(DynTypedNode::create(*Temporary->getBindTemporaryExpr()));
          if (auto Deleted = Element.getAs<CFGDeleteDtor>())
            Target = NearestHandler(DynTypedNode::create(*Deleted->getDeleteExpr()));
          if (Element.getAs<CFGMemberDtor>() || Element.getAs<CFGBaseDtor>())
            Target = dyn_cast<CXXTryStmt>(Body);
        }
        if (Operation)
          MayThrow |= !Operation->getType()->castAs<FunctionProtoType>()->isNothrow();
        if (MayThrow && Target && Handlers.count(Target))
          ExceptionHandlers[&Element] = Handlers[Target];
      }
    liveness(*Graph);
    unsigned N = Graph->getNumBlockIDs();
    std::vector<State> In(N), Out(N);
    std::vector<bool> Seen(N, false);
    State Entry;
    auto *Static = VarDecl::Create(
        C, C.getTranslationUnitDecl(), F->getLocation(), F->getLocation(), nullptr,
        C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_Static);
    Static->setImplicit();
    StaticOrigin = Static;
    auto LiteralType = C.getConstType(C.UnsignedCharTy);
    auto *Literal = VarDecl::Create(
        C, C.getTranslationUnitDecl(), F->getLocation(), F->getLocation(), nullptr,
        LiteralType, C.getTrivialTypeSourceInfo(LiteralType), SC_Static);
    Literal->setImplicit();
    LiteralOrigin = Literal;
    if (ThisOrigin)
      Entry.Ready.insert(ThisOrigin);
    if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F); Ctor && ThisOrigin)
      for (auto *Field : Ctor->getParent()->fields())
        if (fieldClassRegion(Field) && indirectBorrowStorage(Field->getType())) {
          auto *Place = ImplicitParamDecl::Create(C, F, Field->getLocation(), nullptr,
              Field->getType(), ImplicitParamKind::Other);
          FieldOrigins[ThisOrigin][{Field}] = Place;
          OriginOwners[Place] = ThisOrigin;
        }
    auto InitializeClassFields = [&](const VarDecl *P, const CXXRecordDecl *R) {
#ifdef MODULE_SAFETY_BUILTIN
      if (!R || !R->hasDefinition()) return;
      std::map<unsigned, const VarDecl *> Regions;
      auto AddFields = [&](auto &&Self, const CXXRecordDecl *Record, FieldPath Path) -> void {
        for (const auto *Field : Record->getDefinition()->fields()) {
          if (Field->isCirclePhantom()) continue;
          auto Next = Path; Next.push_back(Field);
          if (auto *Nested = circleClassRecord(Field->getType());
              Nested && Nested->hasDefinition() &&
              circleTypeLifetimeCount(Field->getType()) > 1) {
            Self(Self, Nested, Next);
            continue;
          }
          if (circleIsCallableValue(Field->getType())) {
            auto Captures = circleCallableCaptures(Field->getType());
            for (unsigned I = 0; I < Captures.size(); ++I) {
              unsigned Index = mappedPathRegion(Next, I + 1);
              if (!Index) continue;
              const VarDecl *Root = StaticOrigin;
              if (Index != 0x40000000u) {
                auto &Stored = Regions[Index];
                if (!Stored) {
                  auto *Region = VarDecl::Create(C, F, P->getLocation(), P->getLocation(), nullptr,
                      C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
                  Region->setImplicit(); Stored = Region;
                  ClassRegions[Stored] = {P, R->getCanonicalDecl(), Index};
                  if (const auto *Parameter = dyn_cast<ParmVarDecl>(P)) ParameterRegions[Stored] = Parameter;
                  Entry.Ready.insert(Stored);
                }
                Root = Stored;
              }
              Entry.Callables[P][Next][Captures[I]] = {Root};
              Entry.Fields[P][Next].Roots.insert(Root);
            }
            continue;
          }
          unsigned Index = mappedPathRegion(Next);
          if (!Index || Index == 0x40000000u) continue;
          auto &Root = Regions[Index];
          if (!Root) {
            auto *Region = VarDecl::Create(C, F, P->getLocation(), P->getLocation(), nullptr,
                C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
            Region->setImplicit(); Root = Region;
            ClassRegions[Root] = {P, R->getCanonicalDecl(), Index};
            if (const auto *Parameter = dyn_cast<ParmVarDecl>(P))
              ParameterRegions[Root] = Parameter;
            Entry.Ready.insert(Root);
          }
          Entry.Fields[P][Next] = {{Root}, objectBorrow(Field->getType(), true)};
        }
      };
      AddFields(AddFields, R, {});
      if (Regions.empty() && indirectBorrowStorage(P->getType())) {
        unsigned Count = circleClassLifetimeNames(R).size();
        for (unsigned Index = 1; Index <= Count; ++Index) {
          auto *Root = VarDecl::Create(C, F, P->getLocation(), P->getLocation(), nullptr,
              C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
          Root->setImplicit();
          ClassRegions[Root] = {P, R->getCanonicalDecl(), Index};
          if (const auto *Parameter = dyn_cast<ParmVarDecl>(P))
            ParameterRegions[Root] = Parameter;
          Entry.Ready.insert(Root);
          Entry.RetainedBorrows[P].insert(Root);
        }
      }
#endif
    };
#ifdef MODULE_SAFETY_BUILTIN
    if (ThisOrigin && !isa<CXXConstructorDecl>(F))
      if (auto *M = dyn_cast<CXXMethodDecl>(F))
        InitializeClassFields(ThisOrigin, M->getParent());
#endif
    for (auto *P : F->parameters()) {
      Entry.Ready.insert(P);
      initializeFields(P, Entry);
#ifdef MODULE_SAFETY_BUILTIN
      if (P->getType()->getAs<BorrowValueType>()) {
        // The parameter handle is local storage even when its referent is
        // static. Keep its address distinct from the referent's region.
        auto *Storage = ImplicitParamDecl::Create(C, F, P->getLocation(), nullptr,
            P->getType(), ImplicitParamKind::Other);
        FieldOrigins[P][{}] = Storage;
        OriginOwners[Storage] = P;
        Entry.Ready.insert(Storage);
      }
      if (C.getLangOpts().CircleBorrowValues && P->getType()->isPointerType() &&
          !P->getType()->getPointeeType()->isFunctionType()) {
        auto *Root = VarDecl::Create(C, F, P->getLocation(), P->getLocation(), nullptr,
            C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
        Root->setImplicit();
        ExternalPointerRoots.insert(Root);
        Entry.Ready.insert(Root);
        Entry.RawPointers[P] = {Root};
      }
#endif
      if (!P->getType()->isReferenceType() && objectBorrow(P->getType())) {
        auto *Region = VarDecl::Create(
            C, F, P->getLocation(), P->getLocation(), nullptr, C.UnsignedCharTy,
            C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
        Region->setImplicit();
        ParameterRegions[Region] = P;
#ifdef MODULE_SAFETY_BUILTIN
        if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F))
          if (unsigned Index = constructorParameterRegion(P, Ctor->getParent()))
            ClassRegions[Region] = {P, Ctor->getParent()->getCanonicalDecl(), Index};
#endif
        Entry.Ready.insert(Region);
        Vars Origins{Region};
        // Self-references of an owned pinned parameter can point into the
        // parameter itself; they are not all external borrowed regions.
        if (pinnedStorage(P->getType())) Origins.insert(P);
        Entry.Loans[P] = {Origins, objectBorrow(P->getType(), true)};
#ifdef MODULE_SAFETY_BUILTIN
        if (P->getType()->getAs<BorrowValueType>()) Entry.BorrowStorage[P] = Origins;
#endif
      }
      if (P->getType()->isReferenceType()) Entry.BorrowStorage[P] = ownedPlaces(P);
#ifdef MODULE_SAFETY_BUILTIN
      InitializeClassFields(P, circleClassRecord(P->getType()));
      if (circleIsCallableValue(P->getType())) {
        unsigned Index = 0;
        for (unsigned ID : circleCallableCaptures(P->getType())) {
          auto *Root = VarDecl::Create(C, F, P->getLocation(), P->getLocation(), nullptr,
              C.UnsignedCharTy, C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
          Root->setImplicit();
          ClassRegions[Root] = {P, nullptr, ++Index}; ParameterRegions[Root] = P;
          Entry.Ready.insert(Root); Entry.Callables[P][{}][ID] = {Root};
          Entry.Loans[P].Roots.insert(Root);
        }
      }
#endif
    }
    if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
        Ctor && (!storedParameters(Ctor).empty() ||
                 modulesafety::marked(Ctor, "safecpp.stores.self"))) {
      auto Allowed = storedParameters(Ctor);
      bool Self = modulesafety::marked(Ctor, "safecpp.stores.self") &&
                  pinnedStorage(C.getCanonicalTagType(Ctor->getParent()));
      Emit = true;
      for (auto *Init : Ctor->inits()) {
        QualType Storage;
        if (Init->isMemberInitializer())
          Storage = Init->getMember()->getType();
        else if (Init->isBaseInitializer())
          Storage = QualType(Init->getBaseClass(), 0);
        if (Storage.isNull() || !objectBorrow(Storage))
          continue;
        auto Sources = expressionRoots(Init->getInit(), Entry);
        if (Sources.empty())
          error(Init->getInit(), "constructor storage has unknown borrow provenance");
        for (auto *Source : Sources) {
          bool Valid = Self && Source == ThisOrigin;
#ifdef MODULE_SAFETY_BUILTIN
          if (Storage->getAs<BorrowValueType>()) {
            Vars Seen;
            Valid |= permanentRoot(Source, Entry, Seen);
          }
#endif
          for (auto I : Allowed) {
            if (I >= Ctor->getNumParams())
              continue;
            auto *P = Ctor->getParamDecl(I);
            if (Source == P && P->getType()->isReferenceType())
              Valid = true;
            if (auto It = ParameterRegions.find(Source);
                It != ParameterRegions.end() && It->second == P)
              Valid = true;
          }
          if (!Valid)
            error(Init->getInit(), "constructor stores a borrow outside its "
                                   "declared lifetime sources");
        }
      }
      Emit = false;
    }
    if (auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && Method->getParent()->isLambda())
      for (auto &Capture : Method->getParent()->captures())
        if (Capture.capturesVariable())
          if (auto *V = dyn_cast<VarDecl>(Capture.getCapturedVar())) {
            Entry.Ready.insert(V);
            if (ThisOrigin) {
              auto *Region = VarDecl::Create(
                  C, F, V->getLocation(), V->getLocation(), nullptr, C.UnsignedCharTy,
                  C.getTrivialTypeSourceInfo(C.UnsignedCharTy), SC_None);
              Region->setImplicit();
              Entry.Ready.insert(Region);
              CaptureRegions.insert(Region);
              CapturedVariables.insert(V);
              Entry.Loans[V] = {{Region}, objectBorrow(V->getType(), true)};
            }
          }
    bool Changed = true;
    unsigned Iterations = 0;
    while (Changed) {
      if (++Iterations > N * N + N + 1) {
        Emit = true;
        error(F->getBody(), "control-flow safety analysis did not converge");
        return;
      }
      Changed = false;
      for (auto *B : *Graph) {
        State Joined;
        bool Reachable = B == &Graph->getEntry();
        if (Reachable)
          Joined = Entry;
        for (auto Pred : B->preds())
          if (auto *P = Pred.getReachableBlock()) {
            if (!Seen[P->getBlockID()])
              continue;
            State Previous = Out[P->getBlockID()];
#ifdef MODULE_SAFETY_BUILTIN
            applySliceBoundEdge(P, B, Previous);
#endif
            if (!Reachable) {
              Joined = Previous;
              Reachable = true;
            } else {
              Joined = joinStates(std::move(Joined), Previous);
            }
          }
        for (auto &[Source, Edges] : ExceptionalOut)
          if (Seen[Source])
            if (auto I = Edges.find(B->getBlockID()); I != Edges.end()) {
              if (Reachable) Joined = joinStates(std::move(Joined), I->second);
              else { Joined = I->second; Reachable = true; }
            }
        if (!Reachable)
          continue;
        if (HandlerLocals.count(B->getBlockID()))
          unwindLocals(Joined, B->getBlockID());
        auto PriorExceptions = ExceptionalOut[B->getBlockID()];
        auto Result = transfer(B, Joined);
        if (PriorExceptions != ExceptionalOut[B->getBlockID()]) Changed = true;
        unsigned ID = B->getBlockID();
        In[ID] = std::move(Joined);
        if (!Seen[ID] || !(Out[ID] == Result)) {
          Out[ID] = std::move(Result);
          Seen[ID] = true;
          Changed = true;
        }
      }
    }
    Emit = true;
    Emit = true;
    for (auto *B : *Graph)
      if (Seen[B->getBlockID()])
        transfer(B, In[B->getBlockID()]);
  }
};
} // namespace
void analyzeFunction(ASTContext &C, FunctionDecl *F, CheckCall Check, bool ContractsOnly) {
  Analysis(C, F, std::move(Check), ContractsOnly).run();
}

void analyzeInitializer(ASTContext &C, VarDecl *V, CheckCall Check, bool ContractsOnly) {
  auto Loc = V->getLocation();
  auto Type = C.getFunctionType(C.VoidTy, {}, FunctionProtoType::ExtProtoInfo{});
  auto *F =
      FunctionDecl::Create(C, C.getTranslationUnitDecl(), Loc, Loc, DeclarationName(),
                           Type, C.getTrivialTypeSourceInfo(Type), SC_None);
  F->setImplicit();
  auto *Statement = new (C) DeclStmt(DeclGroupRef(V), Loc, Loc);
  Stmt *Statements[] = {Statement};
  F->setBody(CompoundStmt::Create(C, Statements, FPOptionsOverride{}, Loc, Loc));
  Analysis(C, F, std::move(Check), ContractsOnly).run();
}
} // namespace modulesafety
