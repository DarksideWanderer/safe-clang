#pragma once
#include "clang/AST/Expr.h"
#include "clang/AST/ASTTypeTraits.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "llvm/ADT/DenseMap.h"
#include "llvm/ADT/SmallPtrSet.h"
#include <map>

namespace modulesafety {
// A single-evaluation binding has the provenance of the expression it binds.
// A pseudo-object carries the provenance of its semantic result. This is a
// representation query only: CFG/CodeGen still evaluate each binding once.
inline const clang::Expr *evaluationSource(const clang::Expr *E) {
  while (E) {
    if (const auto *Value = llvm::dyn_cast<clang::OpaqueValueExpr>(E);
        Value && Value->getSourceExpr()) E = Value->getSourceExpr();
    else if (const auto *Object = llvm::dyn_cast<clang::PseudoObjectExpr>(E);
             Object && Object->getResultExpr()) E = Object->getResultExpr();
    else break;
  }
  return E;
}
// RAV visits both forms of an initializer list when implicit code is enabled.
// Those forms share children, so revisiting a nested pair doubles its subtree
// at every level. Keep both forms' callbacks, but traverse each pair once per
// checking context. In particular, an unchecked visit must not suppress a
// later checked visit to a shared default initializer.
template <typename Context = unsigned> class InitListVisitSet {
  std::map<Context, llvm::SmallPtrSet<const clang::InitListExpr *, 32>> Seen;

public:
  bool enter(const clang::Stmt *S, const Context &C = Context()) {
    const auto *List = llvm::dyn_cast<clang::InitListExpr>(S);
    if (!List) return true;
    if (const auto *Semantic = List->getSemanticForm()) List = Semantic;
    return Seen[C].insert(List).second;
  }
};

// The CFG needs statement/declaration ancestry in the function being checked,
// not the translation unit's TypeLoc/attribute ancestry. Building Clang's full
// parent map also walks uninstantiated initializer DAGs throughout the TU.
// Record every incoming edge before deduplicating each node's descendants:
// a shared expression keeps all parents rather than picking its first use.
class AnalysisParents : public clang::RecursiveASTVisitor<AnalysisParents> {
  using Nodes = llvm::SmallVector<clang::DynTypedNode, 2>;
  llvm::DenseMap<const void *, Nodes> Parents;
  llvm::SmallVector<clang::DynTypedNode, 16> Stack;
  llvm::SmallPtrSet<const clang::Stmt *, 32> Statements;
  llvm::SmallPtrSet<const clang::Decl *, 32> Declarations;

  void record(const void *Node) {
    if (Stack.empty()) return;
    auto &Result = Parents[Node];
    if (!llvm::is_contained(Result, Stack.back())) Result.push_back(Stack.back());
  }

public:
  bool shouldVisitImplicitCode() const { return true; }
  bool TraverseTypeLoc(clang::TypeLoc, bool = true) { return true; }
  bool TraverseDecl(clang::Decl *D) {
    if (!D) return true;
    record(D);
    if (!Declarations.insert(D).second) return true;
    Stack.push_back(clang::DynTypedNode::create(*D));
    bool Result = RecursiveASTVisitor::TraverseDecl(D);
    Stack.pop_back();
    return Result;
  }
  bool dataTraverseStmtPre(clang::Stmt *S) {
    record(S);
    if (!Statements.insert(S).second) return false;
    Stack.push_back(clang::DynTypedNode::create(*S));
    return true;
  }
  bool dataTraverseStmtPost(clang::Stmt *) {
    Stack.pop_back();
    return true;
  }
  llvm::ArrayRef<clang::DynTypedNode> get(const clang::DynTypedNode &Node) const {
    auto I = Parents.find(Node.getMemoizationData());
    return I == Parents.end() ? llvm::ArrayRef<clang::DynTypedNode>() : I->second;
  }
};
} // namespace modulesafety
