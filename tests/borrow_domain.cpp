// Exercise the production join/conflict functions, rather than a copied model.
#include "../src/FlowAnalysis.cpp"
#include "clang/Tooling/Tooling.h"
#include <iostream>
#include <vector>

int main() {
  auto AST = clang::tooling::buildASTFromCodeWithArgs(
      "void f(){unsigned x=0,y=0;unsigned& actor=x;unsigned& parent=y;}",
      {"-std=c++20"});
  if (!AST) return 1;
  class Variables : public clang::RecursiveASTVisitor<Variables> {
  public:
    std::map<std::string, const clang::VarDecl *> Values;
    bool VisitVarDecl(clang::VarDecl *V) {
      Values[V->getNameAsString()] = V;
      return true;
    }
  } Find;
  Find.TraverseDecl(AST->getASTContext().getTranslationUnitDecl());
  auto *Actor = Find.Values.at("actor"), *Parent = Find.Values.at("parent");
  auto *X = Find.Values.at("x"), *Y = Find.Values.at("y");
  std::vector<modulesafety::State> States;
  for (unsigned ActorRoots = 1; ActorRoots < 4; ++ActorRoots)
    for (unsigned ParentRoots = 1; ParentRoots < 4; ++ParentRoots)
      for (bool Related : {false, true})
        for (bool Exclusive : {false, true}) {
          modulesafety::State S;
          auto &A = S.Loans[Actor], &P = S.Loans[Parent];
          if (ActorRoots & 1) A.Roots.insert(X);
          if (ActorRoots & 2) A.Roots.insert(Y);
          if (ParentRoots & 1) P.Roots.insert(X);
          if (ParentRoots & 2) P.Roots.insert(Y);
          if (Related) A.Parents.insert(Parent);
          P.Exclusive = Exclusive;
          States.push_back(std::move(S));
        }
  // Include missing loans, as occurs when NLL ends a loan on one CFG path.
  auto Missing = States;
  for (auto S : Missing) {
    S.Loans.erase(Parent);
    States.push_back(std::move(S));
  }
  auto Allowed = [&](const modulesafety::State &S, bool Write) {
    const auto &A = S.Loans.at(Actor);
    return !modulesafety::hasBorrowConflict(Actor, Write, A.Roots, A.Parents, S);
  };
  unsigned Checked = 0;
  for (const auto &A : States)
    for (const auto &B : States)
      for (bool Write : {false, true}) {
        auto Joined = modulesafety::joinStates(A, B);
        if (Allowed(Joined, Write) && (!Allowed(A, Write) || !Allowed(B, Write))) {
          std::cerr << "join grants an access rejected by an incoming state\n";
          return 2;
        }
        ++Checked;
      }
  // A permission present only on one path must not survive the join.
  modulesafety::State A, B;
  A.Loans[Actor] = {{X}, true, {Parent}};
  B.Loans[Actor] = {{X}, true, {}};
  A.Loans[Parent] = B.Loans[Parent] = {{X}, true, {}};
  if (Allowed(modulesafety::joinStates(A, B), true)) return 3;
  A.RetainedBorrows[Actor] = {X};
  B.RetainedBorrows[Actor] = {Y};
  auto Retained = modulesafety::joinStates(A, B);
  if (Retained.RetainedBorrows.at(Actor) != modulesafety::Vars{X, Y})
    return 4;
  B.RetainedBorrows.clear();
  if (!modulesafety::joinStates(A, B).RetainedBorrows.at(Actor).count(X))
    return 5;
  std::cout << Checked << " production borrow-domain join/access checks passed\n";
}
