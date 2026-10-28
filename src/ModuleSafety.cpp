#include "FlowAnalysis.h"
#include "SafetyContracts.h"
#include "SafetyTraversal.h"
#ifdef MODULE_SAFETY_BUILTIN
#include "clang/AST/CircleFunctionRelation.h"
#include "clang/AST/CircleRelocation.h"
#endif
#include "clang/AST/ASTConsumer.h"
#include "clang/AST/Attr.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/AST/StmtOpenMP.h"
#include "clang/Basic/DiagnosticFrontend.h"
#include "clang/Basic/Module.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Frontend/FrontendPluginRegistry.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Sema/Sema.h"
#include "clang/Serialization/ASTReader.h"
#include "clang/Serialization/ModuleFile.h"
#include "clang/Serialization/ModuleManager.h"
#include "llvm/ADT/SmallPtrSet.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include <map>
#include <set>
#include <tuple>
#include <vector>
#ifndef MODULE_SAFETY_FINGERPRINT
#error "Build the checker using its CMake target to supply a safety fingerprint"
#endif
using namespace clang;
#ifdef MODULE_SAFETY_BUILTIN
namespace clang {
std::unique_ptr<ASTConsumer> CreateModuleSafetyConsumer(CompilerInstance &, bool);
}
#endif
namespace {
// A deferred borrow slot is only legal when the body actually binds it later.
// Reads before that binding are still rejected by the flow analysis; this
// check keeps a declaration that is never initialized a hard error.
bool laterBorrowAssignment(const VarDecl *V) {
  const auto *Owner = dyn_cast_or_null<FunctionDecl>(V->getDeclContext());
  if (!Owner || !Owner->getBody()) return false;
  class Assignments : public RecursiveASTVisitor<Assignments> {
  public:
    const VarDecl *Wanted;
    bool Found = false;
    explicit Assignments(const VarDecl *V) : Wanted(V) {}
    bool VisitBinaryOperator(BinaryOperator *B) {
      if (!B->isAssignmentOp()) return true;
      const Expr *L = B->getLHS()->IgnoreParenImpCasts();
      if (const auto *D = dyn_cast<DeclRefExpr>(L))
        Found |= D->getDecl() == Wanted;
      return true;
    }
  } Visitor(V);
  Visitor.TraverseStmt(Owner->getBody());
  return Visitor.Found;
}
class StaticContractCalls : public RecursiveASTVisitor<StaticContractCalls> {
public:
  bool Found = false;
  void inspect(QualType Type) {
#ifdef MODULE_SAFETY_BUILTIN
    if (Type->isPointerType()) Type = Type->getPointeeType();
    if (auto *Proto = Type->getAs<FunctionProtoType>()) {
      Found |= Proto->getReturnBorrowClassRegion() != 0 || Proto->hasGenerativeReturnLifetime() ||
               !circleCallableCaptures(QualType(Proto, 0)).empty();
      for (unsigned I = 0; I < Proto->getNumParams(); ++I) {
        auto Info = Proto->getExtParameterInfo(I);
        Found |= Info.hasStaticLifetime() || Info.hasStaticTypeLifetimes() ||
                 circleFunctionRegionIsStatic(Proto, circleFunctionRegion(Proto, I + 1));
      }
      auto Projections = Proto->getClassLifetimeBindings();
      for (unsigned I = 0; I + 2 < Projections.size(); I += 3)
        if (Projections[I])
          Found |= circleFunctionRegionIsStatic(Proto, Projections[I + 2]);
    }
#endif
  }
  void inspect(const FunctionDecl *Function) {
    if (!Function) return;
    Found |= !modulesafety::storedParameters(Function).empty();
    for (auto *Decl : Function->redecls())
      for (auto *Attribute : Decl->specific_attrs<AnnotateAttr>())
        Found |= Attribute->getAnnotation().starts_with("safecpp.unsafe.adopts.borrow:");
  }
  bool VisitCallExpr(CallExpr *E) {
    inspect(E->getDirectCallee());
    inspect(E->getDirectCallee() ? E->getDirectCallee()->getType()
                                 : E->getCallee()->getType());
    return true;
  }
  bool VisitCXXConstructExpr(CXXConstructExpr *E) {
    inspect(E->getConstructor());
    inspect(E->getConstructor()->getType()); return true;
  }
  bool VisitCXXConstructorDecl(CXXConstructorDecl *D) {
    Found |= modulesafety::hasStaticLifetimeFields(
        D->getASTContext().getCanonicalTagType(D->getParent())) ||
        modulesafety::hasClassLifetimeFields(D->getASTContext().getCanonicalTagType(D->getParent()));
    return true;
  }
  bool VisitMemberExpr(MemberExpr *E) {
    Found |= modulesafety::staticLifetimeField(
        dyn_cast<FieldDecl>(E->getMemberDecl())) ||
        modulesafety::fieldClassRegion(dyn_cast<FieldDecl>(E->getMemberDecl()));
    return true;
  }
  bool VisitInitListExpr(InitListExpr *E) {
    Found |= modulesafety::hasStaticLifetimeFields(E->getType()) ||
        modulesafety::hasClassLifetimeFields(E->getType());
    return true;
  }
  bool VisitCastExpr(CastExpr *E) {
    Found |= modulesafety::hasStaticLifetimeFields(E->getType()) ||
        modulesafety::hasClassLifetimeFields(E->getType());
    return true;
  }
  bool VisitVarDecl(VarDecl *V) {
#ifdef MODULE_SAFETY_BUILTIN
    Found |= circleClassHasStaticArguments(V->getType()) || modulesafety::staticBorrowVariable(V);
#endif
    return true;
  }
};
bool marked(const Decl *D, llvm::StringRef tag) {
  for (auto *A : D->specific_attrs<AnnotateAttr>())
    if (A->getAnnotation() == tag)
      return true;
  return false;
}
bool markedImplicit(const Decl *D, llvm::StringRef Tag) {
  for (auto *A : D->specific_attrs<AnnotateAttr>())
    if (A->isImplicit() && A->getAnnotation() == Tag)
      return true;
  return false;
}
class Checker : public RecursiveASTVisitor<Checker> {
  ASTContext &C;
  Sema &Semantic;
  bool Safe, Unchecked = false;
  bool ForceTraversal = false;
  bool DependentBody = false;
  bool InUnsafeInitializer = false;
  bool InTrustedMemoryOp = false;
  unsigned OwnedConstruction = 0;
  const CXXMethodDecl *ActiveMethod = nullptr;
  const FunctionDecl *ActiveFunction = nullptr;
  std::set<const FunctionDecl *> CheckedBodies;
  std::set<const Decl *> ValidatedMetadata;
  std::vector<FunctionDecl *> PendingBodies;
  std::map<std::string, bool> Modes;
  using InitContext = std::tuple<const FunctionDecl *, bool, bool, bool, bool,
                                 unsigned>;
  modulesafety::InitListVisitSet<InitContext> InitLists;

  /// Whether a type's layout can be read now. A generated aggregate — a tuple,
  /// whose members are the elements as written — has no layout while an
  /// element is still a template parameter, and asking for one would recurse
  /// through the member that is not known yet.
  static bool layoutKnown(QualType T) {
    llvm::SmallVector<QualType, 16> Pending{T};
    llvm::SmallPtrSet<const Type *, 32> Seen;
    while (!Pending.empty()) {
      auto Current = Pending.pop_back_val();
      if (Current.isNull() || Current->isDependentType() ||
          Current->isInstantiationDependentType() || Current->isIncompleteType())
        return false;
      if (!Seen.insert(Current.getCanonicalType().getTypePtr()).second) continue;
      if (const auto *Array = Current->getAsArrayTypeUnsafe())
        Pending.push_back(Array->getElementType());
      if (auto *Record = Current->getAsCXXRecordDecl()) {
        for (auto *Field : Record->fields()) Pending.push_back(Field->getType());
        for (const auto &Base : Record->bases()) Pending.push_back(Base.getType());
      }
    }
    return true;
  }

