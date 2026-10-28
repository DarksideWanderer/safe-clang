#pragma once
#include "clang/AST/ASTContext.h"
#include "clang/AST/Attr.h"
#include "clang/AST/Decl.h"
#include "clang/AST/DeclCXX.h"
#include "clang/AST/DeclTemplate.h"
#include "clang/AST/ExprCXX.h"
#include "clang/AST/ExprObjC.h"
#include "clang/AST/Type.h"
#ifdef MODULE_SAFETY_BUILTIN
#include "clang/AST/CircleClassLifetime.h"
#endif
#include <optional>
#include <set>
namespace modulesafety {
// Canonical native contracts live in CircleClassLifetime.h. The CFG wrappers
// below provide no native region identity when compiling the upstream plugin.
inline unsigned projectedFunctionRegion(const clang::FunctionProtoType *T,
                                         unsigned Position, unsigned Region) {
#ifdef MODULE_SAFETY_BUILTIN
  return clang::circleProjectedFunctionRegion(T, Position, Region);
#else
  return 0;
#endif
}
inline bool functionRegionOutlives(const clang::FunctionProtoType *T,
                                   unsigned Long, unsigned Short) {
#ifdef MODULE_SAFETY_BUILTIN
  return clang::circleFunctionRegionOutlives(T, Long, Short);
#else
  return false;
#endif
}
inline bool threadSafeType(clang::QualType T, bool sharing);
inline bool objectBorrow(clang::QualType T, bool exclusiveOnly);
inline unsigned storedClassResultRegion(const clang::FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  if (auto *P = F->getType()->getAs<clang::FunctionProtoType>())
    return P->getReturnBorrowClassRegion();
#endif
  return 0;
}
inline unsigned fieldClassRegion(const clang::FieldDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  // Phantom data carries a lifetime projection but no storage and no
  // constructor or destructor requirement.
  if (F)
    for (const auto *A : F->specific_attrs<clang::AnnotateAttr>())
      if (A->getAnnotation() == "safecpp.native.phantom")
        return 0;
  return clang::circleFieldLifetime(F);
#else
  return 0;
#endif
}
// The lifetime region a field projects, including a phantom field. Phantom
// storage is not a physical region, but its type is exactly how a class value
// records which caller region its generated borrow results depend on.
inline unsigned fieldLifetimeRegion(const clang::FieldDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  return clang::circleFieldLifetime(F);
#else
  return 0;
#endif
}
inline bool hasClassLifetimeFields(clang::QualType T) {
#ifdef MODULE_SAFETY_BUILTIN
  const auto *R = clang::circleClassRecord(T);
  if (R && R->hasDefinition())
    for (auto *F : R->getDefinition()->fields())
      if (fieldClassRegion(F)) return true;
#endif
  return false;
}
inline bool hasPhantomLifetimeFields(clang::QualType T) {
#ifdef MODULE_SAFETY_BUILTIN
  const auto *R = clang::circleClassRecord(T);
  if (R && R->hasDefinition())
    for (auto *F : R->getDefinition()->fields())
      if (F->isCirclePhantom()) return true;
#endif
  return false;
}
/// A class value carrying several regions through direct scalar borrow fields.
/// Such a result has no single region: each field is checked against the
/// parameter bound to the region the result type names for that field.
inline bool multiRegionClassValue(clang::QualType T) {
#ifdef MODULE_SAFETY_BUILTIN
  return clang::circleMultiRegionClassValue(T);
#else
  return false;
#endif
}
/// The region names a class value's type binds, in the record's own region
/// order. Empty when the type carries no class-lifetime arguments.
inline std::vector<llvm::StringRef> classLifetimeBindingNames(clang::QualType T) {
  std::vector<llvm::StringRef> Names;
#ifdef MODULE_SAFETY_BUILTIN
  if (const auto *Binding = clang::circleClassLifetimeBinding(T))
    for (const auto *Argument : Binding->getArguments())
      if (Argument) Names.push_back(Argument->getName());
#endif
  return Names;
}
/// The lifetime label a binding parameter declares, or an empty name for a
/// parameter that binds no region.
inline llvm::StringRef parameterLifetimeLabel(const clang::ParmVarDecl *P) {
  if (!P) return {};
  for (const auto *A : P->specific_attrs<clang::AnnotateAttr>()) {
    if (!A->isImplicit()) continue;
    auto Text = A->getAnnotation();
    if (Text.consume_front("safecpp.native.lifetime:")) return Text;
  }
  return {};
}
inline bool marked(const clang::Decl *D, llvm::StringRef Tag) {
  for (auto *A : D->specific_attrs<clang::AnnotateAttr>())
    if (A->getAnnotation() == Tag)
      return true;
  return false;
}
// A `T+` template parameter declares that the class carries the regions of
// its actual argument. Its special members and fields are projected through
// that parameter even though no explicit `/a` binder was written.
inline bool hasLifetimeBinderParameter(const clang::CXXRecordDecl *R) {
  if (!R) return false;
  const clang::TemplateParameterList *List = nullptr;
  if (auto *Spec = llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(R))
    if (auto *Template = Spec->getSpecializedTemplate())
      List = Template->getTemplateParameters();
  if (!List)
    if (auto *Template = R->getDescribedClassTemplate())
      List = Template->getTemplateParameters();
  if (!List) return false;
  for (auto *P : List->asArray())
    if (llvm::isa<clang::TemplateTypeParmDecl>(P) &&
        marked(P, "safecpp.native.lifetime_binder"))
      return true;
  return false;
}
inline bool staticLifetimeField(const clang::FieldDecl *Field) {
  if (!Field) return false;
#ifdef MODULE_SAFETY_BUILTIN
  if (clang::circleClassHasStaticArguments(Field->getType())) return true;
  if (clang::circleClassRegionIsStatic(
          clang::dyn_cast<clang::CXXRecordDecl>(Field->getParent()), fieldClassRegion(Field)))
    return true;
#endif
  for (auto *A : Field->specific_attrs<clang::AnnotateAttr>())
    if (A->isImplicit() &&
        A->getAnnotation() == "safecpp.native.class.field_lifetime:static")
      return true;
  return false;
}
inline bool hasStaticLifetimeFields(clang::QualType Type) {
  if (Type.isNull() || Type->isDependentType()) return false;
  auto *Record = Type->getAsCXXRecordDecl();
  if (!Record || !Record->hasDefinition()) return false;
  for (auto *Field : Record->getDefinition()->fields())
    if (staticLifetimeField(Field)) return true;
  return false;
}
/// The annotation a declaration carries under \p Tag, or null.
inline const clang::AnnotateAttr *marker(const clang::Decl *D,
                                         llvm::StringRef Tag) {
  for (auto *A : D->specific_attrs<clang::AnnotateAttr>())
    if (A->getAnnotation() == Tag)
      return A;
  return nullptr;
}
/// Whether a claim a contract annotation carries holds for this declaration.
///
/// A contract written `[[unsafe::send(T~is_send)]]` is conditional: the
/// argument is recorded on the annotation, and instantiating the template
/// substitutes it and recomputes the property it names, so the claim is read
/// here per instantiation. An argument that is not yet known — the pattern of
/// a template being checked where it is defined — stands for the claim.
inline bool holdsClaim(const clang::AnnotateAttr *A, clang::ASTContext &Ctx) {
  for (clang::Expr *Arg : A->args()) {
    if (!Arg)
      continue;
    if (Arg->isValueDependent() || Arg->isInstantiationDependent())
      continue;
    // A claim that names a property of a type which is not known yet — the
    // pattern of a template being checked where it is defined — stands for the
    // claim; instantiation substitutes the type and recomputes the property.
    if (auto *Trait = llvm::dyn_cast<clang::TypeTraitExpr>(
            Arg->IgnoreParenImpCasts())) {
      bool Unknown = false;
      for (unsigned I = 0, N = Trait->getNumArgs(); I != N && !Unknown; ++I) {
        clang::QualType Queried = Trait->getArg(I)->getType();
        Unknown = Queried.isNull() || Queried->isDependentType() ||
                  Queried->isInstantiationDependentType();
      }
      if (Unknown)
        continue;
    }
    bool Value = false;
    if (Arg->EvaluateAsBooleanCondition(Value, Ctx) && !Value)
      return false;
  }
  return true;
}
inline bool returnsStatic(const clang::FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  if (auto *Proto = F->getType()->getAs<clang::FunctionProtoType>();
      Proto && Proto->getReturnBorrow() == 0x40000000u) return true;
#endif
  return marked(F, "safecpp.borrow.static");
}
inline bool staticBorrowVariable(const clang::VarDecl *V) {
#ifdef MODULE_SAFETY_BUILTIN
  bool Borrow = V->getType()->getAs<clang::BorrowValueType>() != nullptr;
  if (auto *Ref = V->getType()->getAs<clang::ReferenceType>()) Borrow |= Ref->isSafetyBorrow();
  if (Borrow)
    for (auto *A : V->specific_attrs<clang::AnnotateAttr>())
      if (A->isImplicit() && A->getAnnotation() == "safecpp.native.lifetime:static") return true;
#endif
  return false;
}
inline bool returnsGenerative(const clang::FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  if (auto *Proto = F->getType()->getAs<clang::FunctionProtoType>())
    return Proto->hasGenerativeReturnLifetime();
#endif
  return false;
}
inline std::set<unsigned> borrowRegions(unsigned Region) {
  std::set<unsigned> Result;
  if (Region == 0x40000000u || Region == 0x10000000u)
    return Result;
  if (Region & 0x80000000u) {
    for (unsigned I = 0; I < 31; ++I)
      if (Region & (1u << I))
        Result.insert(I);
  } else if (Region && Region != 65535)
    Result.insert(Region - 1);
  return Result;
}
inline std::set<unsigned> contractParameters(const clang::FunctionDecl *F,
                                             llvm::StringRef Text,
                                             llvm::StringRef Direct,
                                             llvm::StringRef Named) {
  std::set<unsigned> Result;
  bool ByName = false;
  if (!Text.consume_front(Direct)) {
    if (!Text.consume_front(Named))
      return Result;
    ByName = true;
  }
  for (unsigned I = 0; I < F->getNumParams(); ++I) {
    auto *P = F->getParamDecl(I);
    if (!ByName && P->getName() == Text)
      Result.insert(I);
    if (ByName)
      for (auto *A : P->specific_attrs<clang::AnnotateAttr>()) {
        auto Label = A->getAnnotation();
        if (Label.consume_front("safecpp.lifetime:") && Label == Text)
          Result.insert(I);
      }
  }
  return Result;
}
inline std::set<unsigned> borrowedParameters(const clang::FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  if (auto *P = F->getType()->getAs<clang::FunctionProtoType>();
      P && P->getReturnBorrow()) {
    auto Sources = P->getReturnBorrowSources();
    // A dependent declaration records the elision marker before the actual
    // source exists. Fall through so the specialization can recover it.
    if (!Sources.empty())
      return {Sources.begin(), Sources.end()};
  }
#endif
  std::set<unsigned> Result;
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>()) {
      auto Sources = contractParameters(
          R, A->getAnnotation(), "safecpp.borrow.from:", "safecpp.borrow.lifetime:");
      Result.insert(Sources.begin(), Sources.end());
    }
#ifdef MODULE_SAFETY_BUILTIN
  // Lifetime elision is applied when a non-dependent declaration is formed.
  // A dependent `T^` result only becomes concrete during instantiation, so
  // the specialization still needs the same rule: an explicit-self method's
  // result borrows from its first parameter.
  if (Result.empty()) {
    if (auto *P = F->getType()->getAs<clang::FunctionProtoType>();
        P && !P->hasGenerativeReturnLifetime() &&
        (P->getReturnType()->getAs<clang::BorrowValueType>() ||
         (!P->getReturnType()->isReferenceType() &&
          modulesafety::objectBorrow(P->getReturnType(), false)))) {
      if (auto *Method = llvm::dyn_cast<clang::CXXMethodDecl>(F);
          Method && !Method->getParent()->isLambda() && Method->getNumParams() &&
          (Method->getParamDecl(0)->getType()->getAs<clang::BorrowValueType>() ||
           modulesafety::objectBorrow(Method->getParamDecl(0)->getType(), false)))
        Result.insert(0);
    }
    // A checked generic function may carry the return value's regions through
    // a function lifetime binder even when its dependent return type has no
    // concrete borrow spelling at definition time. At instantiation, the
    // parameter bound to the same region is the result's source.
    if (Result.empty()) {
      if (auto *P = F->getType()->getAs<clang::FunctionProtoType>();
          P && !P->getLifetimeBindings().empty() &&
          !P->getReturnType()->isReferenceType() &&
          modulesafety::objectBorrow(P->getReturnType(), false)) {
        auto ReturnType = P->getReturnType();
        for (unsigned I = 0; I < F->getNumParams(); ++I) {
          auto *Param = F->getParamDecl(I);
          if (modulesafety::parameterLifetimeLabel(Param).empty())
            continue;
          auto ParamType = Param->getType();
          if (auto *Borrow = ParamType->getAs<clang::BorrowValueType>())
            ParamType = Borrow->getPointeeType();
          if (F->getASTContext().hasSameUnqualifiedType(ReturnType, ParamType))
            Result.insert(I);
        }
      }
    }
  }
#endif
  return Result;
}
inline std::set<unsigned> storedParameters(const clang::FunctionDecl *F) {
  std::set<unsigned> Result;
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>()) {
      if (A->isInherited())
        continue;
      auto Sources = contractParameters(
          R, A->getAnnotation(), "safecpp.stores.borrow:", "safecpp.stores.lifetime:");
      Result.insert(Sources.begin(), Sources.end());
    }
  return Result;
}
inline bool hasAdoptionContract(const clang::FunctionDecl *F) {
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>())
      if (A->getAnnotation().starts_with("safecpp.unsafe.adopts.borrow:")) return true;
  return false;
}
inline std::set<unsigned> adoptedParameters(const clang::FunctionDecl *F) {
  std::set<unsigned> Result;
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>()) {
      if (A->isInherited()) continue;
      auto Tag = A->getAnnotation();
      if (!Tag.consume_front("safecpp.unsafe.adopts.borrow:")) continue;
      for (unsigned I = 0; I < R->getNumParams(); ++I)
        if (R->getParamDecl(I)->getName() == Tag) Result.insert(I);
    }
  return Result;
}
inline std::optional<unsigned> transferredBorrow(const clang::FunctionDecl *F) {
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>()) {
      auto Text = A->getAnnotation();
      if (!Text.consume_front("safecpp.transfers.borrow:"))
        continue;
      for (unsigned I = 0; I < R->getNumParams(); ++I)
        if (R->getParamDecl(I)->getName() == Text)
          return I;
    }
  return std::nullopt;
}
// Contracts are checked against every return, not accepted as an assertion.
inline std::optional<unsigned> borrowedParameter(const clang::FunctionDecl *F) {
#ifdef MODULE_SAFETY_BUILTIN
  if (auto *Proto = F->getType()->getAs<clang::FunctionProtoType>()) {
    unsigned Region = Proto->getReturnBorrow();
    if (Region && Region != 65535 && Region <= F->getNumParams())
      return Region - 1;
  }
#endif
  for (auto *R : F->redecls())
    for (auto *A : R->specific_attrs<clang::AnnotateAttr>()) {
      llvm::StringRef Text = A->getAnnotation();
      if (!Text.consume_front("safecpp.borrow.from:"))
        continue;
      for (unsigned I = 0; I < F->getNumParams(); ++I)
        if (R->getParamDecl(I)->getName() == Text)
          return I;
    }
  return std::nullopt;
}
} // namespace modulesafety

