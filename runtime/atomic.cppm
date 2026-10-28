module;
#include <atomic>
export module safety_atomic;
import safety;
export namespace std2 {
namespace memory_order {
inline constexpr unsigned relaxed = 0u, acquire = 1u, release = 2u, acq_rel = 3u,
                          seq_cst = 4u;
}
namespace atomic_detail {
template <unsigned Order> unsafe_fn constexpr std::memory_order native_order() {
  static_assert(Order <= memory_order::seq_cst, "invalid atomic memory order");
  if constexpr (Order == memory_order::relaxed)
    return std::memory_order_relaxed;
  if constexpr (Order == memory_order::acquire)
    return std::memory_order_acquire;
  if constexpr (Order == memory_order::release)
    return std::memory_order_release;
  if constexpr (Order == memory_order::acq_rel)
    return std::memory_order_acq_rel;
  return std::memory_order_seq_cst;
}
} // namespace atomic_detail
template <class T>
concept atomic_value = __is_integral(T) || __is_pointer(T);
template <atomic_value T> struct exchange_result {
  bool exchanged;
  T previous;
};
// Orders are compile-time arguments. No raw pointers or references to the
// atomic's storage escape, and all operations check moved-from handles.
template <atomic_value T>
class __attribute__((annotate("safecpp.unsafe.impl.send"),
                     annotate("safecpp.unsafe.impl.sync"))) atomic {
  static_assert(sizeof(T) <= sizeof(unsigned long long),
                "atomic supports integers up to 64 bits");
  std::atomic<T> *state_ = nullptr;

public:
  explicit atomic(T initial = T{}) {
    unsafe { state_ = new std::atomic<T>(initial); }
  }
  atomic(const atomic &) = delete;
  atomic &operator=(const atomic &) = delete;
  atomic(atomic &&other) noexcept {
    unsafe {
      state_ = other.state_;
      other.state_ = nullptr;
    }
  }
  ~atomic() {
    unsafe { delete state_; }
  }
  template <unsigned Order = memory_order::seq_cst> T load() const {
    static_assert(Order == memory_order::relaxed || Order == memory_order::acquire ||
                      Order == memory_order::seq_cst,
                  "invalid atomic load order");
    if (state_ == nullptr)
      panic();
    unsafe { return state_->load(atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst> void store(T value) const {
    static_assert(Order == memory_order::relaxed || Order == memory_order::release ||
                      Order == memory_order::seq_cst,
                  "invalid atomic store order");
    if (state_ == nullptr)
      panic();
    unsafe { state_->store(value, atomic_detail::native_order<Order>()); }
  }
  template <unsigned Order = memory_order::seq_cst> T exchange(T value) const {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->exchange(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  // std::atomic integral addition has defined two's-complement wraparound,
  // including signed T. This is deliberately distinct from checked_add.
  template <unsigned Order = memory_order::seq_cst>
  T fetch_add(T value) const
    requires integer<T>
  {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->fetch_add(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Success = memory_order::seq_cst,
            unsigned Failure = (Success == memory_order::release ? memory_order::relaxed
                                : Success == memory_order::acq_rel
                                    ? memory_order::acquire
                                    : Success)>
  exchange_result<T> compare_exchange(T expected, T desired) const {
    static_assert(Failure == memory_order::relaxed ||
                      Failure == memory_order::acquire ||
                      Failure == memory_order::seq_cst,
                  "invalid atomic CAS failure order");
    if (state_ == nullptr)
      panic();
    unsafe {
      bool changed = state_->compare_exchange_strong(
          expected, desired, atomic_detail::native_order<Success>(),
          atomic_detail::native_order<Failure>());
      return {changed, expected};
    }
    panic();
  }
  template <unsigned Success = memory_order::seq_cst,
            unsigned Failure = (Success == memory_order::release ? memory_order::relaxed
                                : Success == memory_order::acq_rel
                                    ? memory_order::acquire
                                    : Success)>
  exchange_result<T> compare_exchange_weak(T expected, T desired) const {
    static_assert(Failure == memory_order::relaxed ||
                      Failure == memory_order::acquire ||
                      Failure == memory_order::seq_cst,
                  "invalid atomic CAS failure order");
    if (state_ == nullptr)
      panic();
    unsafe {
      bool changed = state_->compare_exchange_weak(
          expected, desired, atomic_detail::native_order<Success>(),
          atomic_detail::native_order<Failure>());
      return {changed, expected};
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_sub(T value) const
    requires integer<T>
  {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->fetch_sub(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_and(T value) const
    requires integer<T>
  {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->fetch_and(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_or(T value) const
    requires integer<T>
  {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->fetch_or(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_xor(T value) const
    requires integer<T>
  {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->fetch_xor(value, atomic_detail::native_order<Order>()); }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_add(__PTRDIFF_TYPE__ difference) const
    requires(__is_pointer(T))
  {
    if (state_ == nullptr)
      panic();
    unsafe {
      return state_->fetch_add(difference, atomic_detail::native_order<Order>());
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_sub(__PTRDIFF_TYPE__ difference) const
    requires(__is_pointer(T))
  {
    if (state_ == nullptr)
      panic();
    unsafe {
      return state_->fetch_sub(difference, atomic_detail::native_order<Order>());
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_and(bool value) const
    requires(__is_same(T, bool))
  {
    if (state_ == nullptr)
      panic();
    unsafe {
      bool previous = state_->load(std::memory_order_relaxed);
      while (!state_->compare_exchange_weak(previous, bool(previous & value),
                                            atomic_detail::native_order<Order>(),
                                            std::memory_order_relaxed)) {
      }
      return previous;
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_or(bool value) const
    requires(__is_same(T, bool))
  {
    if (state_ == nullptr)
      panic();
    unsafe {
      bool previous = state_->load(std::memory_order_relaxed);
      while (!state_->compare_exchange_weak(previous, bool(previous | value),
                                            atomic_detail::native_order<Order>(),
                                            std::memory_order_relaxed)) {
      }
      return previous;
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst>
  T fetch_xor(bool value) const
    requires(__is_same(T, bool))
  {
    if (state_ == nullptr)
      panic();
    unsafe {
      bool previous = state_->load(std::memory_order_relaxed);
      while (!state_->compare_exchange_weak(previous, bool(previous ^ value),
                                            atomic_detail::native_order<Order>(),
                                            std::memory_order_relaxed)) {
      }
      return previous;
    }
    panic();
  }
  template <unsigned Order = memory_order::seq_cst> void wait(T old) const {
    static_assert(Order == memory_order::relaxed || Order == memory_order::acquire ||
                      Order == memory_order::seq_cst,
                  "invalid atomic wait order");
    if (state_ == nullptr)
      panic();
    unsafe { state_->wait(old, atomic_detail::native_order<Order>()); }
  }
  void notify_one() const {
    if (state_ == nullptr)
      panic();
    unsafe { state_->notify_one(); }
  }
  void notify_all() const {
    if (state_ == nullptr)
      panic();
    unsafe { state_->notify_all(); }
  }
  bool is_lock_free() const {
    if (state_ == nullptr)
      panic();
    unsafe { return state_->is_lock_free(); }
    panic();
  }
};
template <unsigned Order = memory_order::seq_cst> void atomic_fence() {
  static_assert(Order == memory_order::acquire || Order == memory_order::release ||
                    Order == memory_order::acq_rel || Order == memory_order::seq_cst,
                "invalid atomic fence order");
  unsafe { std::atomic_thread_fence(atomic_detail::native_order<Order>()); }
}
template <class T> using atomic_ptr = atomic<T *>;
} // namespace std2
