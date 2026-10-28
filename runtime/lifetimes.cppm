export module safety_lifetimes;
export namespace std2 {
// Each instantiation checks Callback's body and substituted owner type.
// No return-borrow contract: a reference or borrow-carrying result is rejected.
// Owning values and void may return normally.
template <auto Callback, class Owner> decltype(auto) with_borrow(Owner &owner) {
  return Callback(owner);
}
// A higher-order reborrow retains exactly the owner's checked provenance.
// Temporary owners cannot bind, and the callback cannot substitute a local.
template <auto Callback, class Owner>
__attribute__((annotate("safecpp.borrow.lifetime:region"))) decltype(auto)
map_borrow(__attribute__((annotate("safecpp.lifetime:region"))) Owner &owner) {
  return Callback(owner);
}
} // namespace std2