  // A successful constant fold is not a runtime range proof: constexpr
  // functions can observe __builtin_constant_p and take another runtime path.
  // Only literal/data expressions and materialized immediate invocations may
  // exempt runtime arithmetic or conversion checks.
  bool stableIntegerConstant(const Expr *E, Expr::EvalResult &Result) {
    if (E->isValueDependent() ||
        !E->getType()->isIntegralOrEnumerationType())
      return false;
    class Stable : public RecursiveASTVisitor<Stable> {
      std::set<const VarDecl *> Seen;
    public:
      bool Valid = true;
      bool TraverseConstantExpr(ConstantExpr *Expr) {
        if (Expr->isImmediateInvocation()) return true;
        return TraverseStmt(Expr->getSubExpr());
      }
      bool TraverseUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *) {
        return true;
      }
      bool TraverseCXXNoexceptExpr(CXXNoexceptExpr *) { return true; }
      bool TraverseExpressionTraitExpr(ExpressionTraitExpr *) { return true; }
      bool VisitCallExpr(CallExpr *) { Valid = false; return true; }
      bool VisitCXXConstructExpr(CXXConstructExpr *) { Valid = false; return true; }
      bool VisitDeclRefExpr(DeclRefExpr *Expr) {
        auto *Var = dyn_cast<VarDecl>(Expr->getDecl());
        if (!Var || Var->isConstexpr()) return true;
        if (!Var->getType().getNonReferenceType().isConstQualified() ||
            !Var->hasInit()) {
          Valid = false;
          return true;
        }
        if (Seen.insert(Var).second) TraverseStmt(Var->getInit());
        return true;
      }
    } Visitor;
    Visitor.TraverseStmt(const_cast<Expr *>(E));
    return Visitor.Valid && E->EvaluateAsInt(Result, C) &&
           !Result.HasUndefinedBehavior && !Result.HasSideEffects;
  }
  bool constantSafe(const Expr *E) {
    Expr::EvalResult Result;
    return stableIntegerConstant(E, Result);
  }
  bool exactIntegerFloatConstant(const CastExpr *E) {
    if (E->getCastKind() != CK_IntegralToFloating || E->isValueDependent())
      return false;
    Expr::EvalResult Value;
    if (!stableIntegerConstant(E->getSubExpr(), Value))
      return false;
    llvm::APFloat Converted(C.getFloatTypeSemantics(E->getType()));
    const auto &I = Value.Val.getInt();
    return Converted.convertFromAPInt(I, I.isSigned(),
                                      llvm::APFloat::rmNearestTiesToEven) ==
           llvm::APFloat::opOK;
  }
  bool local(const Decl *D) const { return !D->isFromASTFile(); }
  bool ownsThis(const Expr *E) const {
    auto *This = dyn_cast<CXXThisExpr>(E->IgnoreParenImpCasts());
    if (!This || !ActiveMethod)
      return false;
    if (This->isTypeDependent())
      return !ActiveMethod->getParent()->isLambda();
    auto *Record = This->getType()->getPointeeType()->getAsCXXRecordDecl();
    return Record &&
           Record->getCanonicalDecl() == ActiveMethod->getParent()->getCanonicalDecl();
  }
  bool partialPolymorphicObject() const {
    return ActiveMethod && ActiveMethod->getParent()->isPolymorphic() &&
           isa<CXXConstructorDecl, CXXDestructorDecl>(ActiveMethod);
  }
  void checkPartialObjectArgument(Expr *E) {
    if (!partialPolymorphicObject())
      return;
    class ThisValue : public RecursiveASTVisitor<ThisValue> {
    public:
      bool Found = false;
      bool VisitCXXThisExpr(CXXThisExpr *) {
        Found = true;
        return true;
      }
      // Initialized member subobjects have their own complete lifetimes.
      bool TraverseMemberExpr(MemberExpr *) { return true; }
    } Visitor;
    Visitor.TraverseStmt(E);
    if (Visitor.Found)
      reject(E->getExprLoc(),
             "polymorphic object escapes during construction or destruction");
  }
  void reject(SourceLocation L, llvm::StringRef Message) {
    if (!Safe || Unchecked || InUnsafeInitializer || L.isInvalid())
      return;
    auto &D = C.getDiagnostics();
    D.Report(L, D.getCustomDiagID(
                    DiagnosticsEngine::Error,
                    "module-safety: %0 requires an explicit SAFETY_UNSAFE block"))
        << Message;
  }
  // Circle's `unsafe` qualifier names an entity whose representation and
  // operations the declaration itself has audited. The parser records the
  // qualifier as a compiler-owned annotation. `std2::unsafe_cell` and
  // `std2::manually_drop` are the corresponding compiler-provided wrappers:
  // their members are the storage those audited primitives exist to expose.
  bool unsafeObject(const Decl *D) const {
    if (!D)
      return false;
    if (marked(D, "safecpp.unsafe.object"))
      return true;
    const auto *Field = dyn_cast<FieldDecl>(D);
    if (!Field)
      return false;
    const auto *Owner = Field->getParent();
    if (!Owner)
      return false;
    auto IsAuditedWrapper = [](const CXXRecordDecl *R) {
      if (!R)
        return false;
      auto Name = R->getQualifiedNameAsString();
      return llvm::StringRef(Name).starts_with("std2::unsafe_cell") ||
             llvm::StringRef(Name).starts_with("std2::manually_drop");
    };
    // The wrapper's own field is the raw storage; a containing class may hold
    // the wrapper itself (for example `std2::atomic`). Constructing that
    // wrapper is the audited boundary, so the initializer traversal must treat
    // both the wrapper's fields and fields whose type is the wrapper as unsafe
    // storage.
    return IsAuditedWrapper(dyn_cast<CXXRecordDecl>(Owner)) ||
           IsAuditedWrapper(Field->getType()->getAsCXXRecordDecl());
  }
  bool unsafeUse(const Expr *E) const {
    if (!E)
      return false;
    E = E->IgnoreParenImpCasts();
    if (const auto *D = dyn_cast<DeclRefExpr>(E))
      return unsafeObject(D->getDecl());
    if (const auto *M = dyn_cast<MemberExpr>(E))
      return unsafeObject(M->getMemberDecl()) || unsafeUse(M->getBase());
    if (const auto *U = dyn_cast<UnaryOperator>(E))
      return unsafeUse(U->getSubExpr());
    if (const auto *C = dyn_cast<CastExpr>(E))
      return unsafeUse(C->getSubExpr());
    if (const auto *I = dyn_cast<ArraySubscriptExpr>(E))
      return unsafeUse(I->getBase());
    if (const auto *B = dyn_cast<BinaryOperator>(E))
      return unsafeUse(B->getLHS()) || unsafeUse(B->getRHS());
    if (const auto *Q = dyn_cast<ConditionalOperator>(E))
      return unsafeUse(Q->getTrueExpr()) || unsafeUse(Q->getFalseExpr());
    if (const auto *Call = dyn_cast<CXXMemberCallExpr>(E))
      return unsafeUse(Call->getImplicitObjectArgument());
    return false;
  }
  static bool auditedUnsafeWrapperFunction(const FunctionDecl *F) {
    if (!F)
      return false;
    const auto *Owner = dyn_cast<CXXRecordDecl>(F->getDeclContext());
    if (!Owner)
      return false;
    auto Name = Owner->getQualifiedNameAsString();
    return llvm::StringRef(Name).starts_with("std2::unsafe_cell") ||
           llvm::StringRef(Name).starts_with("std2::manually_drop");
  }
  static bool noRuntimeCheckParameter(const FunctionDecl *F) {
    if (!F)
      return false;
    for (const auto *P : F->parameters()) {
      const auto *R = P->getType()->getAsCXXRecordDecl();
      if (R && R->getQualifiedNameAsString() == "std2::no_runtime_check")
        return true;
    }
    return false;
  }
  bool storedBorrow(QualType T, std::set<const CXXRecordDecl *> &Seen) {
    if (T->isReferenceType())
      T = T->getPointeeType();
    // A record that declares a thread contract classifies its own storage: the
    // checked model asserts the contract instead of judging the representation
    // the library chose for it.
    if (auto *Contract = T->getAsCXXRecordDecl();
        Contract && (marked(Contract, "safecpp.send") ||
                     marked(Contract, "safecpp.sync") ||
                     marked(Contract, "safecpp.unsend") ||
                     marked(Contract, "safecpp.unsync")))
      return false;
    // The generated storage of a `choice` holds one alternative at a time and
    // is managed by the generated match and construction.
    if (auto *Choice = T->getAsCXXRecordDecl(); Choice &&
        (marked(Choice, "safecpp.native.choice") ||
         marked(Choice, "safecpp.native.choice.storage")))
      return false;
    if (layoutKnown(T) && !T->isFunctionType() &&
        C.getTypeAlignInChars(T) < C.getTypeAlignInChars(C.getCanonicalType(T)))
      return true;
    while (auto *Array = C.getAsArrayType(T))
      T = Array->getElementType();
    if (T->isVectorType() || T->isComplexType() || T->isMatrixType() ||
        T->isFixedPointType() || T->isAtomicType())
      return true;
    auto *Record = T->getAsCXXRecordDecl();
    if (!Record || !Record->hasDefinition() ||
        !Seen.insert(Record->getDefinition()).second)
      return false;
    Record = Record->getDefinition();
    // A system library type's representation is an implementation detail of
    // an audited native ABI. Its operations still need a safe classification;
    // judging its private storage here would reject every by-value use.
    if (C.getSourceManager().isInSystemHeader(Record->getLocation()))
      return false;
    if ((Record->isUnion() && !modulesafety::scalarUnion(Record)) ||
        Record->hasAttr<PackedAttr>() || Record->hasAttr<MaxFieldAlignmentAttr>())
      return true;
    for (auto *Field : Record->fields())
      if (Field->isMutable() || Field->hasAttr<PackedAttr>() ||
          storedBorrow(Field->getType(), Seen))
        return true;
    for (auto &Base : Record->bases())
      if (storedBorrow(Base.getType(), Seen))
        return true;
    return false;
  }
  void checkValueType(QualType T, SourceLocation L) {
    if (T.isNull() || T->isDependentType())
      return;
    if (T->isVectorType() || T->isComplexType() || T->isMatrixType() ||
        T->isFixedPointType() || T->isAtomicType())
      reject(L, "extended numeric or atomic type has no checked storage and "
                "arithmetic model");
    if (auto *R = T->getAsCXXRecordDecl();
        R && marked(R, "safecpp.unsafe.borrowed.sequence"))
      if (auto *Spec = dyn_cast<ClassTemplateSpecializationDecl>(R);
          Spec && Spec->getTemplateArgs().size() &&
          Spec->getTemplateArgs()[0].getKind() == TemplateArgument::Type) {
        auto Element = Spec->getTemplateArgs()[0].getAsType();
        if (!modulesafety::objectBorrow(Element) ||
            !modulesafety::threadSafeType(Element, true))
          reject(L, "borrowed sequences require readonly borrow-carrying elements");
      }
    if (auto *R = T->getAsCXXRecordDecl();
        R && marked(R, "safecpp.unsafe.exclusive.sequence"))
      if (auto *Spec = dyn_cast<ClassTemplateSpecializationDecl>(R);
          Spec && Spec->getTemplateArgs().size() &&
          Spec->getTemplateArgs()[0].getKind() == TemplateArgument::Type &&
          !modulesafety::objectBorrow(Spec->getTemplateArgs()[0].getAsType()))
        reject(L, "exclusive borrowed sequences require borrow-carrying elements");
    std::set<const CXXRecordDecl *> Seen;
    if (storedBorrow(T, Seen))
      reject(L, "value type contains unchecked numeric storage, a union, "
                "mutable field, unaligned storage, or stored reference");
  }
  bool inferTrivialSpecialMember(const FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
    const auto *Method = dyn_cast<CXXMethodDecl>(F);
    if (!Method || !Method->isImplicit() || !Method->isTrivial() ||
        Method->isDependentContext() ||
        (!isa<CXXConstructorDecl>(Method) && !isa<CXXDestructorDecl>(Method)))
      return false;
    auto *Parent = Method->getParent();
    if (!C.getLangOpts().CircleBorrowValues &&
        !circleRecordHasLifetimeBinderParameter(Parent) &&
        circleClassLifetimeNames(Parent).empty())
      return false;
    if (auto *Owner = F->getOwningModule()) {
      auto Mode = Modes.find(Owner->Name);
      if (!Owner->isNamedModule() || Mode == Modes.end() || !Mode->second)
        return false;
    } else if (!Safe || C.getSourceManager().isInSystemHeader(F->getLocation())) {
      return false;
    }
    for (auto *R : F->redecls())
      for (const auto *A : R->specific_attrs<AnnotateAttr>())
        if (!A->isImplicit() && A->getAnnotation() == "safecpp.unsafe")
          return false;
    bool Copy = isa<CXXConstructorDecl>(Method) &&
                cast<CXXConstructorDecl>(Method)->isCopyOrMoveConstructor();
    if (Copy && modulesafety::objectBorrow(C.getCanonicalTagType(Parent), true))
      return false;
    std::set<const CXXRecordDecl *> Seen;
    auto Subobjects = [&](auto &&Self, QualType Type) -> bool {
      if (Type.isVolatileQualified()) return false;
      if (auto *Array = C.getAsArrayType(Type))
        return Self(Self, Array->getElementType());
      auto *Record = Type->getAsCXXRecordDecl();
      if (!Record || !Record->hasDefinition()) return true;
      Record = Record->getDefinition();
      if (!Seen.insert(Record).second) return true;
      if (auto *Owner = Record->getOwningModule()) {
        auto Mode = Modes.find(Owner->Name);
        if (!Owner->isNamedModule() || Mode == Modes.end() || !Mode->second)
          return false;
      }
      for (auto *Member : Record->methods()) {
        bool Same = isa<CXXDestructorDecl>(Method) && isa<CXXDestructorDecl>(Member);
        if (auto *Ctor = dyn_cast<CXXConstructorDecl>(Method))
          if (auto *Child = dyn_cast<CXXConstructorDecl>(Member))
            Same |= Copy ? Child->isCopyOrMoveConstructor()
                         : Ctor->isDefaultConstructor() && Child->isDefaultConstructor();
        if (Same)
          for (const auto *A : Member->specific_attrs<AnnotateAttr>())
            if (!A->isImplicit() && A->getAnnotation() == "safecpp.unsafe")
              return false;
      }
      for (auto *Field : Record->fields())
        if (!Self(Self, Field->getType())) return false;
      for (const auto &Base : Record->bases())
        if (!Self(Self, Base.getType())) return false;
      return true;
    };
    return Subobjects(Subobjects, C.getCanonicalTagType(Parent));
#else
    return false;
#endif
  }
  bool inferCheckedDestructor(const FunctionDecl *F) {
    const auto *Dtor = dyn_cast_or_null<CXXDestructorDecl>(F);
    if (!Dtor || (!Dtor->isImplicit() && !Dtor->isDefaulted()) ||
        Dtor->isDependentContext()) return false;
    for (auto *R : F->redecls())
      for (const auto *A : R->specific_attrs<AnnotateAttr>())
        if (!A->isImplicit() && A->getAnnotation() == "safecpp.unsafe")
          return false;
    auto *Owner = Dtor->getParent()->getOwningModule();
    auto Mode = Owner ? Modes.find(Owner->Name) : Modes.end();
    return (Owner && Owner->isNamedModule() && Mode != Modes.end() && Mode->second) ||
           (Safe && !C.getSourceManager().isInSystemHeader(Dtor->getLocation()));
  }
  void markInferredSafe(FunctionDecl *F) {
    for (auto *R : F->redecls()) {
#ifdef MODULE_SAFETY_BUILTIN
      auto *Type = R->getType()->castAs<FunctionType>();
      R->setType(QualType(C.adjustFunctionType(
          Type, Type->getExtInfo().withModuleSafe(true)), 0));
#endif
      AttrVec Kept;
      for (auto *A : R->attrs())
        if (auto *Label = dyn_cast<AnnotateAttr>(A);
            !Label || !Label->isImplicit() || Label->getAnnotation() != "safecpp.unsafe")
          Kept.push_back(A);
      R->setAttrs(Kept);
      if (!marked(R, "safecpp.safe"))
        R->addAttr(AnnotateAttr::CreateImplicit(C, "safecpp.safe", nullptr, 0));
    }
  }
  void call(const FunctionDecl *F, SourceLocation L, bool Invocation = true) {
    if (const auto *Method = dyn_cast_or_null<CXXMethodDecl>(F);
        Method && markedImplicit(Method->getParent(), "safecpp.native.interface")) {
      auto &D = C.getDiagnostics();
      D.Report(L, D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle interface dispatch requires native impl lowering, which is not yet implemented"));
      return;
    }
    if (!F) {
      reject(L, "indirect or unresolved call");
      return;
    }
    bool InferredImplicit = false;
    // Instantiating an imported function body can create a special member
    // after the declaration-gathering pass. Use the same checked inference
    // here rather than relying on whether it existed when that pass ran.
    if (inferTrivialSpecialMember(F)) {
      markInferredSafe(const_cast<FunctionDecl *>(F));
      InferredImplicit = true;
    }
    if (inferCheckedDestructor(F)) {
      auto *Mutable = const_cast<CXXDestructorDecl *>(cast<CXXDestructorDecl>(F));
      markInferredSafe(Mutable);
      if (!Mutable->getDefinition() && !Mutable->isDeleted())
        Semantic.DefineImplicitDestructor(L, Mutable);
      InferredImplicit = true;
    }
    bool Unsafe = false, Trusted = false;
    for (auto *R : F->redecls()) {
      Unsafe |= marked(R, "safecpp.unsafe");
      Trusted |= marked(R, "safecpp.safe");
    }
    // A system library destructor releases a native ABI resource. Its body is
    // not a checked header; the owning safe wrapper (for example
    // `std2::unsafe_cell` or `std2::thread`) is where that obligation is
    // audited. Destroying the subobject itself is deterministic cleanup.
    if (isa<CXXDestructorDecl>(F) &&
        C.getSourceManager().isInSystemHeader(F->getLocation())) {
      Trusted = true;
      Unsafe = false;
    }
    // The checked object model supplies a small set of intrinsics: relocation
    // reads and writes and the address-and-length slice operations. Their
    // contracts are part of the compiler, and each one's operands are already
    // validated by the safe-function checks at the call site.
    llvm::StringRef Intrinsic;
    if (F->getDeclName().isIdentifier())
      Intrinsic = F->getName();
    if (Intrinsic == "__rel_read" || Intrinsic == "__rel_write" ||
        Intrinsic == "__slice_pointer" || Intrinsic == "__builtin_trap" ||
        Intrinsic == "__builtin_abort" ||
        Intrinsic == "memcpy" || Intrinsic == "memmove" ||
        Intrinsic == "memset" || Intrinsic == "memcmp" ||
        Intrinsic.starts_with("__builtin_circle_slice_")) {
      Trusted = true;
      Unsafe = false;
    }
#ifdef MODULE_SAFETY_BUILTIN
    if (F->isImplicit() &&
        markedImplicit(F, "safecpp.native.deferred.format")) {
      Trusted = true;
      Unsafe = false;
    }
#endif
    // A drop-only destructor's contract is exactly that it destroys the
    // sequence it owns. `std::destroy_n` is the library's implementation of
    // that cleanup; the destructor's own drop classification is the audit.
    if (F->getQualifiedNameAsString() == "std::destroy_n" && ActiveFunction &&
        isa<CXXDestructorDecl>(ActiveFunction) &&
        marked(ActiveFunction, "safecpp.drop.only")) {
      Trusted = true;
      Unsafe = false;
    }
    // A choice's generated move assignment is the compiler's drop-and-replace
    // operation. The call site has already validated the source value, and
    // CodeGen destroys the active alternative before relocating the source.
    if (auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && Method->isImplicit() && Method->isMoveAssignmentOperator() &&
        marked(Method->getParent(), "safecpp.native.choice")) {
      Trusted = true;
      Unsafe = false;
    }
    // `std2::unsafe_cell` and `std2::manually_drop` are the audited wrappers
    // whose representation deliberately contains an unsafe type. Their
    // constructors and accessors are the boundary contract; the legacy type's
    // operations are not exposed to safe callers outside the wrapper.
    if (auditedUnsafeWrapperFunction(F) ||
        auditedUnsafeWrapperFunction(ActiveFunction)) {
      Trusted = true;
      Unsafe = false;
    }
    if (Invocation && (Unsafe || !Trusted))
      reject(L, "call to unsafe or unclassified function '" +
                    F->getQualifiedNameAsString() + "'");
    if (Safe && !DependentBody && Trusted && !Unsafe &&
        (InferredImplicit || F->isTemplateInstantiation() ||
         isa<ClassTemplateSpecializationDecl>(F->getDeclContext()))) {
      if (!F->getDefinition() && !F->isTrivial() && !F->isDeleted())
        if (auto *Pattern = F->getTemplateInstantiationPattern();
            Pattern && Pattern->hasBody()) {
          // Parameter destruction can require checking a specialization which
          // ordinary syntax-only compilation has not instantiated yet.
          Semantic.InstantiateFunctionDefinition(L, const_cast<FunctionDecl *>(F), true,
                                                 true, true);
          if (C.getDiagnostics().hasErrorOccurred())
            return;
          classify(const_cast<DeclContext *>(F->getDeclContext()));
        }
      if (auto *Definition = F->getDefinition())
        PendingBodies.push_back(const_cast<FunctionDecl *>(Definition));
      else if (!F->isTrivial() && !F->isDeleted())
        reject(L, "template instantiation has no checkable definition");
    }
    // A non-dependent class specialization can be constructed in a still
    // dependent function body. Ordinary instantiation may defer its body, but
    // field contracts must inspect the actual member initializers, including
    // when the caller has explicit unsafe permission.
    if (auto *Ctor = dyn_cast_or_null<CXXConstructorDecl>(F);
        Ctor && !Ctor->isDependentContext() && !Ctor->getDefinition() &&
        !Ctor->isDeleted() &&
        (modulesafety::hasStaticLifetimeFields(C.getCanonicalTagType(Ctor->getParent())) ||
         modulesafety::hasClassLifetimeFields(C.getCanonicalTagType(Ctor->getParent())))) {
      if (auto *Pattern = Ctor->getTemplateInstantiationPattern();
          Pattern && Pattern->hasBody()) {
        Semantic.InstantiateFunctionDefinition(L, const_cast<CXXConstructorDecl *>(Ctor),
                                               true, true, true);
        classify(const_cast<DeclContext *>(Ctor->getDeclContext()));
        if (auto *Definition = Ctor->getDefinition())
          PendingBodies.push_back(const_cast<FunctionDecl *>(Definition));
      }
    }
    if (auto *Ctor = dyn_cast_or_null<CXXConstructorDecl>(F);
        Ctor && !Ctor->isCopyOrMoveConstructor() &&
        (modulesafety::hasStaticLifetimeFields(C.getCanonicalTagType(Ctor->getParent())) ||
         modulesafety::hasClassLifetimeFields(C.getCanonicalTagType(Ctor->getParent()))))
      for (auto *Field : Ctor->getParent()->fields()) {
        if (!modulesafety::staticLifetimeField(Field) && !modulesafety::fieldClassRegion(Field)) continue;
        bool Initialized = Field->hasInClassInitializer();
        for (auto *Init : Ctor->inits())
          Initialized |= Init->isMemberInitializer() && Init->getMember() == Field &&
                         !isa<ImplicitValueInitExpr>(Init->getInit());
        if (!Initialized)
          C.getDiagnostics().Report(L,
              C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error, "module-safety: %0"))
                << (modulesafety::staticLifetimeField(Field)
                    ? "static field requires an initialized permanent borrow"
                    : "class field requires an initialized borrow");
      }

  }

public:
  Checker(ASTContext &C, Sema &Semantic, bool S, Module *M,
          std::map<std::string, bool> Modes)
      : C(C), Semantic(Semantic), Safe(S), Modes(std::move(Modes)) {
    // A plain translation unit has no module name; the empty name keys the
    // unit's own mode, which is what a call from one of its functions needs.
    this->Modes[M ? M->Name : std::string()] = S;
  }
  void validatePendingBodies() {
    ForceTraversal = true;
    for (size_t I = 0; I < PendingBodies.size(); ++I)
      TraverseDecl(PendingBodies[I]);
    ForceTraversal = false;
  }
  bool shouldVisitTemplateInstantiations() const { return true; }
  bool shouldVisitImplicitCode() const { return true; }
  bool dataTraverseStmtPre(Stmt *S) {
    return InitLists.enter(S, {ActiveFunction, Unchecked, DependentBody,
                              InUnsafeInitializer, InTrustedMemoryOp,
                              OwnedConstruction});
  }
  // Gather first; otherwise call-before-definition and implicit class/lambda
  // members depend on the order in which the visitor happens to reach them.
  void classify(DeclContext *DC) {
    class Gather : public RecursiveASTVisitor<Gather> {
      Checker &Check;
      modulesafety::InitListVisitSet<> InitLists;

    public:
      explicit Gather(Checker &Check) : Check(Check) {}
      std::set<FunctionDecl *> Functions;
      bool VisitDecl(Decl *D) { return Check.VisitDecl(D); }
      bool shouldVisitTemplateInstantiations() const { return true; }
      bool shouldVisitImplicitCode() const { return true; }
      bool dataTraverseStmtPre(Stmt *S) { return InitLists.enter(S); }
      bool TraverseDecl(Decl *D) {
        if (!D || D->isFromASTFile())
          return true;
        return RecursiveASTVisitor::TraverseDecl(D);
      }
      bool VisitFunctionDecl(FunctionDecl *F) {

        Functions.insert(F);
        return true;
      }
      bool VisitCallExpr(CallExpr *E) {
        if (E->isTypeDependent() || E->isValueDependent())
          return true;
        if (auto *F = E->getDirectCallee(); F && !F->isFromASTFile())
          Functions.insert(F);
        return true;
      }
      bool VisitDeclRefExpr(DeclRefExpr *E) {
        if (auto *F = dyn_cast<FunctionDecl>(E->getDecl()); F && !F->isFromASTFile())
          Functions.insert(F);
        return true;
      }
      bool VisitCXXConstructExpr(CXXConstructExpr *E) {
        if (!E->getConstructor()->isFromASTFile())
          Functions.insert(E->getConstructor());
        return true;
      }
    } G(*this);
    G.TraverseDecl(Decl::castFromDeclContext(DC));
#ifdef MODULE_SAFETY_BUILTIN
    // A method that relocates its receiver consumes it, so every caller must
    // treat the receiver as moved. The mark is written onto the declaration so
    // it travels with an imported module.
    for (auto *F : G.Functions) {
      auto *Method = dyn_cast<CXXMethodDecl>(F);
      if (!Method || Method->isStatic() || Method->isImplicit() || !F->getBody())
        continue;
      if (marked(F, "safecpp.native.consumes.receiver"))
        continue;
      class RelocatesReceiver : public RecursiveASTVisitor<RelocatesReceiver> {
        modulesafety::InitListVisitSet<> InitLists;
      public:
        const CXXMethodDecl *Method;
        bool Found = false;
        explicit RelocatesReceiver(const CXXMethodDecl *M) : Method(M) {}
        // The relocation the checker looks for is in the generated `match`
        // lowering, which is implicit code.
        bool shouldVisitImplicitCode() const { return true; }
        bool dataTraverseStmtPre(Stmt *S) { return InitLists.enter(S); }
        bool shouldVisitTemplateInstantiations() const { return true; }
        bool VisitUnaryOperator(UnaryOperator *E) {
          if (E->getOpcode() != UO_Relocate)
            return true;
          const Expr *Place = E->getSubExpr()->IgnoreParenImpCasts();
          for (;;) {
            if (auto *Member = dyn_cast<MemberExpr>(Place)) {
              Place = Member->getBase()->IgnoreParenImpCasts();
              continue;
            }
            if (auto *U = dyn_cast<UnaryOperator>(Place);
                U && (U->getOpcode() == UO_Deref ||
                      U->getOpcode() == UO_Borrow ||
                      U->getOpcode() == UO_SharedBorrow)) {
              Place = U->getSubExpr()->IgnoreParenImpCasts();
              continue;
            }
            if (auto *Cast = dyn_cast<ImplicitCastExpr>(Place);
                Cast && Cast->getCastKind() == CK_BitCast) {
              Place = Cast->getSubExpr()->IgnoreParenImpCasts();
              continue;
            }
            break;
          }
          if (isa<CXXThisExpr>(Place))
            Found = true;
          if (auto *Ref = dyn_cast<DeclRefExpr>(Place))
            if (auto *Var = dyn_cast<VarDecl>(Ref->getDecl());
                Var && Var->getDeclContext() == Method) {
              // The receiver is the object parameter, whichever way this
              // frontend represents it: as a parameter of the receiver's own
              // class, taken by value or by borrow.
              QualType Receiver = Var->getType().getNonReferenceType();
              if (auto *Borrow = Receiver->getAs<BorrowValueType>())
                Receiver = Borrow->getPointeeType();
              Found |= Receiver.getUnqualifiedType()->getAsCXXRecordDecl() ==
                       Method->getParent();
            }
          return true;
        }
      } Scan(Method);
      Scan.TraverseStmt(F->getBody());
      if (Scan.Found)
        F->addAttr(AnnotateAttr::CreateImplicit(
            C, "safecpp.native.consumes.receiver", nullptr, 0));
    }
#endif
    for (auto *F : G.Functions) {
      VisitDecl(F);
      auto *Pattern = F->getTemplateInstantiationPattern();
      auto *Owner = F->getOwningModule();
      if (!Owner && Pattern)
        Owner = Pattern->getOwningModule();
      // A declaration attached to a safe named module has a safe contract.
      // Definitions in implementation units are independently checked; missing
      // definitions fail at link time. Global-fragment/C-linkage declarations
      // have no such module contract.
      bool OwnerSafe = false;
      if (Owner) {
        auto Found = Modes.find(Owner->Name);
        OwnerSafe = Found != Modes.end() && Found->second;
      }
      bool PlainSafe = false;
#ifdef MODULE_SAFETY_BUILTIN
      // Native function types carry the checked effect for an ordinary Circle
      // TU too. Do not overwrite it with an unsafe annotation merely because
      // there is no named module. Global-fragment/header declarations retain
      // their independent classification until their bodies are checked.
      if (!Owner && Safe && F->getLocation().isValid() &&
          !C.getSourceManager().isInSystemHeader(F->getLocation()))
        if (const auto *FT = F->getType()->getAs<FunctionType>()) {
          PlainSafe = FT->getExtInfo().getModuleSafe();
          if (const auto *Method = dyn_cast<CXXMethodDecl>(F))
            PlainSafe |= Method->getParent()->isLambda();
        }
      if (inferTrivialSpecialMember(F) || inferCheckedDestructor(F)) {
        PlainSafe = true;
        markInferredSafe(F);
      }
#endif
      bool U = (!OwnerSafe && !PlainSafe) ||
               (Owner && !Owner->isNamedModule()) || F->isExternC() ||
               F->hasAttr<AsmLabelAttr>() || F->hasAttr<AliasAttr>() ||
               F->hasAttr<IFuncAttr>() || F->hasAttr<WeakRefAttr>();
      for (auto *R : F->redecls())
        for (auto *A : R->specific_attrs<AnnotateAttr>())
          U |= !A->isImplicit() && A->getAnnotation() == "safecpp.unsafe";
      // A compiler-defaulted assignment returns its receiver even when the
      // operation itself is unsafe. Its result provenance is independent of
      // the effect classification of its subobjects.
      if (auto *Method = dyn_cast<CXXMethodDecl>(F);
            Method && !Method->isStatic() &&
            ((!U && Method->getParent()->isLambda()) ||
             (Method->isDefaulted() && (Method->isCopyAssignmentOperator() ||
                                        Method->isMoveAssignmentOperator()))) &&
            (F->getReturnType()->isReferenceType() ||
             modulesafety::objectBorrow(F->getReturnType())) &&
            modulesafety::borrowedParameters(F).empty() &&
            !marked(F, "safecpp.borrow.this"))
          F->addAttr(
              AnnotateAttr::CreateImplicit(C, "safecpp.borrow.this", nullptr, 0));
      if (!marked(F, "safecpp.safe") && !marked(F, "safecpp.unsafe"))
        F->addAttr(AnnotateAttr::CreateImplicit(
            C, U ? "safecpp.unsafe" : "safecpp.safe", nullptr, 0));
    }
  }
  bool TraverseDecl(Decl *D) {
    if (!D)
      return true;
    if (auto *Method = dyn_cast<CXXMethodDecl>(D);
        Method && Method->isDefaulted() && Method->isTrivial() &&
        modulesafety::scalarUnion(Method->getParent()))
      return true;
    // Headers in the global module fragment are untrusted declarations, not
    // safe module definitions. Their calls still require an unsafe boundary.
    auto *Owner = D->getOwningModule();
    bool CheckedHeader = false;
#ifdef MODULE_SAFETY_BUILTIN
    CheckedHeader = Safe && !C.getSourceManager().isInSystemHeader(D->getLocation());
#endif
    if ((!Owner || !Owner->isNamedModule()) && D->getLocation().isValid() &&
        !C.getSourceManager().isInMainFile(D->getLocation()) && !CheckedHeader)
      return true;
    // Recheck instantiated imported templates: their generic definition may
    // become dangerous only after substituting a signed or pointer type.
    auto *Specialization = dyn_cast<FunctionDecl>(D);
    bool Instantiation =
        Specialization &&
        Specialization->getTemplateSpecializationKind() == TSK_ImplicitInstantiation;
    if (!local(D) && !Instantiation && !ForceTraversal)
      return true;
    if (Specialization && Specialization->doesThisDeclarationHaveABody() &&
        !CheckedBodies.insert(Specialization).second)
      return true;
    bool Saved = Unchecked;
    bool SavedDependent = DependentBody;
    bool SavedUnsafeInitializer = InUnsafeInitializer;
    unsigned SavedOwnedConstruction = OwnedConstruction;
    auto *SavedMethod = ActiveMethod;
    const FunctionDecl *SavedFunction = ActiveFunction;
    auto *F = dyn_cast<FunctionDecl>(D);
    if (F) {
      // The destructor the checked object model generates for a `choice` ends
      // the active alternative's lifetime, and its constructor selects the
      // definition's default alternative; both bodies are compiler-owned, and
      // the alternatives they name are checked where the choice is defined.
      Unchecked = marked(F, "safecpp.unsafe") ||
                  marked(F, "safecpp.native.choice.destructor") ||
                  marked(F, "safecpp.native.choice.constructor") || !Safe;
      DependentBody = F->isDependentContext();
      OwnedConstruction = marked(F, "safecpp.validate.owned.construction")      ? 1u
                          : marked(F, "safecpp.validate.regional.construction") ? 2u
                                                                                : 0u;
      ActiveMethod = dyn_cast<CXXMethodDecl>(F);
      ActiveFunction = F;
    }
    bool Result = RecursiveASTVisitor::TraverseDecl(D);
    if (F && Safe && !Unchecked &&
        !auditedUnsafeWrapperFunction(F))
      modulesafety::analyzeFunction(
          C, F, [this](const FunctionDecl *D, SourceLocation L) { call(D, L); });
    else if (F && F->doesThisDeclarationHaveABody() && !F->isDependentContext()) {
      StaticContractCalls Calls;
      Calls.TraverseDecl(F);
      if (Calls.Found || modulesafety::returnsStatic(F) || modulesafety::returnsGenerative(F) || modulesafety::storedClassResultRegion(F) ||
          !modulesafety::borrowedParameters(F).empty() || marked(F, "safecpp.borrow.this"))
        modulesafety::analyzeFunction(C, F,
            [](const FunctionDecl *, SourceLocation) {}, true);
    }
    Unchecked = Saved;
    DependentBody = SavedDependent;
    InUnsafeInitializer = SavedUnsafeInitializer;
    OwnedConstruction = SavedOwnedConstruction;
    ActiveMethod = SavedMethod;
    ActiveFunction = SavedFunction;
    return Result;
  }
  bool TraverseConstructorInitializer(CXXCtorInitializer *I) {
    bool Saved = InUnsafeInitializer;
    InUnsafeInitializer |= I->isMemberInitializer() &&
                           unsafeObject(I->getMember());
    bool Result = RecursiveASTVisitor::TraverseConstructorInitializer(I);
    InUnsafeInitializer = Saved;
    return Result;
  }
  bool TraverseCallExpr(CallExpr *E) {
    // `memcpy`/`memmove`/`memset` relocate the representation itself. A
    // container keeps element lifetimes in its declared region, so the copy
    // is the audited relocation step rather than an erasure of the handle.
    bool Saved = InTrustedMemoryOp;
    if (const FunctionDecl *Callee = E->getDirectCallee())
      if (const IdentifierInfo *Id = Callee->getIdentifier()) {
        auto Name = Id->getName();
        InTrustedMemoryOp |= Name == "memcpy" || Name == "memmove" ||
                             Name == "memset";
      }
    bool Result = RecursiveASTVisitor::TraverseCallExpr(E);
    InTrustedMemoryOp = Saved;
    return Result;
  }
  bool TraverseLambdaExpr(LambdaExpr *L) {
    for (auto &Capture : L->captures())
      if (Capture.capturesThis())
        reject(L->getBeginLoc(), "escaping-capable reference capture; capture "
                                 "an owned value instead");
    bool Saved = Unchecked;
    Unchecked = !Safe;
    bool Result = RecursiveASTVisitor::TraverseLambdaExpr(L);
    Unchecked = Saved;
    return Result;
  }
  bool TraverseIfStmt(IfStmt *S) {
    auto *V = S->getConditionVariable();
    if (!V || !marked(V, "safecpp.unsafe.scope"))
      return RecursiveASTVisitor::TraverseIfStmt(S);
    TraverseStmt(S->getInit());
    TraverseDecl(V);
    TraverseStmt(S->getCond());
    bool Saved = Unchecked;
    Unchecked = true;
    TraverseStmt(S->getThen());
    Unchecked = Saved;
    TraverseStmt(S->getElse());
    return true;
  }
  bool VisitDecl(Decl *D) {
    if (!ValidatedMetadata.insert(D).second)
      return true;
    for (auto *A : D->specific_attrs<AnnotateAttr>()) {
      auto Text = A->getAnnotation();
      if (!A->isImplicit() && A->getLocation().isValid() &&
          !C.getSourceManager().isLoadedSourceLocation(A->getLocation()) &&
          (Text == "safecpp.safe" || Text.starts_with("safecpp.module.") ||
           Text.starts_with("safecpp.native.") ||
           Text.starts_with("safecpp.thread."))) {
        auto &Diags = C.getDiagnostics();
        Diags.Report(D->getLocation(),
                     Diags.getCustomDiagID(DiagnosticsEngine::Error,
                                           "module-safety: compiler-owned safety "
                                           "metadata cannot be written in source"));
      }
    }
    return true;
  }
  bool VisitFunctionDecl(FunctionDecl *F) {
    if (modulesafety::storedClassResultRegion(F))
      for (auto *A : F->specific_attrs<AnnotateAttr>())
        if (!A->isImplicit() &&
            (A->getAnnotation().starts_with("safecpp.borrow.from:") ||
             A->getAnnotation().starts_with("safecpp.borrow.lifetime:") ||
             A->getAnnotation() == "safecpp.borrow.this" ||
             A->getAnnotation() == "safecpp.borrow.static"))
          C.getDiagnostics().Report(F->getLocation(),
              C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
                "module-safety: class result lifetime cannot mix declaration borrow attributes"));
    if (const auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && !F->isImplicit() &&
        markedImplicit(Method->getParent(), "safecpp.native.impl") &&
        !Method->getParent()->isDependentContext() &&
        !markedImplicit(Method, "safecpp.native.impl.method")) {
      auto &D = C.getDiagnostics();
      D.Report(F->getLocation(), D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle impl method contract binding is not yet implemented"));
    }
    if (const auto *Method = dyn_cast<CXXMethodDecl>(F);
        Method && markedImplicit(Method->getParent(), "safecpp.native.interface") &&
        F->doesThisDeclarationHaveABody()) {
      auto &D = C.getDiagnostics();
      D.Report(F->getLocation(), D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle interface default method lowering is not yet implemented"));
    }
    bool ExplicitUnsafe = false, PreviouslySafe = false;
    for (auto *R : F->redecls()) {
      PreviouslySafe |= marked(R, "safecpp.safe");
      bool DeclaredUnsafe = false;
      for (auto *A : R->specific_attrs<AnnotateAttr>())
        DeclaredUnsafe |= !A->isImplicit() && A->getAnnotation() == "safecpp.unsafe" &&
                          A->getLocation().isValid() && R->getEndLoc().isValid() &&
                          (A->getLocation() == R->getEndLoc() ||
                           C.getSourceManager().isBeforeInTranslationUnit(
                               A->getLocation(), R->getEndLoc()));
      auto *Owner = R->getOwningModule();
      auto Mode = Owner ? Modes.find(Owner->Name) : Modes.end();
      if (!R->isImplicit() && Owner && Owner->isNamedModule() && Mode != Modes.end() &&
          Mode->second && !R->isExternC() && !DeclaredUnsafe)
        PreviouslySafe = true;
      for (auto *A : R->specific_attrs<AnnotateAttr>())
        ExplicitUnsafe |= !A->isImplicit() && A->getAnnotation() == "safecpp.unsafe";
    }
    if (ExplicitUnsafe && PreviouslySafe)
      C.getDiagnostics().Report(F->getLocation(),
                                C.getDiagnostics().getCustomDiagID(
                                    DiagnosticsEngine::Error,
                                    "module-safety: an unsafe definition "
                                    "cannot weaken a declared safe interface"));
    if (F->hasAttr<NonNullAttr>() || F->hasAttr<ReturnsNonNullAttr>() ||
        F->hasAttr<AssumeAlignedAttr>() || F->hasAttr<OMPAssumeAttr>() ||
        F->hasAttr<PureAttr>() || F->hasAttr<ConstAttr>() ||
        F->hasAttr<NoThrowAttr>() || F->hasAttr<AllocAlignAttr>() ||
        F->hasAttr<AllocSizeAttr>() || F->hasAttr<RestrictAttr>())
      reject(F->getLocation(), "unchecked optimizer precondition attribute");
    if (F->hasAttr<WeakAttr>() || F->hasAttr<WeakImportAttr>() ||
        F->hasAttr<NakedAttr>() || F->hasAttr<ReturnsTwiceAttr>())
      reject(F->getLocation(), "optional symbol or unmodeled control-flow ABI");
    if (F->hasAttr<ConstructorAttr>() || F->hasAttr<DestructorAttr>())
      reject(F->getLocation(), "automatic extension callbacks require an "
                               "audited initialization boundary");
    if (marked(F, "safecpp.stores.self"))
      if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
          !Ctor ||
          !modulesafety::pinnedStorage(C.getCanonicalTagType(Ctor->getParent())))
        reject(F->getLocation(), "self storage contracts require a pinned constructor");
    if (Safe && modulesafety::hasAdoptionContract(F)) {
      auto *Method = dyn_cast<CXXMethodDecl>(F);
      bool Valid = Method && !Method->isStatic();
      for (auto *R : F->redecls())
        for (auto *A : R->specific_attrs<AnnotateAttr>()) {
          if (A->isInherited()) continue;
          auto Tag = A->getAnnotation();
          if (!Tag.consume_front("safecpp.unsafe.adopts.borrow:")) continue;
          bool Found = false;
          for (auto *P : R->parameters())
            if (P->getName() == Tag) {
              Found = true;
              Valid &= P->getType()->isDependentType() ||
                       P->getType()->isReferenceType() ||
                       modulesafety::objectBorrow(P->getType());
            }
          Valid &= Found;
        }
      if (!Valid)
        C.getDiagnostics().Report(F->getLocation(),
            C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
              "module-safety: invalid borrowed-element owner contract"));
    }
    if (F->getReturnType()->isDependentType())
      return true;
    if (auto *Method = dyn_cast<CXXMethodDecl>(F);
        modulesafety::consumingReceiver(Method) && !F->isDependentContext()) {
      auto T = C.getCanonicalTagType(Method->getParent());
      if (Method->isConst() || Method->isVolatile())
        reject(F->getLocation(), "consuming receiver requires an unqualified owner");
      if (modulesafety::pinnedStorage(T))
        reject(F->getLocation(), "consuming receiver cannot consume pinned storage");
      if (!modulesafety::movedDropSafe(T))
        reject(F->getLocation(), "consuming receiver requires a trivial or audited "
                                 "moved-from destructor");
      if (marked(F, "safecpp.borrow.this"))
        reject(F->getLocation(), "consuming receiver cannot return a borrow of itself");
    }
    if (!F->isDependentContext())
      for (auto *A : F->specific_attrs<AnnotateAttr>())
        if (A->getAnnotation().starts_with("safecpp.transfers.borrow:")) {
          auto Index = modulesafety::transferredBorrow(F);
          auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
          bool Valid = Ctor && Index && *Index < F->getNumParams();
          if (Valid) {
            auto T = F->getParamDecl(*Index)->getType();
            Valid = T->isRValueReferenceType() &&
                    modulesafety::objectBorrow(T->getPointeeType(), true) &&
                    modulesafety::movedDropSafe(T->getPointeeType()) &&
                    modulesafety::objectBorrow(C.getCanonicalTagType(Ctor->getParent()),
                                               true) &&
                    modulesafety::storedParameters(F) == std::set<unsigned>{*Index};
          }
          if (!Valid)
            reject(F->getLocation(), "borrow transfer requires an exclusive rvalue "
                                     "source and a moved-from destructor contract");
        }
    std::optional<std::set<unsigned>> Stores;
    for (auto *R : F->redecls()) {
      std::set<unsigned> Sources;
      bool Found = false;
      for (auto *A : R->specific_attrs<AnnotateAttr>()) {
        if (A->isInherited())
          continue;
        auto Text = A->getAnnotation();
        if (!Text.starts_with("safecpp.stores.borrow:") &&
            !Text.starts_with("safecpp.stores.lifetime:"))
          continue;
        Found = true;
        auto Resolved = modulesafety::contractParameters(
            R, Text, "safecpp.stores.borrow:", "safecpp.stores.lifetime:");
        bool Valid = !Resolved.empty();
        for (auto I : Resolved) {
          auto T = F->getParamDecl(I)->getType();
          Valid &= T->isDependentType() || T->isReferenceType() ||
                   modulesafety::objectBorrow(T);
          Sources.insert(I);
        }
        if (!Valid || !isa<CXXConstructorDecl>(F))
          reject(F->getLocation(), "invalid constructor borrow storage contract");
      }
      if (Found) {
        if (auto *Ctor = dyn_cast<CXXConstructorDecl>(F);
            Ctor && !Ctor->isDependentContext() &&
            !modulesafety::objectBorrow(C.getCanonicalTagType(Ctor->getParent())))
          reject(F->getLocation(), "constructor borrow storage contract "
                                   "requires visible borrow-carrying fields");
        if (Stores && *Stores != Sources)
          reject(F->getLocation(),
                 "constructor lifetime contract changed across redeclarations");
        Stores = Sources;
      }
    }
    std::optional<unsigned> Contract;
    bool ThisContract = false, StaticContract = modulesafety::returnsStatic(F),
         InvalidContract = false;
    std::optional<std::set<unsigned>> DeclaredRegions;
    for (auto *R : F->redecls()) {
      std::set<unsigned> Regions;
      for (auto *A : R->specific_attrs<AnnotateAttr>()) {
        if (A->isInherited())
          continue;
        auto Text = A->getAnnotation();
        if (Text == "safecpp.borrow.this")
          ThisContract = true;
        if (!Text.starts_with("safecpp.borrow.from:") &&
            !Text.starts_with("safecpp.borrow.lifetime:"))
          continue;
        auto Resolved = modulesafety::contractParameters(
            R, Text, "safecpp.borrow.from:", "safecpp.borrow.lifetime:");
        if (Resolved.empty())
          InvalidContract = true;
        for (auto I : Resolved) {
          Contract = I;
          Regions.insert(I);
        }
      }
      if (!Regions.empty()) {
        if (DeclaredRegions && *DeclaredRegions != Regions)
          InvalidContract = true;
        DeclaredRegions = Regions;
      }
    }
    if (StaticContract && (Contract || ThisContract))
      InvalidContract = true;
    if (ThisContract &&
        (Contract || !isa<CXXMethodDecl>(F) || cast<CXXMethodDecl>(F)->isStatic()))
      InvalidContract = true;
    bool BorrowResult = F->getReturnType()->isReferenceType() ||
                        modulesafety::objectBorrow(F->getReturnType());
#ifdef MODULE_SAFETY_BUILTIN
    BorrowResult |= circleSimpleClassValueRegion(F->getReturnType()) != nullptr;
#endif
    if ((Contract || ThisContract || StaticContract) && !BorrowResult)
      InvalidContract = true;
#ifdef MODULE_SAFETY_BUILTIN
    if (auto *Proto = F->getType()->getAs<FunctionProtoType>();
        Proto && marked(F, "safecpp.native.lifetime.binders"))
      if (DeclaredRegions || ThisContract || marked(F, "safecpp.borrow.static"))
        reject(F->getLocation(), "native lifetime binding cannot mix declaration borrow attributes");
#endif
    if (InvalidContract)
      reject(F->getLocation(), "inconsistent or invalid borrow lifetime contract");
    if (!F->isDeleted())
      checkValueType(F->getReturnType(), F->getLocation());
    // A dependent result cannot be checked for lifetime elision yet: the
    // return type still names a template parameter, so the binder rules are
    // applied when the specialization is instantiated. Reporting here would
    // reject every generic accessor that returns `T^`.
    if (!F->isDeleted() && BorrowResult &&
        !F->getReturnType()->isDependentType()) {
#ifdef MODULE_SAFETY_BUILTIN
      if (C.getLangOpts().CircleBorrowValues && F->getReturnType()->isRecordType() &&
          circleClassLifetimeBinding(F->getReturnType()) &&
          !circleClassHasStaticArguments(F->getReturnType()) &&
          !circleSimpleClassValueRegion(F->getReturnType()) &&
          !modulesafety::multiRegionClassValue(F->getReturnType()))
        C.getDiagnostics().Report(F->getLocation(),
            C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
              "module-safety: non-static class-value result lifetimes are not yet modeled"));
#endif
      auto Params = modulesafety::borrowedParameters(F);
      bool Valid = !Params.empty() || StaticContract || modulesafety::returnsGenerative(F);
      for (auto I : Params)
        Valid &= I < F->getNumParams() &&
                 // A dependent carrier's field shape is checked again on
                 // specialization, just like a dependent result type.
                 (F->getParamDecl(I)->getType()->isDependentType() ||
                  F->getParamDecl(I)->getType()->isReferenceType() ||
                  modulesafety::objectBorrow(F->getParamDecl(I)->getType())
#ifdef MODULE_SAFETY_BUILTIN
                  || circleSimpleClassValueRegion(F->getParamDecl(I)->getType())
#endif
                  );
      if (!Valid && !(isa<CXXMethodDecl>(F) && marked(F, "safecpp.borrow.this"))) {
#ifdef MODULE_SAFETY_BUILTIN
        if (C.getLangOpts().CircleBorrowValues)
          C.getDiagnostics().Report(F->getLocation(),
              C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
                "module-safety: native borrow result requires a checked lifetime contract"));
        else
#endif
          reject(F->getLocation(), "borrow result without a checked lifetime contract");
      }
    }
    return true;
  }
  bool VisitFieldDecl(FieldDecl *F) {
    if (markedImplicit(F->getParent(), "safecpp.native.impl")) {
      auto &D = C.getDiagnostics();
      D.Report(F->getLocation(), D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle impl cannot declare object storage fields"));
    }
    if (markedImplicit(F->getParent(), "safecpp.native.interface")) {
      auto &D = C.getDiagnostics();
      D.Report(F->getLocation(), D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle interface cannot declare object storage fields"));
    }
#ifdef MODULE_SAFETY_BUILTIN
    bool Projected = false;
    bool MemberPack = false;
    for (const auto *A : F->specific_attrs<AnnotateAttr>())
      {
        Projected |= A->isImplicit() &&
            A->getAnnotation() == "safecpp.native.lifetime_projection";
        // A member pack's field is generated from the enclosing template's
        // type arguments. Those arguments carry the lifetime of each element;
        // the generated field has no separate binder of its own.
        MemberPack |= A->isImplicit() &&
            A->getAnnotation().starts_with("safecpp.native.member_pack:");
      }
    if (!Projected)
    {
      auto *Owner = dyn_cast<CXXRecordDecl>(F->getParent());
      // A choice payload is stored in a generated union; its lifetime binder
      // belongs to the enclosing choice, not to that representation record.
      if (Owner && markedImplicit(Owner, "safecpp.native.choice.storage"))
        Owner = dyn_cast_or_null<CXXRecordDecl>(Owner->getParent());
      Projected = modulesafety::hasLifetimeBinderParameter(Owner);
    }
    if (circleIsCallableValue(C.getBaseElementType(F->getType()))) {
      unsigned Count = circleTypeLifetimeCount(F->getType());
      bool Captured = Count != 0;
      for (unsigned I = 1; I <= Count; ++I) Captured &= circleMappedFieldRegion(F, I) != 0;
      Projected |= Captured;
    }
    if (C.getLangOpts().CircleBorrowValues &&
        modulesafety::objectBorrow(F->getType()) && !Projected && !MemberPack)
      reject(F->getLocation(), "borrow value fields require class lifetime parameters");
#endif
    if (F->hasAttr<PackedAttr>())
      reject(F->getLocation(), "packed field requires an unaligned access model");
    // A class that declares a thread contract owns the representation of its
    // own storage; the contract is what the checked model asserts about it.
    auto *Owner = dyn_cast<CXXRecordDecl>(F->getParent());
    bool Contract = Owner && (marked(Owner, "safecpp.send") ||
                              marked(Owner, "safecpp.sync") ||
                              marked(Owner, "safecpp.unsend") ||
                              marked(Owner, "safecpp.unsync"));
    if (!Contract)
      checkValueType(F->getType(), F->getLocation());
    if (F->isMutable())
      reject(F->getLocation(), "mutable field requires a synchronization contract");
    if (F->getType().isVolatileQualified())
      reject(F->getLocation(), "volatile field storage");
    return true;
  }
  bool VisitCXXRecordDecl(CXXRecordDecl *D) {
    if (D->isCompleteDefinition())
      for (const auto &Base : D->bases())
        if (const auto *Parent = Base.getType()->getAsCXXRecordDecl();
            Parent && markedImplicit(Parent, "safecpp.native.interface") &&
            !markedImplicit(D, "safecpp.native.interface")) {
          auto &Diagnostics = C.getDiagnostics();
          Diagnostics.Report(D->getLocation(), Diagnostics.getCustomDiagID(
              DiagnosticsEngine::Error,
              "Circle interface inheritance cannot create an ordinary object type"));
        }
    if (D->hasAttr<PackedAttr>() || D->hasAttr<MaxFieldAlignmentAttr>())
      reject(D->getLocation(), "packed layout requires an unaligned access model");
    if (D->isCompleteDefinition() && !D->isDependentContext()) {
      if (marked(D, "safecpp.pinned")) {
        bool CopyDeleted = false, MoveDeleted = false;
        for (auto *Ctor : D->ctors()) {
          if (Ctor->isCopyConstructor())
            CopyDeleted |= Ctor->isDeleted();
          if (Ctor->isMoveConstructor())
            MoveDeleted |= Ctor->isDeleted();
        }
        if (!CopyDeleted || !MoveDeleted)
          reject(D->getLocation(), "pinned records must explicitly delete copy "
                                   "and move constructors");
      }
      if (marked(D, "safecpp.unsafe.borrowed.sequence"))
        if (auto *Spec = dyn_cast<ClassTemplateSpecializationDecl>(D);
            Spec && Spec->getTemplateArgs().size() &&
            Spec->getTemplateArgs()[0].getKind() == TemplateArgument::Type &&
            !modulesafety::objectBorrow(Spec->getTemplateArgs()[0].getAsType()))
          reject(D->getLocation(),
                 "borrowed sequences require a borrow-carrying element type");
      // Element storage is the claim that the elements kept there were adopted
      // from the region the sequence's stored borrow contract declares. The
      // claim is only read for an audited sequence with a declared region, and
      // only when it can hold borrow-carrying elements.
      for (auto *Field : D->fields())
        if (modulesafety::sequenceStorageField(Field)) {
          if (!modulesafety::auditedSequence(D))
            reject(Field->getLocation(),
                   "element storage requires an audited borrowed sequence");
          QualType Element = Field->getType();
          if (Element->isPointerType()) Element = Element->getPointeeType();
          else if (Element->isArrayType()) Element = C.getBaseElementType(Element);
          if (!Element.isNull() && !Element->isDependentType() &&
              !modulesafety::objectBorrow(Element))
            reject(Field->getLocation(),
                   "element storage requires borrow-carrying elements");
          bool Region = false;
          for (auto *Ctor : D->ctors())
            Region |= !modulesafety::storedParameters(Ctor).empty() ||
                      marked(Ctor, "safecpp.stores.self");
          if (!Region)
            reject(D->getLocation(),
                   "element storage requires a declared stored borrow region");
        }
      if (marked(D, "safecpp.native.choice")) {
        // A choice ends the active alternative's lifetime in its generated
        // destructor, so each alternative that needs a destructor must have
        // one that safe code can call.
        for (auto *Field : D->fields()) {
          auto *Storage = Field->getType()->getAsCXXRecordDecl();
          if (!Storage || !marked(Storage, "safecpp.native.choice.storage"))
            continue;
          for (auto *Alternative : Storage->fields()) {
            QualType Payload = Alternative->getType();
            if (!Payload->getAsCXXRecordDecl() ||
                Payload.isDestructedType() != QualType::DK_cxx_destructor)
              continue;
            call(Payload->getAsCXXRecordDecl()->getDestructor(),
                 D->getLocation());
          }
        }
      }
      // A contract written in the template's terms — `[[unsafe::send(T~is_send)]]`
      // — is read per instantiation: the frontend records whether the property
      // holds for the arguments this instantiation was written with, and that
      // conclusion is the answer. The declaration's own claim is checked when
      // nothing resolved it.
      bool Concluded = marked(D, "safecpp.thread.send") ||
                       marked(D, "safecpp.thread.sync") ||
                       marked(D, "safecpp.unsend") ||
                       marked(D, "safecpp.unsync");
      if (!Concluded) {
        if (marked(D, "safecpp.send") &&
            !modulesafety::threadSafeType(C.getCanonicalTagType(D), false))
          reject(D->getLocation(), "record does not satisfy Send");
        if (marked(D, "safecpp.sync") &&
            !modulesafety::threadSafeType(C.getCanonicalTagType(D), true))
          reject(D->getLocation(), "record does not satisfy Sync");
      }
    }
    if (D->isUnion() && D->isCompleteDefinition() && !modulesafety::scalarUnion(D) &&
        !marked(D, "safecpp.native.choice.storage"))
      reject(D->getLocation(), "union requires scalar members and trivial destruction");
    return true;
  }
  bool VisitAttributedStmt(AttributedStmt *S) {
    for (auto *A : S->getAttrs())
      if (isa<CXXAssumeAttr>(A))
        reject(S->getBeginLoc(), "unchecked assume statement");
    return true;
  }
  bool VisitOMPExecutableDirective(OMPExecutableDirective *S) {
    reject(S->getBeginLoc(),
           "OpenMP parallel execution has no checked ownership model");
    return true;
  }
  bool VisitCUDAKernelCallExpr(CUDAKernelCallExpr *E) {
    reject(E->getExprLoc(), "device execution has no checked ownership model");
    return true;
  }
  bool TraverseCoroutineBodyStmt(CoroutineBodyStmt *S) {
    auto *Promise = S->getPromiseDecl()->getType()->getAsCXXRecordDecl();
    if (!Promise || !marked(Promise, "safecpp.unsafe.coroutine.promise")) {
      reject(S->getBeginLoc(), "coroutine requires an audited frame promise");
      return true;
    }
    if (ActiveMethod && !ActiveMethod->isStatic())
      reject(S->getBeginLoc(), "coroutine frame cannot borrow this or a closure");
    if (auto *Function = dyn_cast<FunctionDecl>(S->getPromiseDecl()->getDeclContext()))
      for (auto *P : Function->parameters())
        if (P->getType()->isReferenceType() || modulesafety::objectBorrow(P->getType()))
          reject(P->getLocation(), "coroutine frame cannot retain borrowed parameters");
    return TraverseStmt(S->getBody());
  }
  bool TraverseCoyieldExpr(CoyieldExpr *E) {
    auto *Call = dyn_cast<CallExpr>(E->getOperand()->IgnoreParenImpCasts());
    if (!Call || Call->getNumArgs() != 1) {
      reject(E->getBeginLoc(), "unmodeled coroutine yield protocol");
      return true;
    }
    return TraverseStmt(Call->getArg(0));
  }
  bool TraverseCoawaitExpr(CoawaitExpr *E) {
    auto *Type = E->getOperand()->getType()->getAsCXXRecordDecl();
    if (!Type || !marked(Type, "safecpp.unsafe.coroutine.suspend"))
      reject(E->getBeginLoc(), "await requires an audited suspension contract");
    return TraverseStmt(E->getOperand());
  }
  bool VisitCXXConstructorDecl(CXXConstructorDecl *F) {
    if (!F->doesThisDeclarationHaveABody() || F->isDependentContext())
      return true;
    class InitializerReads : public RecursiveASTVisitor<InitializerReads> {
      modulesafety::InitListVisitSet<> InitLists;
    public:
      unsigned Phase = 0;
      std::set<const FieldDecl *> Initialized;
      std::vector<SourceLocation> InvalidReads;
      bool shouldVisitImplicitCode() const { return true; }
      bool dataTraverseStmtPre(Stmt *S) { return InitLists.enter(S, Phase); }
      bool VisitMemberExpr(MemberExpr *E) {
        if (isa<CXXThisExpr>(E->getBase()->IgnoreParenImpCasts()))
          if (auto *Field = dyn_cast<FieldDecl>(E->getMemberDecl());
              Field && !Initialized.count(Field))
            InvalidReads.push_back(E->getExprLoc());
        return true;
      }
      bool TraverseMemberExpr(MemberExpr *E) {
        if (isa<CXXThisExpr>(E->getBase()->IgnoreParenImpCasts()))
          return WalkUpFromMemberExpr(E);
        return RecursiveASTVisitor::TraverseMemberExpr(E);
      }
      bool TraverseCXXThisExpr(CXXThisExpr *E) {
        InvalidReads.push_back(E->getExprLoc());
        return true;
      }
      bool VisitCXXMemberCallExpr(CXXMemberCallExpr *E) {
        if (isa<CXXThisExpr>(E->getImplicitObjectArgument()->IgnoreParenImpCasts()))
          InvalidReads.push_back(E->getExprLoc());
        return true;
      }
      bool TraverseLambdaExpr(LambdaExpr *) { return true; }
    } Reads;
    for (auto *Init : F->inits()) {
      Reads.TraverseStmt(Init->getInit());
      ++Reads.Phase;
      if (Init->isMemberInitializer())
        Reads.Initialized.insert(Init->getMember());
    }
    for (auto L : Reads.InvalidReads)
      reject(L, "constructor initializer reads an uninitialized member or "
                "calls a method on a partial object");
    if (F->getParent()->isUnion())
      return true;
    // A delegating constructor initializes the complete object through the
    // target constructor. Check the target on its own declaration; requiring
    // a second set of member initializers here would reject every valid
    // `Ctor(...) : Ctor(args) { ... }` chain.
    if (llvm::any_of(F->inits(), [](const CXXCtorInitializer *I) {
          return I->isDelegatingInitializer();
        }))
      return true;
    for (auto *Field : F->getParent()->fields()) {
      if (markedImplicit(Field, "safecpp.native.phantom") ||
          Field->hasInClassInitializer() ||
          !C.getBaseElementType(Field->getType())->isScalarType())
        continue;
      bool Initialized = false;
      for (auto *I : F->inits())
        Initialized |= I->isMemberInitializer() && I->getMember() == Field;
      if (!Initialized)
        reject(F->getLocation(),
               "constructor does not initialize a scalar field or array");
    }
    return true;
  }
  bool VisitDeclRefExpr(DeclRefExpr *E) {
    if (auto *F = dyn_cast<FunctionDecl>(E->getDecl())) {
      if ((Safe || marked(F, "safecpp.safe")) && modulesafety::hasAdoptionContract(F))
        C.getDiagnostics().Report(E->getExprLoc(),
            C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
              "module-safety: indirect borrowed-element owner contracts are not yet modeled"));
      call(F, E->getExprLoc(), false);
    }
    if (auto *V = dyn_cast<VarDecl>(E->getDecl()); V && V->hasGlobalStorage()) {
      // A value that only the instantiation knows is judged there: the checker
      // visits the instantiated body as well.
      if (E->isValueDependent())
        return true;
      auto *Owner = V->getOwningModule();
      auto Found = Owner ? Modes.find(Owner->Name) : Modes.end();
      if ((!Owner || !Owner->isNamedModule() || Found == Modes.end() ||
           !Found->second) &&
          !constantSafe(E))
        reject(E->getExprLoc(), "access to unclassified or unsafe global storage");
      if (V->getTLSKind() == VarDecl::TLS_None &&
          (!V->getType().isConstQualified() ||
           (V->getType()->isRecordType() &&
            !modulesafety::threadSafeType(V->getType(), true))))
        reject(E->getExprLoc(),
               "access to shared mutable storage without synchronization");
    }
    return true;
  }
  bool VisitCXXMethodDecl(CXXMethodDecl *F) {
    for (auto *Base : F->overridden_methods()) {
      if (marked(Base, "safecpp.safe") && marked(F, "safecpp.unsafe")) {
        auto &D = C.getDiagnostics();
        D.Report(F->getLocation(),
                 D.getCustomDiagID(DiagnosticsEngine::Error,
                                   "module-safety: an unsafe override cannot "
                                   "weaken a safe virtual contract"));
      }
      if (marked(Base, "safecpp.safe") && F->getReturnType()->isReferenceType() &&
          (modulesafety::borrowedParameters(Base) !=
               modulesafety::borrowedParameters(F) ||
           marked(Base, "safecpp.borrow.this") != marked(F, "safecpp.borrow.this")))
        reject(F->getLocation(),
               "virtual override changes the borrow lifetime contract");
    }
    return true;
  }
  bool TraverseUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *E) {
    // sizeof/alignof operands do not execute. VLA types are rejected
    // separately.
    return VisitUnaryExprOrTypeTraitExpr(E);
  }
  bool TraverseCXXNoexceptExpr(CXXNoexceptExpr *) { return true; }
  bool TraverseExpressionTraitExpr(ExpressionTraitExpr *) { return true; }
  bool TraverseDecltypeType(DecltypeType *, bool = true) { return true; }
  bool TraverseDecltypeTypeLoc(DecltypeTypeLoc, bool = true) { return true; }
  bool TraverseRequiresExpr(RequiresExpr *) { return true; }
  bool VisitUnaryExprOrTypeTraitExpr(UnaryExprOrTypeTraitExpr *E) {
    if (const auto *Record = E->getTypeOfArgument()->getAsCXXRecordDecl();
        Record && markedImplicit(Record, "safecpp.native.interface")) {
      auto &D = C.getDiagnostics();
      D.Report(E->getExprLoc(), D.getCustomDiagID(DiagnosticsEngine::Error,
          "Circle interface layout queries are not yet modeled"));
    }
    return true;
  }
  bool VisitVarDeclType(QualType T, SourceLocation L) {
    if (T->isVariablyModifiedType())
      reject(L, "variable-length array extension");
    return true;
  }
  bool VisitParmVarDecl(ParmVarDecl *P) {
    if (marked(P, "safecpp.native.owned.self") && !P->getType()->isDependentType()) {
      auto *Record = P->getType()->getAsCXXRecordDecl();
      if (!P->isExplicitObjectParameter() || !Record ||
          (!Record->hasTrivialDestructor() && !Record->isParamDestroyedInCallee()))
        reject(P->getLocation(), "owned self requires a by-value record with an owning parameter ABI");
    }
    for (auto *A : P->specific_attrs<AnnotateAttr>()) {
      auto Label = A->getAnnotation();
      if (Label.consume_front("safecpp.lifetime:") &&
          (Label.empty() ||
           (!P->getType()->isDependentType() && !P->getType()->isReferenceType() &&
            !modulesafety::objectBorrow(P->getType()))))
        reject(P->getLocation(), "named lifetime requires a borrow-carrying parameter");
    }
    if (P->getType()->isDependentType())
      return true;
    if (auto *Function = dyn_cast<FunctionDecl>(P->getDeclContext());
        Function && marked(Function, "safecpp.validate.owned.arguments") &&
        (P->getType()->isReferenceType() || modulesafety::objectBorrow(P->getType())))
      reject(P->getLocation(),
             "replacement arguments must not retain borrowed storage");
    // By-value parameters are destroyed even when the function's CFG does
    // not contain an automatic-object destructor element for the parameter.
    if (!P->getType()->isReferenceType() &&
        !marked(P, "safecpp.unsafe.object"))
      if (auto *Record = P->getType()->getAsCXXRecordDecl();
          Record && Record->hasDefinition() && !Record->hasTrivialDestructor())
        if (auto *Destructor = Record->getDestructor())
          call(Destructor, P->getLocation());
    if (marked(P, "safecpp.send.static") &&
        (P->getType()->isReferenceType() || modulesafety::objectBorrow(P->getType())))
      reject(P->getLocation(),
             "unscoped thread transfer cannot carry a borrowed lifetime");
    if ((marked(P, "safecpp.send") || marked(P, "safecpp.send.static")) &&
        !modulesafety::threadSafeType(P->getType(), false))
      reject(P->getLocation(), "thread transfer requires Send ownership "
                               "without borrowed or raw storage");
    if (marked(P, "safecpp.sync") &&
        (!P->getType()->isReferenceType() ||
         !P->getType()->getPointeeType().isConstQualified() ||
         !modulesafety::threadSafeType(P->getType(), true)))
      reject(P->getLocation(),
             "shared thread access requires a const reference to a Sync type");
    return true;
  }
  bool VisitVarDecl(VarDecl *V) {
#ifdef MODULE_SAFETY_BUILTIN
    // A dependent match binding acquires its initializer when its operand and
    // payload are instantiated. User declarations and concrete bindings still
    // require initialization; source cannot forge this compiler-owned marker.
    bool DeferredMatchBinding = DependentBody && V->getType()->isDependentType() &&
                                markedImplicit(V, "safecpp.native.match.binding");
    // A local borrow slot may be declared before the control-flow point that
    // binds it. The flow analysis still rejects a read before that assignment.
    bool DeferredBorrow = V->getType()->getAs<BorrowValueType>() &&
                          V->isLocalVarDecl() && !V->hasGlobalStorage() &&
                          !V->hasInit() && laterBorrowAssignment(V);
    if (V->getType()->getAs<BorrowValueType>() && !V->hasInit() &&
        !isa<ParmVarDecl>(V) && !DeferredMatchBinding && !DeferredBorrow)
      reject(V->getLocation(), "borrow values require initialization");
    if (V->hasGlobalStorage() && !V->isLocalVarDecl() &&
        C.getBaseElementType(V->getType())->getAs<BorrowValueType>())
      reject(V->getLocation(), "borrow value globals require a storage lifetime contract");
#endif
    if (V->hasAttr<WeakAttr>() || V->hasAttr<WeakImportAttr>() ||
        V->hasAttr<WeakRefAttr>() || V->hasAttr<AsmLabelAttr>() ||
        V->hasAttr<AliasAttr>())
      reject(V->getLocation(), "optional or aliased storage requires an audited boundary");
    if (V->hasInit())
      checkPartialObjectArgument(V->getInit());
    if (layoutKnown(V->getType()) &&
        !V->getType()->isReferenceType() &&
        C.getDeclAlign(V) < C.getTypeAlignInChars(C.getCanonicalType(V->getType())))
      reject(V->getLocation(),
             "under-aligned storage requires an unaligned access model");
    if (V->hasGlobalStorage() && V->hasInit() && !V->getType()->isDependentType()) {
      // Dependent constexpr initializers are evaluated at instantiation;
      // the C++ frontend itself requires them to be constant then.
      if (!V->isConstexpr() && !V->hasConstantInitialization())
        reject(
            V->getLocation(),
            "dynamic static initialization requires an initialization-order contract");
      if (auto *R = C.getBaseElementType(V->getType())->getAsCXXRecordDecl();
          R && R->hasDefinition() && !R->hasTrivialDestructor())
        reject(V->getLocation(),
               "static destruction requires a shutdown lifetime contract");
    }
    if (V->hasAttr<AlignValueAttr>())
      reject(V->getLocation(), "unchecked pointer alignment precondition");
    if (V->hasAttr<CleanupAttr>())
      reject(V->getLocation(), "unmodeled automatic cleanup callback");
    if (Safe && !Unchecked && V->hasGlobalStorage() && !V->isLocalVarDecl() &&
        V->hasInit() && modulesafety::objectBorrow(V->getType()))
      modulesafety::analyzeInitializer(
          C, V, [this](const FunctionDecl *F, SourceLocation L) { call(F, L); });
    else if (V->hasGlobalStorage() && !V->isLocalVarDecl() && V->hasInit() &&
             !V->getType()->isDependentType()) {
      StaticContractCalls Calls;
      Calls.TraverseStmt(V->getInit());
      if (Calls.Found)
        modulesafety::analyzeInitializer(C, V,
            [](const FunctionDecl *, SourceLocation) {}, true);
    }
    checkValueType(V->getType(), V->getLocation());
    VisitVarDeclType(V->getType(), V->getLocation());
    if (V->getType().isVolatileQualified())
      reject(V->getLocation(), "volatile storage");
    return true;
  }
  bool VisitImplicitValueInitExpr(ImplicitValueInitExpr *E) {
#ifdef MODULE_SAFETY_BUILTIN
    if (C.getBaseElementType(E->getType())->getAs<BorrowValueType>())
      reject(E->getExprLoc(), "borrow values cannot be zero initialized");
#endif
    return true;
  }
  bool VisitCXXScalarValueInitExpr(CXXScalarValueInitExpr *E) {
#ifdef MODULE_SAFETY_BUILTIN
    if (E->getType()->getAs<BorrowValueType>())
      reject(E->getExprLoc(), "borrow values cannot be zero initialized");
#endif
    return true;
  }
  bool VisitUnaryOperator(UnaryOperator *E) {
    // The operand's declaration already accepted the raw representation
    // (`T* unsafe p_`), so dereference, stepping and increment are audited
    // where that object was declared.
    if (unsafeUse(E->getSubExpr()))
      return true;
#ifdef MODULE_SAFETY_BUILTIN
    if (E->getOpcode() == UO_Relocate && !E->isTypeDependent()) {
      // Relocation lowers implicit calls as well as representation copies.
      // Their effects require the same classification as explicit calls.
      CircleRelocationQuery Query(C);
      llvm::SmallPtrSet<const Type *, 16> Seen;
      auto Check = [&](auto &&Self, QualType T) -> void {
        T = C.getBaseElementType(T);
        if (!Seen.insert(T.getCanonicalType().getTypePtr()).second) return;
        auto Plan = Query.get(T);
        if (Plan.Method) {
          call(Plan.Method, E->getExprLoc());
          if (Plan.Kind == CircleRelocationKind::Move)
            if (auto *Dtor = Plan.Method->getParent()->getDestructor();
                Dtor && !Dtor->isTrivial()) call(Dtor, E->getExprLoc());
        }
        if (Plan.Kind != CircleRelocationKind::Memberwise &&
            Plan.Kind != CircleRelocationKind::Choice) return;
        if (auto *Record = T->getAsCXXRecordDecl()) {
          for (const auto &Base : Record->bases()) Self(Self, Base.getType());
          for (auto *Field : Record->fields()) {
            if (circleRelocationMarked(Field, "safecpp.native.phantom")) continue;
            if (Plan.Kind == CircleRelocationKind::Choice &&
                circleRelocationMarked(Field, "safecpp.native.choice.payload")) {
              for (auto *Payload : Field->getType()->getAsRecordDecl()->fields())
                Self(Self, Payload->getType());
            } else Self(Self, Field->getType());
          }
        }
      };
      Check(Check, E->getType());
    }
#endif
    if (UnaryOperator::getOpcodeStr(E->getOpcode()) == "^^" &&
        modulesafety::pinnedStorage(E->getType()))
      reject(E->getExprLoc(), "relocating pinned storage");
    if (UnaryOperator::getOpcodeStr(E->getOpcode()) == "^^")
      for (auto *M = dyn_cast<MemberExpr>(E->getSubExpr()->IgnoreParens()); M;
           M = dyn_cast<MemberExpr>(M->getBase()->IgnoreParens())) {
        auto T = M->getBase()->getType();
        bool BorrowParent = modulesafety::objectBorrow(T);
#ifdef MODULE_SAFETY_BUILTIN
        if (C.getLangOpts().CircleBorrowValues && T->isRecordType())
          BorrowParent = false; // Per-field ownership is checked by dataflow.
#endif
        if (BorrowParent || modulesafety::pinnedStorage(T))
          reject(E->getExprLoc(), "partial relocation requires an owning unpinned record");
      }
    if (E->getOpcode() == UO_Minus && E->getType()->isSignedIntegerType() &&
        !constantSafe(E))
      reject(E->getExprLoc(), "potentially overflowing signed negation");
    bool CheckedBorrowDeref = false;
#ifdef MODULE_SAFETY_BUILTIN
    if (E->getOpcode() == UO_Deref) {
      // A borrow value is reached through the pointer the dereference is
      // formed on, so the cast that carries it there is not a raw pointer.
      const Expr *Operand = E->getSubExpr()->IgnoreParens();
      if (const auto *Cast = dyn_cast<ImplicitCastExpr>(Operand);
          Cast && Cast->getCastKind() == CK_BitCast)
        Operand = Cast->getSubExpr()->IgnoreParens();
      CheckedBorrowDeref = Operand->getType()->getAs<BorrowValueType>();
      if (!CheckedBorrowDeref)
        if (const auto *Ref = C.getReferenceQualifiedType(Operand)
                                  ->getAs<ReferenceType>())
          CheckedBorrowDeref = Ref->isSafetyBorrow();
    }
#endif
    if (E->getOpcode() == UO_Deref && !E->isTypeDependent() &&
        !ownsThis(E->getSubExpr()) &&
        !CheckedBorrowDeref)
      reject(E->getExprLoc(), "raw pointer dereference");
    // Signed inc/dec use the same checked overflow intrinsic as signed
    // addition and subtraction in CodeGen. Raw pointer stepping still needs
    // the audited declaration of the storage it walks.
    if (E->isIncrementDecrementOp() && E->getType()->isPointerType())
      reject(E->getExprLoc(), "pointer arithmetic");
    return true;
  }
  bool VisitBinaryOperator(BinaryOperator *E) {
    if (unsafeUse(E->getLHS()) || unsafeUse(E->getRHS()))
      return true;
#ifdef MODULE_SAFETY_BUILTIN
    if (C.getLangOpts().CircleBorrowValues && E->isAssignmentOp())
      if (const auto *Element = dyn_cast<ArraySubscriptExpr>(E->getLHS()->IgnoreParenImpCasts());
          Element && modulesafety::objectBorrow(Element->getType()))
        reject(E->getExprLoc(), "borrow array element rebinding requires a projected region update");
#endif
    if (BinaryOperator::getOpcodeStr(E->getOpcode()) == ":=")
      for (auto *Member = dyn_cast<MemberExpr>(E->getLHS()->IgnoreParens()); Member;
           Member = dyn_cast<MemberExpr>(Member->getBase()->IgnoreParens())) {
        auto ParentType = Member->getBase()->getType();
        if (modulesafety::objectBorrow(ParentType) ||
            (!E->getRHS()->getType()->isVoidType() && modulesafety::pinnedStorage(ParentType)))
          reject(E->getExprLoc(), "field replacement cannot relocate borrowed or pinned parent storage");
      }
    if (BinaryOperator::getOpcodeStr(E->getOpcode()) == ":=" &&
        !E->getRHS()->getType()->isVoidType() &&
        modulesafety::pinnedStorage(E->getLHS()->getType()))
      reject(E->getExprLoc(), "replacement cannot relocate pinned storage");
    auto O = E->getOpcode();
    if (E->isAssignmentOp())
      checkPartialObjectArgument(E->getRHS());
    if (E->isAssignmentOp() && E->getLHS()->getType().isVolatileQualified())
      reject(E->getExprLoc(), "volatile store");
    if (O == BO_PtrMemD || O == BO_PtrMemI)
      if (!modulesafety::knownMemberFunctionPointer(E->getRHS()))
        reject(E->getExprLoc(), "unchecked member-pointer application");
    if (E->getLHS()->getType()->isPointerType() ||
        E->getRHS()->getType()->isPointerType()) {
      auto SliceFieldSource = [&](const Expr *Value,
                                  llvm::StringRef FieldName) -> const VarDecl * {
        if (!Value)
          return nullptr;
        Value = Value->IgnoreParens();
        for (;;) {
          if (auto *Cleanup = dyn_cast<ExprWithCleanups>(Value))
            Value = Cleanup->getSubExpr()->IgnoreParens();
          else if (auto *Temporary = dyn_cast<MaterializeTemporaryExpr>(Value))
            Value = Temporary->getSubExpr()->IgnoreParens();
          else if (auto *Cast = dyn_cast<CastExpr>(Value))
            Value = Cast->getSubExpr()->IgnoreParens();
          else
            break;
        }
        auto *Member = dyn_cast<MemberExpr>(Value);
        if (!Member)
          return nullptr;
        auto *Field = dyn_cast<FieldDecl>(Member->getMemberDecl());
        if (!Field || Field->getName() != FieldName)
          return nullptr;
        const Expr *Base = Member->getBase()->IgnoreParenImpCasts();
        for (;;) {
          auto *Unary = dyn_cast<UnaryOperator>(Base);
          if (!Unary ||
              (Unary->getOpcode() != UO_Deref &&
               UnaryOperator::getOpcodeStr(Unary->getOpcode()) != "^"))
            break;
          Base = Unary->getSubExpr()->IgnoreParenImpCasts();
        }
        auto *Ref = dyn_cast<DeclRefExpr>(Base);
        return Ref ? dyn_cast<VarDecl>(Ref->getDecl()) : nullptr;
      };
      bool SliceEnd = false;
      if (E->isAdditiveOp() && E->getOpcode() == BO_Add &&
          E->getType()->isPointerType()) {
        const Expr *Pointer = E->getLHS();
        const Expr *Length = E->getRHS();
        if (!Pointer->getType()->isPointerType())
          std::swap(Pointer, Length);
        const VarDecl *Data =
            SliceFieldSource(Pointer, "__circle_data");
        SliceEnd = Data && Data ==
            SliceFieldSource(Length, "__circle_len");
      }
      if (!SliceEnd && (E->isAdditiveOp() || E->isCompoundAssignmentOp()))
        reject(E->getExprLoc(), "pointer arithmetic");
    }
    bool CheckedIntegerDivRem = false;
#ifdef MODULE_SAFETY_BUILTIN
    QualType Computation = E->getType();
    if (auto *Compound = dyn_cast<CompoundAssignOperator>(E))
      Computation = Compound->getComputationResultType();
    CheckedIntegerDivRem =
        (C.getLangOpts().ModuleSafetySafe || C.getLangOpts().ModuleSafetyUnsafe) &&
        Computation->isIntegerType() &&
        (O == BO_Div || O == BO_Rem || O == BO_DivAssign || O == BO_RemAssign);
#endif
    // A constant shift whose count fits the promoted left operand is defined.
    // A runtime count still needs a checked-shift lowering, which this subset
    // does not provide yet.
    bool ConstantShift = false;
    if (E->isShiftOp() || O == BO_ShlAssign || O == BO_ShrAssign) {
      Expr::EvalResult Count;
      QualType Left = E->getLHS()->getType();
      if (auto *Compound = dyn_cast<CompoundAssignOperator>(E))
        Left = Compound->getComputationLHSType();
      if (Left->isIntegerType() && E->getRHS()->EvaluateAsInt(Count, C) &&
          !Count.HasSideEffects && !Count.Val.getInt().isNegative() &&
          Count.Val.getInt().getActiveBits() <= 64 &&
          Count.Val.getInt().getZExtValue() < C.getIntWidth(Left))
        ConstantShift = true;
    }
    if (!CheckedIntegerDivRem && !ConstantShift &&
        (O == BO_Div || O == BO_Rem || O == BO_DivAssign || O == BO_RemAssign ||
         E->isShiftOp() || O == BO_ShlAssign || O == BO_ShrAssign))
      reject(E->getExprLoc(), "division, remainder or shift without runtime checks");
    bool Signed = E->getType()->isSignedIntegerType();
    if (auto *Compound = dyn_cast<CompoundAssignOperator>(E))
      Signed |= Compound->getComputationResultType()->isSignedIntegerType();
    bool CheckedSignedArithmetic = false;
#ifdef MODULE_SAFETY_BUILTIN
    CheckedSignedArithmetic =
        (C.getLangOpts().ModuleSafetySafe || C.getLangOpts().ModuleSafetyUnsafe) &&
        Signed;
#endif
    if (Signed && !CheckedSignedArithmetic && !constantSafe(E) &&
        (O == BO_Add || O == BO_Sub || O == BO_Mul || O == BO_AddAssign ||
         O == BO_SubAssign || O == BO_MulAssign))
      reject(E->getExprLoc(), "potentially overflowing signed arithmetic");
    return true;
  }
  bool VisitArraySubscriptExpr(ArraySubscriptExpr *E) {
    if (E->isTypeDependent()) return true;
    if (unsafeUse(E->getBase()) || noRuntimeCheckParameter(ActiveFunction))
      return true;
    // Keep the array bound before the implicit array-to-pointer conversion.
    // Only a proven constant index permits access without a runtime check.
    const Expr *Base = modulesafety::evaluationSource(
        E->getBase()->IgnoreParenImpCasts())->IgnoreParenImpCasts();
#ifdef MODULE_SAFETY_BUILTIN
    // The syntactic form of a single-evaluation native slice access keeps its
    // original slice operand. Its semantic form below uses the data field.
    if (!C.circleSliceElement(Base->getType()).isNull()) return true;
#endif
    // The element of a slice is reached through the pointer the generated
    // record holds, and the access carries the bounds check that formed it.
    if (const auto *Member = dyn_cast<MemberExpr>(Base))
      for (const auto *A : Member->getMemberDecl()->specific_attrs<AnnotateAttr>())
        if (A->isImplicit() && A->getAnnotation() == "safecpp.native.slice.data")
          return true;
    const auto *Array = C.getAsConstantArrayType(Base->getType());
#ifdef MODULE_SAFETY_BUILTIN
    // Native CodeGen checks this known bound before the GEP/load/store. Raw
    // pointers remain outside this rule; the plugin has no CodeGen checks.
    if (Array && (C.getLangOpts().ModuleSafetySafe ||
                  C.getLangOpts().ModuleSafetyUnsafe))
      return true;
#endif
    Expr::EvalResult Index;
    if (Array && stableIntegerConstant(E->getIdx(), Index)) {
      const auto &Value = Index.Val.getInt();
      unsigned Width = std::max(Value.getBitWidth(), Array->getSize().getBitWidth());
      if (!Value.isNegative() &&
          Value.zextOrTrunc(Width).ult(Array->getSize().zextOrTrunc(Width)))
        return true;
    }
    reject(E->getExprLoc(), "unchecked subscripting");
    return true;
  }
  bool VisitMemberExpr(MemberExpr *E) {
    if (E->isArrow() && !ownsThis(E->getBase()) && !unsafeUse(E->getBase()))
      reject(E->getExprLoc(), "pointer member access");
    return true;
  }
  bool VisitImplicitCastExpr(ImplicitCastExpr *E) {
    // Value-category changes are not changes of value type. Explicit casts
    // already express the programmer's conversion intent.
    bool Lossy = false;
    if (!E->isTypeDependent()) {
      auto From = E->getSubExpr()->getType(), To = E->getType();
      if (E->getCastKind() == CK_IntegralCast && !To->isBooleanType()) {
        bool FS = From->isSignedIntegerOrEnumerationType();
        bool TS = To->isSignedIntegerOrEnumerationType();
        Lossy = (FS && !TS) || C.getIntWidth(To) - TS < C.getIntWidth(From) - FS;
        Expr::EvalResult Value;
        if (Lossy && stableIntegerConstant(E->getSubExpr(), Value)) {
          const auto &I = Value.Val.getInt();
          Lossy = TS ? (I.isNegative() ? !I.isSignedIntN(C.getIntWidth(To))
                                       : I.getActiveBits() >= C.getIntWidth(To))
                     : I.isNegative() || !I.isIntN(C.getIntWidth(To));
        }
      } else if (E->getCastKind() == CK_IntegralToFloating) {
        unsigned Bits = C.getIntWidth(From) - From->isSignedIntegerOrEnumerationType();
        Lossy = llvm::APFloat::semanticsPrecision(C.getFloatTypeSemantics(To)) < Bits;
        if (Lossy && exactIntegerFloatConstant(E))
          Lossy = false;
      } else if (E->getCastKind() == CK_FloatingToIntegral) {
        Lossy = true;
      } else if (E->getCastKind() == CK_FloatingCast) {
        Lossy = llvm::APFloat::semanticsPrecision(C.getFloatTypeSemantics(To)) <
                llvm::APFloat::semanticsPrecision(C.getFloatTypeSemantics(From));
      }
    }
    if (Safe && !Unchecked && Lossy && !E->isPartOfExplicitCast() &&
        E->getExprLoc().isValid() &&
        !C.hasSameUnqualifiedType(E->getType(), E->getSubExpr()->getType())) {
      auto &D = C.getDiagnostics();
      // Custom warning IDs can enter PCM diagnostic mappings, but their
      // registrations do not survive importing without the plugin. Use the
      // stable plugin diagnostic so ordinary Clang can read these PCMs too.
      D.Report(E->getExprLoc(), diag::warn_fe_backend_plugin)
          << ("module-safety: implicit conversion from '" +
              E->getSubExpr()->getType().getAsString() + "' to '" +
              E->getType().getAsString() + "'");
    }
    if (E->getCastKind() == CK_LValueToRValue &&
        E->getSubExpr()->getType().isVolatileQualified())
      reject(E->getExprLoc(), "volatile load");
    return true;
  }
  void checkFunctionCast(CastExpr *E) {
#ifdef MODULE_SAFETY_BUILTIN
    if (E->getCastKind() == CK_ToVoid || E->getType()->isVoidType()) return;
    // Sema has already established that these conversions create a genuine
    // null value. There is no callable implementation whose contract could
    // be erased or invented; invocation still uses the native null check.
    if (E->getCastKind() == CK_NullToPointer ||
        E->getCastKind() == CK_NullToMemberPointer) return;
    // Native dereference lowers the borrow's address to an ordinary pointer.
    // This compiler-created projection retains the exact referent type; an
    // explicit cast, or a changed referent contract, still needs the checks
    // below. It does not authorize erasing a callback stored in that referent.
    if (isa<ImplicitCastExpr>(E) && E->getCastKind() == CK_BitCast)
      if (const auto *Borrow = E->getSubExpr()->getType()->getAs<BorrowValueType>())
        if (E->getType()->isPointerType() &&
            C.hasSameType(Borrow->getPointeeType(), E->getType()->getPointeeType()))
          return;
    if (isa<ImplicitCastExpr>(E) && E->getCastKind() == CK_ArrayToPointerDecay)
      if (const auto *Array = C.getAsArrayType(E->getSubExpr()->getType()))
        if (E->getType()->isPointerType() &&
            C.hasSameType(Array->getElementType(), E->getType()->getPointeeType()))
          return;
    auto Function = [](QualType Type) -> const FunctionProtoType * {
      Type = Type.getNonReferenceType();
      if (Type->isPointerType() || Type->isMemberPointerType())
        Type = Type->getPointeeType();
      return Type->getAs<FunctionProtoType>();
    };
    auto Source = E->getSubExpr()->getType(), Target = E->getType();
    auto *From = Function(Source), *To = Function(Target);
    if (!circleContainsFunctionLifetimeContract(Source) &&
        !circleContainsFunctionLifetimeContract(Target)) return;
    // Checked memory operations copy handle storage, not the callable itself.
    if (InTrustedMemoryOp && !From && !To) return;
    if (circleSameFunctionContractTree(C, Source, Target)) return;
    // A reference cast yields a storage view, rather than copying a callback
    // value. Expr types omit the reference spelling, so recover the storage
    // boundary for the shared relation. Mutable slots remain invariant;
    // const slots and references to immutable function code may compose.
    auto RelationSource = Source, RelationTarget = Target;
    if (E->isGLValue()) {
      RelationSource = C.getPointerType(Source);
      RelationTarget = C.getPointerType(Target);
    }
    if (circleFunctionTypeConvertible(C, RelationSource, RelationTarget)) return;
    auto Error = [&](llvm::StringRef Message) {
      C.getDiagnostics().Report(E->getExprLoc(),
          C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
                                            "module-safety: %0")) << Message;
    };
    bool Quantified = circleContainsFunctionLifetimeContract(Source, true) ||
                      circleContainsFunctionLifetimeContract(Target, true);
    bool Projected = (From && From->getReturnBorrowClassRegion()) ||
                     (To && To->getReturnBorrowClassRegion());
    auto ClassValue = [](const FunctionProtoType *F) {
      return F && circleSimpleClassValueRegion(F->getReturnType()) &&
          (!F->getReturnBorrowSources().empty() || F->hasGenerativeReturnLifetime());
    };
    bool ClassResult = ClassValue(From) || ClassValue(To);
    bool Generative = (From && From->hasGenerativeReturnLifetime()) ||
                      (To && To->hasGenerativeReturnLifetime());
    bool Static = circleFunctionHasStaticContract(From) || circleFunctionHasStaticContract(To);
    if (Quantified) Error("cast cannot erase or invent quantified lifetime contracts");
    if (Projected) Error("cast cannot erase or invent class result lifetime contracts");
    if (ClassResult) Error("cast cannot erase or invent class-value lifetime contracts");
    if (Generative) Error("cast cannot erase or invent generative lifetime contracts");
    if (Static) Error("cast cannot erase static lifetime contracts or invent new static promises");
    if (!Quantified && !Projected && !ClassResult && !Generative && !Static)
      Error("cast cannot erase or invent stored function lifetime contracts");
