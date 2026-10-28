module;
#include <pthread.h>
export module safety_threads;
import safety;
export namespace std2 {
template <class R> struct thread_result_slot {
  R value{};
};
template <> struct thread_result_slot<void> {
  unsigned value{};
};
// Both APIs join before returning. No borrowed context escapes the call.
// The POSIX implementation below is the explicit audited unsafe boundary.
template <auto Target, class T>
auto joined_thread(__attribute__((annotate("safecpp.send"))) T value) {
  auto checked_target = Target;
  using Result = decltype(Target(static_cast<T &&>(value)));
  static_assert(__is_void(Result) || __is_integral(Result) ||
                    __is_floating_point(Result),
                "thread results must be scalar values");
  struct Work {
    T value;
    thread_result_slot<Result> result{};
    unsafe_fn explicit Work(T &&source) : value(static_cast<T &&>(source)) {}
    unsafe_fn ~Work() {}
    Work(const Work &) = delete;
    Work &operator=(const Work &) = delete;
  };
  struct Worker {
    static Result invoke(T value) { return Target(static_cast<T &&>(value)); }
    unsafe_fn static void *entry(void *raw) noexcept {
      auto *work = static_cast<Work *>(raw);
      if constexpr (__is_void(Result))
        invoke(static_cast<T &&>(work->value));
      else
        work->result.value = invoke(static_cast<T &&>(work->value));
      return nullptr;
    }
  };
  unsafe {
    auto *work = new Work{static_cast<T &&>(value)};
    pthread_t thread{};
    if (pthread_create(&thread, nullptr, &Worker::entry, work) != 0) {
      delete work;
      panic();
    }
    if (pthread_join(thread, nullptr) != 0)
      panic();
    if constexpr (__is_void(Result)) {
      delete work;
      return;
    } else {
      Result result = work->result.value;
      delete work;
      return result;
    }
  }
  panic();
}
template <auto Target, class T>
auto run_thread(__attribute__((annotate("safecpp.send.static"))) T value) {
  return joined_thread<Target>(static_cast<T &&>(value));
}
template <auto Target, class T>
auto scoped_thread(__attribute__((annotate("safecpp.send"))) T value) {
  return joined_thread<Target>(static_cast<T &&>(value));
}
template <auto Target, class T>
auto share_thread(__attribute__((annotate("safecpp.sync"))) const T &value) {
  auto checked_target = Target;
  using Result = decltype(Target(value));
  static_assert(__is_void(Result) || __is_integral(Result) ||
                    __is_floating_point(Result),
                "thread results must be scalar values");
  struct Work {
    const T *value;
    thread_result_slot<Result> result{};
  };
  struct Worker {
    static Result invoke(const T &value) { return Target(value); }
    unsafe_fn static void *entry(void *raw) noexcept {
      auto *work = static_cast<Work *>(raw);
      if constexpr (__is_void(Result))
        invoke(*work->value);
      else
        work->result.value = invoke(*work->value);
      return nullptr;
    }
  };
  unsafe {
    Work work{&value};
    pthread_t thread{};
    if (pthread_create(&thread, nullptr, &Worker::entry, &work) != 0)
      panic();
    if (pthread_join(thread, nullptr) != 0)
      panic();
    if constexpr (__is_void(Result))
      return;
    else
      return work.result.value;
  }
  panic();
}
template <scalar T>
class __attribute__((annotate("safecpp.unsafe.impl.send"),
                     annotate("safecpp.unsafe.impl.sync"))) mutex {
  struct State {
    pthread_mutex_t lock{};
    T value{};
  };
  State *state_ = nullptr;
  template <auto Target> static T invoke(T value) { return Target(value); }

public:
  explicit mutex(T value = T{}) {
    unsafe {
      state_ = new State{};
      if (pthread_mutex_init(&state_->lock, nullptr) != 0) {
        delete state_;
        panic();
      }
      state_->value = value;
    }
  }
  mutex(const mutex &) = delete;
  mutex &operator=(const mutex &) = delete;
  mutex(mutex &&other) noexcept {
    unsafe {
      state_ = other.state_;
      other.state_ = nullptr;
    }
  }
  ~mutex() {
    unsafe {
      if (state_ != nullptr) {
        if (pthread_mutex_destroy(&state_->lock) != 0)
          panic();
        delete state_;
      }
    }
  }
  T load() const {
    if (state_ == nullptr)
      panic();
    unsafe {
      if (pthread_mutex_lock(&state_->lock) != 0)
        panic();
      T result = state_->value;
      if (pthread_mutex_unlock(&state_->lock) != 0)
        panic();
      return result;
    }
    return T{};
  }
  void store(T value) const {
    if (state_ == nullptr)
      panic();
    unsafe {
      if (pthread_mutex_lock(&state_->lock) != 0)
        panic();
      state_->value = value;
      if (pthread_mutex_unlock(&state_->lock) != 0)
        panic();
    }
  }
  template <auto Target> T update() const {
    // Validate opaque callable objects as well as direct function targets.
    auto checked_callback = &invoke<Target>;
    if (state_ == nullptr)
      panic();
    unsafe {
      if (pthread_mutex_lock(&state_->lock) != 0)
        panic();
      try {
        state_->value = invoke<Target>(state_->value);
      } catch (...) {
        if (pthread_mutex_unlock(&state_->lock) != 0)
          panic();
        throw;
      }
      T result = state_->value;
      if (pthread_mutex_unlock(&state_->lock) != 0)
        panic();
      return result;
    }
    return T{};
  }
};
template <class Left, class Right> struct thread_results {
  Left first;
  Right second;
};
template <auto LeftTarget, auto RightTarget, class T>
auto parallel_share(__attribute__((annotate("safecpp.sync"))) const T &value) {
  using Left = decltype(LeftTarget(value));
  using Right = decltype(RightTarget(value));
  static_assert(__is_void(Left) || __is_integral(Left) || __is_floating_point(Left));
  static_assert(__is_void(Right) || __is_integral(Right) || __is_floating_point(Right));
  struct LeftWork {
    const T *value;
    thread_result_slot<Left> result{};
  };
  struct RightWork {
    const T *value;
    thread_result_slot<Right> result{};
  };
  struct Worker {
    static Left left(const T &value) { return LeftTarget(value); }
    static Right right(const T &value) { return RightTarget(value); }
    unsafe_fn static void *left_entry(void *raw) noexcept {
      auto *work = static_cast<LeftWork *>(raw);
      if constexpr (__is_void(Left))
        left(*work->value);
      else
        work->result.value = left(*work->value);
      return nullptr;
    }
    unsafe_fn static void *right_entry(void *raw) noexcept {
      auto *work = static_cast<RightWork *>(raw);
      if constexpr (__is_void(Right))
        right(*work->value);
      else
        work->result.value = right(*work->value);
      return nullptr;
    }
  };
  unsafe {
    LeftWork left{&value};
    RightWork right{&value};
    pthread_t a{}, b{};
    if (pthread_create(&a, nullptr, &Worker::left_entry, &left) != 0)
      panic();
    if (pthread_create(&b, nullptr, &Worker::right_entry, &right) != 0) {
      if (pthread_join(a, nullptr) != 0)
        panic();
      panic();
    }
    if (pthread_join(a, nullptr) != 0)
      panic();
    if (pthread_join(b, nullptr) != 0)
      panic();
    if constexpr (__is_void(Left) && __is_void(Right))
      return;
    else if constexpr (__is_void(Left))
      return right.result.value;
    else if constexpr (__is_void(Right))
      return left.result.value;
    else
      return thread_results<Left, Right>{left.result.value, right.result.value};
  }
  panic();
}

} // namespace std2