namespace modulesafety {
// Borrow regions are structural: nested aggregate fields carry their owners.
inline bool scalarUnion(const clang::CXXRecordDecl *R) {
  if (!R || !R->hasDefinition() || !R->isUnion())
    return false;
  R = R->getDefinition();
  if (!R->isTriviallyCopyable() || !R->hasTrivialDestructor() ||
      R->isAnonymousStructOrUnion())
    return false;
  for (auto *Field : R->fields())
    if (!Field->getType()->isArithmeticType() ||
        Field->getType().isVolatileQualified() || Field->isBitField() ||
        Field->hasAttr<clang::PackedAttr>())
      return false;
  return true;
}
inline bool nativeCallableValue(clang::QualType T) {
#ifdef MODULE_SAFETY_BUILTIN
  return clang::circleIsCallableValue(T);
#else
  return false;
#endif
}
inline bool objectBorrowImpl(clang::QualType T, bool exclusiveOnly,
                             std::set<const clang::CXXRecordDecl *> &Seen) {
  if (T.isNull() || T->isDependentType())
    return false;
#ifdef MODULE_SAFETY_BUILTIN
  if (clang::circleIsCallableValue(T) && !clang::circleCallableCaptures(T).empty())
    return !exclusiveOnly;
  if (auto *Borrow = T->getAs<clang::BorrowValueType>()) {
    auto Pointee = Borrow->getPointeeType();
    bool Shared = Pointee.isConstQualified();
    if (auto *Slice = Pointee->getAs<clang::NativeSliceType>())
      Shared |= Slice->getElementType().isConstQualified();
    if (auto *Record = Pointee->getAsCXXRecordDecl())
      Shared |= Record->getASTContext().circleBorrowIsShared(Borrow);
    return !exclusiveOnly || !Shared ||
           objectBorrowImpl(Pointee, true, Seen);
  }
#endif
  if (T->isReferenceType())
    return !exclusiveOnly || !T->getPointeeType().isConstQualified() ||
           objectBorrowImpl(T->getPointeeType(), true, Seen);
  if (auto *A = T->getAsArrayTypeUnsafe())
    return objectBorrowImpl(A->getElementType(), exclusiveOnly, Seen);
  auto *R = T->getAsCXXRecordDecl();
  if (!R || !R->hasDefinition())
    return false;
  R = R->getDefinition();
  if (!Seen.insert(R).second)
    return false;
  for (auto *F : R->fields())
    if (objectBorrowImpl(F->getType(), exclusiveOnly, Seen))
      return true;
  for (const auto &B : R->bases())
    if (objectBorrowImpl(B.getType(), exclusiveOnly, Seen))
      return true;
  return false;
}
inline bool objectBorrow(clang::QualType T, bool exclusiveOnly = false) {
  std::set<const clang::CXXRecordDecl *> Seen;
  return objectBorrowImpl(T, exclusiveOnly, Seen);
}
inline bool pinnedStorageImpl(clang::QualType T,
                              std::set<const clang::CXXRecordDecl *> &Seen) {
  if (T.isNull() || T->isReferenceType() || T->isDependentType())
    return false;
  if (auto *A = T->getAsArrayTypeUnsafe())
    return pinnedStorageImpl(A->getElementType(), Seen);
  auto *R = T->getAsCXXRecordDecl();
  if (!R || !R->hasDefinition())
    return false;
  R = R->getDefinition();
  if (!Seen.insert(R).second)
    return false;
  if (marked(R, "safecpp.pinned"))
    return true;
  for (auto *F : R->fields())
    if (pinnedStorageImpl(F->getType(), Seen))
      return true;
  for (const auto &B : R->bases())
    if (pinnedStorageImpl(B.getType(), Seen))
      return true;
  return false;
}
inline bool pinnedStorage(clang::QualType T) {
  std::set<const clang::CXXRecordDecl *> Seen;
  return pinnedStorageImpl(T, Seen);
}
inline bool movedDropSafe(clang::QualType T) {
  auto *R = T->getAsCXXRecordDecl();
  return R && R->hasDefinition() &&
         (R->getDefinition()->hasTrivialDestructor() ||
          marked(R->getDefinition(), "safecpp.unsafe.moved.drop"));
}
// In a checked interface, && qualifies an affine (consuming) receiver.
// Ordinary and explicitly unsafe C++ methods retain C++ reference semantics.
inline bool consumingReceiver(const clang::CXXMethodDecl *M) {
  return M && !M->isStatic() && M->getRefQualifier() == clang::RQ_RValue &&
         marked(M, "safecpp.safe") && !marked(M, "safecpp.unsafe");
}
// A method whose body relocates its receiver ends the caller's ownership of
// it: naming the receiver again is the use of a moved value. The classifier
// marks such a method while it checks the body, so the contract also holds
// when the definition is imported from a module and the body is not available.
inline bool consumesReceiver(const clang::CXXMethodDecl *M) {
  return M && !M->isStatic() &&
         (marked(M, "safecpp.native.consumes.receiver") ||
          consumingReceiver(M));
}
// A member-function pointer with a locally visible constant initializer still
// names exactly one checked method. Resolving it lets a safe indirect call
// retain the method's receiver, lifetime, and effect contracts. Data-member
// pointers and member pointers whose target is not visible stay unresolved
// and are rejected by the caller.
inline const clang::CXXMethodDecl *
knownMemberFunctionPointer(const clang::Expr *E) {
  if (!E) return nullptr;
  E = E->IgnoreParenImpCasts();
  if (auto *U = clang::dyn_cast<clang::UnaryOperator>(E);
      U && U->getOpcode() == clang::UO_AddrOf) {
    E = U->getSubExpr()->IgnoreParenImpCasts();
    if (auto *D = clang::dyn_cast<clang::DeclRefExpr>(E))
      if (auto *M = clang::dyn_cast<clang::CXXMethodDecl>(D->getDecl());
          M && (!M->isVirtual() || M->getParent()->isEffectivelyFinal()))
        return M;
    return nullptr;
  }
  if (auto *D = clang::dyn_cast<clang::DeclRefExpr>(E))
    if (auto *V = clang::dyn_cast<clang::VarDecl>(D->getDecl());
        V && V->hasInit() && V->getType().isConstQualified())
      return knownMemberFunctionPointer(V->getInit());
  return nullptr;
}
inline const clang::CXXMethodDecl *
indirectMemberCallee(const clang::CallExpr *Call) {
  if (!Call || Call->getDirectCallee()) return nullptr;
  const clang::Expr *Callee = Call->getCallee()->IgnoreParenImpCasts();
  if (auto *B = clang::dyn_cast<clang::BinaryOperator>(Callee);
      B && (B->getOpcode() == clang::BO_PtrMemD ||
            B->getOpcode() == clang::BO_PtrMemI))
    return knownMemberFunctionPointer(B->getRHS());
  if (auto *Member = clang::dyn_cast<clang::MemberExpr>(Callee))
    return clang::dyn_cast_or_null<clang::CXXMethodDecl>(
        Member->getMemberDecl());
  return nullptr;
}
inline bool
threadSafeTypeImpl(clang::QualType T, bool sharing,
                   std::set<std::pair<const clang::CXXRecordDecl *, bool>> &Seen) {
  if (T.isNull() || T->isDependentType() || T.isVolatileQualified())
    return false;
  if (T->isReferenceType())
    return sharing
               ? (T->getPointeeType().isConstQualified() &&
                  threadSafeTypeImpl(T->getPointeeType(), true, Seen))
               : threadSafeTypeImpl(T->getPointeeType(),
                                    T->getPointeeType().isConstQualified(), Seen);
  if (T->isPointerType() || T->isMemberPointerType() || T->isAtomicType())
    return false;
  if (T->isArithmeticType() || T->isEnumeralType())
    return true;
  if (auto *A = T->getAsArrayTypeUnsafe())
    return threadSafeTypeImpl(A->getElementType(), sharing, Seen);
  auto *R = T->getAsCXXRecordDecl();
  if (!R || !R->hasDefinition() || (R->isUnion() && !scalarUnion(R)))
    return false;
  R = R->getDefinition();
  // Check recursive owning types coinductively before following their pointee.
  if (!Seen.insert({R, sharing}).second)
    return true;
  if (marked(R, "safecpp.unsafe.pinned.owner")) {
    auto *Spec = llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(R);
    return Spec && Spec->getTemplateArgs().size() == 1 &&
           Spec->getTemplateArgs()[0].getKind() == clang::TemplateArgument::Type &&
           threadSafeTypeImpl(Spec->getTemplateArgs()[0].getAsType(), sharing, Seen);
  }
  if (marked(R, "safecpp.unsafe.pinned.region")) {
    auto *Spec = llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(R);
    return Spec && Spec->getTemplateArgs().size() == 2 &&
           Spec->getTemplateArgs()[0].getKind() == clang::TemplateArgument::Type &&
           Spec->getTemplateArgs()[1].getKind() == clang::TemplateArgument::Type &&
           threadSafeTypeImpl(Spec->getTemplateArgs()[0].getAsType(), sharing, Seen) &&
           threadSafeTypeImpl(Spec->getTemplateArgs()[1].getAsType(), sharing, Seen);
  }
  if (marked(R, "safecpp.unsafe.exclusive.sequence")) {
    auto *Spec = llvm::dyn_cast<clang::ClassTemplateSpecializationDecl>(R);
    return !sharing && Spec && Spec->getTemplateArgs().size() == 2 &&
           Spec->getTemplateArgs()[0].getKind() == clang::TemplateArgument::Type &&
           Spec->getTemplateArgs()[1].getKind() == clang::TemplateArgument::Type &&
           threadSafeTypeImpl(Spec->getTemplateArgs()[0].getAsType(), false, Seen) &&
           threadSafeTypeImpl(Spec->getTemplateArgs()[1].getAsType(), false, Seen);
  }
  // A contract the frontend resolved for this instantiation is a value: the
  // property holds when the claim held for the arguments the instantiation was
  // written with.
  if (marked(R, sharing ? "safecpp.thread.sync" : "safecpp.thread.send"))
    return true;
  if (marked(R, sharing ? "safecpp.unsync" : "safecpp.unsend"))
    return false;
  if (const auto *Impl =
          marker(R, sharing ? "safecpp.unsafe.impl.sync"
                            : "safecpp.unsafe.impl.send")) {
    // A contract may be conditional — `[[unsafe::send(T~is_send)]]` — in which
    // case the argument is recorded on the annotation, instantiation
    // substitutes it, and the claim is read here with this checker's own
    // judgement of the property it names.
    return holdsClaim(Impl, R->getASTContext());
  }
  for (auto *F : R->fields())
    if (F->isMutable() || !threadSafeTypeImpl(F->getType(), sharing, Seen))
      return false;
  for (const auto &B : R->bases())
    if (!threadSafeTypeImpl(B.getType(), sharing, Seen))
      return false;
  Seen.erase({R, sharing});
  return true;
}
inline bool threadSafeType(clang::QualType T, bool sharing) {
  std::set<std::pair<const clang::CXXRecordDecl *, bool>> Seen;
  return threadSafeTypeImpl(T, sharing, Seen);
}
// An audited sequence's element storage. The sequence declares that the
// elements it keeps in this field were adopted from the region its stored
// borrow contract names, so an element read through this field borrows that
// region. The declaration is a library contract like the other
// `safecpp.unsafe.*` markers: the checked write paths verify each adopted
// element against the receiver's region, and the checker refuses a storage
// field that is not attached to an audited sequence.
inline bool sequenceStorageField(const clang::FieldDecl *F) {
  return F && marked(F, "safecpp.unsafe.sequence.storage");
}
inline bool auditedSequence(const clang::CXXRecordDecl *R) {
  return R && (marked(R, "safecpp.unsafe.borrowed.sequence") ||
               marked(R, "safecpp.unsafe.exclusive.sequence"));
}
} // namespace modulesafety