#endif
  }
  bool VisitCastExpr(CastExpr *E) {
    // An unsafe object annotation cannot change a public callable contract.
    checkFunctionCast(E);
    if (unsafeUse(E->getSubExpr()))
      return true;
    // Discarding a value cannot forge a representation or a lifetime.
    if (E->getCastKind() == CK_ToVoid || E->getType()->isVoidType())
      return true;
#ifdef MODULE_SAFETY_BUILTIN
    // Erasing the address of a borrow handle or a record containing borrows
    // exposes its representation to untracked writes. Unsafe permission does
    // not supply a lifetime proof for the overwritten handle.
    if (C.getLangOpts().CircleBorrowValues && !E->isTypeDependent()) {
      auto Storage = [](QualType Type) {
        unsigned Depth = 0;
        while (Type->isPointerType() || Type->isReferenceType()) {
          ++Depth;
          Type = Type->getPointeeType();
        }
        if (auto *Borrow = Type->getAs<BorrowValueType>()) {
          if (!Depth) { Type = Borrow->getPointeeType(); Depth = 1; }
          else return std::make_pair(Type, Depth);
        }
        return std::make_pair(Type, Depth);
      };
      auto Source = Storage(E->getSubExpr()->getType());
      auto Target = Storage(E->getType());
      // Comparing pointers to borrow values is lowered through the handle's
      // pointer representation (`T^ *` -> `T **`) with a no-op cast. The value
      // is unchanged and the result is an rvalue, so no lifetime is erased.
    auto BorrowPointerRepresentation = [&]() {
        if (E->isGLValue() || E->getCastKind() != CK_NoOp)
          return false;
        auto From = E->getSubExpr()->getType();
        auto To = E->getType();
        if (!From->isPointerType() || !To->isPointerType())
          return false;
        // A borrow handle is stored as a pointer to its referent. Map every
        // nested borrow layer to that pointer representation while preserving
        // qualification, then compare the resulting types.
        //
        // Qualifiers on the pointee do not change the pointer representation:
        // `T*` and `const T*` compare the same addresses.  Keep the shape
        // check separate from qualification so a borrow of `const T` is not
        // mistaken for a different storage representation.
        auto Representation = [&](auto &&Self, QualType T) -> QualType {
          QualType U = T.getUnqualifiedType();
          if (auto *Borrow = U->getAs<BorrowValueType>())
            U = C.getPointerType(Self(Self, Borrow->getPointeeType()));
          else if (U->isPointerType())
            U = C.getPointerType(Self(Self, U->getPointeeType()));
          else if (U->isLValueReferenceType() || U->isRValueReferenceType())
            U = C.getLValueReferenceType(Self(Self, U->getPointeeType()));
          return U;
        };
        return C.hasSameUnqualifiedType(Representation(Representation, From),
                                        Representation(Representation, To));
      };
      bool Protected = (Source.second &&
                        Source.first->getAs<BorrowValueType>()) ||
          ((Source.second || E->getSubExpr()->getType()->getAs<BorrowValueType>()) &&
           modulesafety::objectBorrow(Source.first));
      if (Protected && E->getCastKind() != CK_PointerToBoolean &&
          !BorrowPointerRepresentation() && !InTrustedMemoryOp &&
          (Source.second != Target.second ||
           !C.hasSameUnqualifiedType(Source.first, Target.first)))
        C.getDiagnostics().Report(E->getExprLoc(),
            C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error,
                                              "module-safety: %0"))
            << "native borrow storage representation cannot be erased";
    }
