#pragma once
#include <memory>
namespace clang {
class ASTConsumer;
class CompilerInstance;
std::unique_ptr<ASTConsumer> CreateModuleSafetyConsumer(CompilerInstance &,
                                                        bool);
} // namespace clang
