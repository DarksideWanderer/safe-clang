#pragma once
#include "clang/AST/ASTContext.h"
#include "clang/AST/Decl.h"
#include <functional>
namespace modulesafety {
using CheckCall =
    std::function<void(const clang::FunctionDecl *, clang::SourceLocation)>;
void analyzeFunction(clang::ASTContext &, clang::FunctionDecl *, CheckCall,
                     bool ContractsOnly = false);
void analyzeInitializer(clang::ASTContext &, clang::VarDecl *, CheckCall,
                        bool ContractsOnly = false);
} // namespace modulesafety