#endif
    auto Representation = [](QualType Type) {
      while (Type->isPointerType() || Type->isReferenceType())
        Type = Type->getPointeeType();
#ifdef MODULE_SAFETY_BUILTIN
      if (auto *Borrow = Type->getAs<BorrowValueType>()) Type = Borrow->getPointeeType();
#endif
      return Type;
    };
    auto ToRepresentation = Representation(E->getType());
    if ((modulesafety::hasStaticLifetimeFields(ToRepresentation) ||
         modulesafety::hasClassLifetimeFields(ToRepresentation)) &&
        !C.hasSameUnqualifiedType(ToRepresentation, Representation(E->getSubExpr()->getType())) &&
        (isa<CXXReinterpretCastExpr, CStyleCastExpr, BuiltinBitCastExpr>(E) ||
         E->getCastKind() == CK_BaseToDerived))
      C.getDiagnostics().Report(E->getExprLoc(),
          C.getDiagnostics().getCustomDiagID(DiagnosticsEngine::Error, "module-safety: %0"))
            << (modulesafety::hasStaticLifetimeFields(ToRepresentation)
              ? "static field representation cast is not modeled"
              : "class field representation cast is not modeled");
    if (E->getCastKind() == CK_IntegralToFloating && !E->isTypeDependent()) {
      auto Source = E->getSubExpr()->getType();
      const auto &Semantics = C.getFloatTypeSemantics(E->getType());
      unsigned ValueBits =
          C.getIntWidth(Source) - Source->isSignedIntegerOrEnumerationType();
      // Every source value must fit, including the signed minimum. Merely
      // comparing storage sizes misses unsigned __int128 -> float.
      int MaxExponent = llvm::APFloat::semanticsMaxExponent(Semantics);
      bool Fits = static_cast<int64_t>(ValueBits) <= MaxExponent;
      if (!Source->isSignedIntegerOrEnumerationType() &&
          static_cast<int64_t>(ValueBits) == MaxExponent + 1 &&
          llvm::APFloat::semanticsPrecision(Semantics) >= ValueBits)
        Fits = true;
      if (!Fits && !exactIntegerFloatConstant(E))
        reject(E->getExprLoc(),
               "integer-to-floating conversion may exceed the destination range");
    }
    // An arithmetic C-style cast is a value conversion, not a pointer or
    // lifetime reinterpretation. The checked subset permits it; the unsafe
    // casts below still require an audited block.
    bool ArithmeticCStyleCast =
        isa<CStyleCastExpr>(E) && E->getType()->isArithmeticType() &&
        E->getSubExpr()->getType()->isArithmeticType();
    if (isa<CXXReinterpretCastExpr>(E) || isa<CXXConstCastExpr>(E) ||
        (isa<CStyleCastExpr>(E) && !ArithmeticCStyleCast) ||
        E->getCastKind() == CK_BaseToDerived ||
        E->getCastKind() == CK_FloatingToIntegral ||
        (E->getCastKind() == CK_IntegralCast && E->getType()->isEnumeralType()) ||
        (E->getCastKind() == CK_FloatingCast && !E->isTypeDependent() &&
         C.getTypeSize(E->getType()) < C.getTypeSize(E->getSubExpr()->getType())))
      reject(E->getExprLoc(), "unsafe cast");
    return true;
  }
  bool VisitCXXNewExpr(CXXNewExpr *E) {
    if (!InUnsafeInitializer)
      reject(E->getExprLoc(), "raw allocation");
    return true;
  }
  bool VisitCXXDeleteExpr(CXXDeleteExpr *E) {
    if (!unsafeUse(E->getArgument()))
      reject(E->getExprLoc(), "raw deletion");
    return true;
  }
  bool VisitCXXThrowExpr(CXXThrowExpr *E) {
    if (E->getSubExpr() && modulesafety::objectBorrow(E->getSubExpr()->getType()))
      reject(E->getExprLoc(), "exception payload cannot carry a borrowed lifetime");
    return true;
  }
  bool VisitCallExpr(CallExpr *E) {
    // Invoking a method through an object declared `unsafe` stays inside the
    // audited boundary that declaration established.
    if (const auto *Member = dyn_cast<CXXMemberCallExpr>(E);
        Member && unsafeUse(Member->getImplicitObjectArgument()))
      return true;
    const FunctionDecl *Callee = E->getDirectCallee();
    if (!Callee &&
        isa<CXXPseudoDestructorExpr>(
            E->getCallee()->IgnoreParenImpCasts()))
      return true;
    if (!Callee)
      Callee = modulesafety::indirectMemberCallee(E);
    if (!Callee)
      if (auto *Member = dyn_cast<CXXMemberCallExpr>(E))
        if (auto *CalleeExpr =
                dyn_cast<MemberExpr>(Member->getCallee()->IgnoreParenImpCasts()))
          Callee = dyn_cast_or_null<CXXMethodDecl>(
              CalleeExpr->getMemberDecl());
    bool ExplicitReceiver = false;
#ifdef MODULE_SAFETY_BUILTIN
    if (const auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee);
        Method && Method->getNumParams())
      ExplicitReceiver = Method->getParamDecl(0)->getType()->getAs<BorrowValueType>();
#endif
    if (const auto *Method = dyn_cast_or_null<CXXMethodDecl>(Callee);
        Method && E->getNumArgs() && unsafeUse(E->getArg(0)) &&
        (Method->isImplicitObjectMemberFunction() || ExplicitReceiver))
      return true;
    if (E->isTypeDependent() || E->isValueDependent()) {
      // Argument substitution can defer the value checks, but cannot change
      // the effect of an already resolved nondependent callee.
      if (Callee && !Callee->isDependentContext())
        call(Callee, E->getExprLoc());
      return true;
    }
    if (partialPolymorphicObject()) {
      if (auto *Member = dyn_cast<CXXMemberCallExpr>(E)) {
        if (ownsThis(Member->getImplicitObjectArgument()))
          reject(
              E->getExprLoc(),
              "method call on a polymorphic object during construction or destruction");
        else
          checkPartialObjectArgument(Member->getImplicitObjectArgument());
      }
      for (auto *Arg : E->arguments())
        checkPartialObjectArgument(Arg);
    }
    checkValueType(E->getType(), E->getExprLoc());
#ifdef MODULE_SAFETY_BUILTIN
    if (!Callee) {
      auto T = E->getCallee()->getType();
      if (T->isPointerType())
        T = T->getPointeeType();
      if (auto *FT = T->getAs<FunctionProtoType>();
          FT && FT->getExtInfo().getModuleSafe()) {
        if ((FT->getReturnType()->isReferenceType() ||
             modulesafety::objectBorrow(FT->getReturnType())) &&
            (!FT->getReturnBorrow() || FT->getReturnBorrow() == 65535))
          reject(E->getExprLoc(),
                 "indirect reference return has no type-level lifetime contract");
        return true;
      }
    }
#endif
    call(Callee, E->getExprLoc());
    return true;
  }
  bool VisitCXXConstructExpr(CXXConstructExpr *E) {
    if (OwnedConstruction == 1 && modulesafety::objectBorrow(E->getType()) &&
        (!modulesafety::pinnedStorage(E->getType()) ||
         !marked(E->getConstructor(), "safecpp.stores.self") ||
         !modulesafety::storedParameters(E->getConstructor()).empty()))
      reject(E->getExprLoc(),
             "owned construction requires self-only pinned borrow storage");
    if (OwnedConstruction == 2 && modulesafety::objectBorrow(E->getType()) &&
        modulesafety::storedParameters(E->getConstructor()) != std::set<unsigned>{0})
      reject(E->getExprLoc(),
             "regional construction must borrow only its owner parameter");
    for (auto *Arg : E->arguments())
      checkPartialObjectArgument(Arg);
    checkValueType(E->getType(), E->getExprLoc());
    call(E->getConstructor(), E->getExprLoc());
    if ((E->getConstructor()->isCopyConstructor() ||
         E->getConstructor()->isMoveConstructor()) &&
        modulesafety::pinnedStorage(E->getType()))
      reject(E->getExprLoc(), "copying or moving pinned storage");
    if (E->getConstructor()->isCopyConstructor() &&
        modulesafety::objectBorrow(E->getType(), true))
      reject(E->getExprLoc(), "copying an exclusive object borrow");
    if (!E->getConstructor()->getParent()->isUnion() &&
        E->getConstructor()->isDefaultConstructor() &&
        E->getConstructor()->isTrivial() && !E->requiresZeroInitialization()) {
      for (auto *Field : E->getConstructor()->getParent()->fields())
        if (!markedImplicit(Field, "safecpp.native.phantom") &&
            !Field->hasInClassInitializer())
          reject(E->getExprLoc(), "default construction leaves fields uninitialized");
    }
    return true;
  }
  bool VisitCXXInheritedCtorInitExpr(CXXInheritedCtorInitExpr *E) {
    call(E->getConstructor(), E->getExprLoc());
    return true;
  }
  bool VisitReturnStmt(ReturnStmt *S) {
    if (auto *E = S->getRetValue())
      if (E->getType()->isPointerType()) {
#ifdef MODULE_SAFETY_BUILTIN
        // Native Circle permits raw pointer values; dereference and other
        // unsafe pointer operations remain checked at their use sites.
        if (C.getLangOpts().CircleBorrowValues) return true;
        if (auto *FT = E->getType()->getPointeeType()->getAs<FunctionType>();
            FT && FT->getExtInfo().getModuleSafe())
          return true;
#endif
        reject(S->getReturnLoc(), "escaping raw pointer");
      }
    return true;
  }
  bool VisitInitListExpr(InitListExpr *E) {
    checkValueType(E->getType(), E->getExprLoc());
#ifdef MODULE_SAFETY_BUILTIN
    if (C.getLangOpts().CircleBorrowValues && E->getArrayFiller() &&
        modulesafety::objectBorrow(E->getType()))
      reject(E->getExprLoc(), "borrow arrays require every element to be initialized");
    for (const auto *Init : E->inits())
      if (C.getLangOpts().CircleBorrowValues && isa<ImplicitValueInitExpr>(Init) &&
          modulesafety::objectBorrow(Init->getType()))
        reject(E->getExprLoc(), "borrow fields require explicit initialization");
#endif
    // RecursiveASTVisitor does not include an array's implicit filler in
    // children(). Its constructor is nevertheless executed for each omitted
    // element and must cross the same safety boundary as explicit elements.
    if (auto *Filler = E->getArrayFiller())
      TraverseStmt(Filler);
    return true;
  }
  bool VisitBuiltinBitCastExpr(BuiltinBitCastExpr *E) {
    reject(E->getExprLoc(), "unchecked bit reinterpretation");
    return true;
  }
  bool VisitAtomicExpr(AtomicExpr *E) {
    reject(E->getExprLoc(), "raw atomic builtin requires a validated storage "
                            "and lifetime contract");
    return true;
  }
  bool VisitBlockExpr(BlockExpr *E) {
    reject(E->getExprLoc(), "block capture lifetime is not tracked");
    return true;
  }
  bool VisitVAArgExpr(VAArgExpr *E) {
    reject(E->getExprLoc(), "unchecked variadic argument access");
    return true;
  }
  bool VisitCXXPseudoDestructorExpr(CXXPseudoDestructorExpr *E) {
    if (!unsafeUse(E->getBase()))
      reject(E->getExprLoc(), "explicit scalar lifetime termination");
    return true;
  }
  bool VisitMSAsmStmt(MSAsmStmt *S) {
    reject(S->getBeginLoc(), "inline assembly");
    return true;
  }
  bool VisitIndirectGotoStmt(IndirectGotoStmt *S) {
    reject(S->getBeginLoc(), "computed goto");
    return true;
  }
  bool VisitStmtExpr(StmtExpr *S) {
    // A generated `match` evaluates its subject and its pattern binding in
    // nested statement expressions whose lifetimes the lowering already
    // scopes to the arm.
    if (const auto *Body = S->getSubStmt())
      for (const Stmt *Child : Body->body())
        if (const auto *Decls = dyn_cast<DeclStmt>(Child))
          for (const Decl *D : Decls->decls())
            if (const auto *Var = dyn_cast<VarDecl>(D))
              for (const auto *A : Var->specific_attrs<AnnotateAttr>())
                if (A->isImplicit() &&
                    A->getAnnotation().starts_with("safecpp.native.match"))
                  return true;
    reject(S->getBeginLoc(), "GNU statement expression with untracked lifetime");
    return true;
  }
  bool VisitGCCAsmStmt(GCCAsmStmt *S) {
    reject(S->getAsmLoc(), "inline assembly");
    return true;
  }
};
class Consumer : public ASTConsumer {
  CompilerInstance &CI;
  bool Safe;
  std::string PolicyPath;
  bool AllowPlainUnit;

public:
  Consumer(CompilerInstance &CI, bool S, std::string PolicyPath = {},
           bool AllowPlainUnit = false)
      : CI(CI), Safe(S), PolicyPath(std::move(PolicyPath)),
        AllowPlainUnit(AllowPlainUnit) {}
  void HandleTranslationUnit(ASTContext &C) override {
    // Recovery AST nodes may contain undeduced or invalid types. The normal
    // frontend has already rejected this unit; never query their layout or
    // serialize safety metadata from a failed compilation.
    if (CI.getDiagnostics().hasErrorOccurred())
      return;
    Module *M = CI.getSema().getCurrentModule();
    // Circle safety covers a whole translation unit. A checked named module is
    // one unit; an ordinary translation unit compiled with -fcircle-safety,
    // including its non-system headers, is another. The
    // plugin compatibility layer keeps its module-only contract.
    bool Named = M && M->isNamedModule();
    // Native mode selection is exclusively command-line driven. A retained
    // upstream feature directive never changes a translation unit's mode.
    bool PlainUnit = false;
#ifdef MODULE_SAFETY_BUILTIN
    PlainUnit = !M && AllowPlainUnit;
    if (PlainUnit && !Safe) return; // Ordinary legacy C/C++ keeps Clang behavior.
#else
    (void)AllowPlainUnit;
#endif
    if ((!Named && !PlainUnit) || !CI.getLangOpts().CPlusPlus20 ||
        CI.getLangOpts().CPlusPlus23 || CI.getLangOpts().ObjC ||
        CI.getLangOpts().OpenCL || CI.getLangOpts().HLSL) {
      auto &D = CI.getDiagnostics();
      D.Report(D.getCustomDiagID(
          DiagnosticsEngine::Error,
          "module-safety: only C++20 named module units are supported"));
      return;
    }
    auto &Diagnostics = CI.getDiagnostics();
    if (Safe && (CI.getLangOpts().FastMath || CI.getLangOpts().NoHonorNaNs ||
                 CI.getLangOpts().NoHonorInfs)) {
      Diagnostics.Report(Diagnostics.getCustomDiagID(
          DiagnosticsEngine::Error, "module-safety: fast/finite-only floating-point "
                                    "assumptions invalidate checked conversions"));
      return;
    }
    std::map<std::string, bool> Modes;
    std::string Primary =
        Named ? M->Name.substr(0, M->Name.find(':')) : std::string();
    std::map<std::string, bool> Policy;
    if (!PolicyPath.empty()) {
      auto Buffer = llvm::MemoryBuffer::getFile(PolicyPath);
      auto BadPolicy = [&]() {
        Diagnostics.Report(Diagnostics.getCustomDiagID(
            DiagnosticsEngine::Error,
            "module-safety: invalid or unreadable module policy '%0'"))
            << PolicyPath;
      };
      if (!Buffer) {
        BadPolicy();
        return;
      }
      auto Json = llvm::json::parse((*Buffer)->getBuffer());
      if (!Json) {
        llvm::consumeError(Json.takeError());
        BadPolicy();
        return;
      }
      auto *Object = Json->getAsObject();
      auto *Modules = Object ? Object->getObject("modules") : nullptr;
      if (!Modules || Object->getInteger("version") != 1) {
        BadPolicy();
        return;
      }
      for (const auto &Entry : *Modules) {
        auto Mode = Entry.second.getAsString();
        if (!Mode || (*Mode != "safe" && *Mode != "unsafe")) {
          BadPolicy();
          return;
        }
        Policy[Entry.first.str()] = *Mode == "safe";
      }
      auto It = Policy.find(Primary);
      if (Named && (It == Policy.end() || It->second != Safe)) {
        Diagnostics.Report(Diagnostics.getCustomDiagID(
            DiagnosticsEngine::Error,
            "module-safety: module '%0' mode conflicts with or is absent from "
            "project policy"))
            << Primary;
        return;
      }
    }
    if (auto Reader = CI.getASTReader()) {
      for (auto &File : Reader->getModuleManager()) {
        if (File.ModuleName.empty())
          continue;
        bool Found = false, ImportedSafe = false;
        for (auto *D : Reader->getModuleFileLevelDecls(File)) {
          if (D->isImplicit() &&
              (markedImplicit(D, "safecpp.module.safe.v4") ||
               markedImplicit(D, "safecpp.module.unsafe.v4")) &&
              markedImplicit(D, "safecpp.module.checker:" MODULE_SAFETY_FINGERPRINT)) {
            Found = true;
            ImportedSafe = markedImplicit(D, "safecpp.module.safe.v4");
            break;
          }
        }
        if (!Found) {
          Diagnostics.Report(Diagnostics.getCustomDiagID(
              DiagnosticsEngine::Error,
              "module-safety: imported module '%0' has no safety metadata; "
              "rebuild it with the plugin"))
              << File.ModuleName;
          continue;
        }
        Modes[File.ModuleName] = ImportedSafe;
        if (!PolicyPath.empty()) {
          auto Name = File.ModuleName.substr(0, File.ModuleName.find(':'));
          auto It = Policy.find(Name);
          if (It == Policy.end() || It->second != ImportedSafe)
            Diagnostics.Report(Diagnostics.getCustomDiagID(
                DiagnosticsEngine::Error, "module-safety: imported module '%0' "
                                          "disagrees with project policy"))
                << File.ModuleName;
        }
        if (File.ModuleName.substr(0, File.ModuleName.find(':')) == Primary &&
            ImportedSafe != Safe)
          Diagnostics.Report(Diagnostics.getCustomDiagID(
              DiagnosticsEngine::Error,
              "module-safety: mode conflicts with another unit of module '%0'"))
              << Primary;
      }
    }
    auto *TU = C.getTranslationUnitDecl();
    std::string MarkerName = "__module_safety_mode_v4_";
    // The mode marker only has to travel with a module interface. A plain
    // translation unit is not imported by anything, so it needs no marker.
    if (Named) {
      for (char Ch : M->Name)
        MarkerName += Ch == ':' || Ch == '.' ? '_' : Ch;
      auto Loc = C.getSourceManager().getLocForStartOfFile(
          C.getSourceManager().getMainFileID());
      auto *Marker = NamespaceDecl::Create(C, TU, false, Loc, Loc,
                                           &C.Idents.get(MarkerName), nullptr, false);
      Marker->setImplicit();
      Marker->setModuleOwnershipKind(Decl::ModuleOwnershipKind::VisibleWhenImported);
      Marker->setLocalOwningModule(M);
      Marker->addAttr(AnnotateAttr::CreateImplicit(
          C, Safe ? "safecpp.module.safe.v4" : "safecpp.module.unsafe.v4", nullptr, 0));
      Marker->addAttr(AnnotateAttr::CreateImplicit(
          C, "safecpp.module.checker:" MODULE_SAFETY_FINGERPRINT, nullptr, 0));
      TU->addDecl(Marker);
    }
    Checker Check(C, CI.getSema(), Safe, M, std::move(Modes));
    Check.classify(C.getTranslationUnitDecl());
    Check.TraverseDecl(C.getTranslationUnitDecl());
    Check.validatePendingBodies();
  }
};
#ifndef MODULE_SAFETY_BUILTIN
class Action : public PluginASTAction {
  bool Safe = true;
  std::string PolicyPath;
  bool ParseArgs(const CompilerInstance &CI,
                 const std::vector<std::string> &Args) override {
    if (Args.empty() || Args.size() > 2 || (Args[0] != "safe" && Args[0] != "unsafe") ||
        (Args.size() == 2 &&
         (!llvm::StringRef(Args[1]).starts_with("policy=") || Args[1].size() == 7))) {
      auto &D = CI.getDiagnostics();
      D.Report(
          D.getCustomDiagID(DiagnosticsEngine::Error,
                            "module-safety: select exactly one mode: safe or unsafe"));
      return false;
    }
    Safe = Args[0] == "safe";
    if (Args.size() == 2)
      PolicyPath = Args[1].substr(7);
    return true;
  }
  std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &CI,
                                                 llvm::StringRef) override {
    if (Safe)
      CI.getCodeGenOpts().setFiniteLoops(CodeGenOptions::FiniteLoopsKind::Never);
    // Syntax compatibility layer; these tokens are parsed by Clang as ordinary
    // annotated declarations/if-statements. This does not alter Clang's
    // grammar.
    auto &PP = CI.getPreprocessor();
    PP.setPredefines(
        PP.getPredefines() +
        "\n#define unsafe if ([[clang::annotate(\"safecpp.unsafe.scope\")]] "
        "bool safecpp_unsafe_scope = true)\n"
        "#define unsafe_fn __attribute__((annotate(\"safecpp.unsafe\")))\n");
    return std::make_unique<Consumer>(CI, Safe, PolicyPath);
  }
  ActionType getActionType() override { return AddBeforeMainAction; }
};
#endif
} // namespace
#ifdef MODULE_SAFETY_BUILTIN
std::unique_ptr<ASTConsumer> clang::CreateModuleSafetyConsumer(CompilerInstance &CI,
                                                               bool Safe) {
  return std::make_unique<Consumer>(CI, Safe,
                                    CI.getFrontendOpts().ModuleSafetyPolicyPath,
                                    /*AllowPlainUnit=*/true);
}
#else
static FrontendPluginRegistry::Add<Action>
    X("module-safety", "Explicit safety boundaries for C++20 modules");
#endif
