// Checked primitives and owning containers. No pointers or references escape
// their public APIs. The unsafe implementation is the audited trust boundary.
export module safety;
export namespace std2 {
using size_type = decltype(sizeof(0));
[[noreturn]] inline void panic() noexcept {
  unsafe { __builtin_trap(); }
  for (;;) {
  }
}
template <auto Target> struct callable {
  template <class... Args> auto operator()(Args... args) const {
    return Target(args...);
  }
};
template <class T>
__attribute__((annotate("safecpp.borrow.from:value"))) T &&move(T &value) noexcept {
  return static_cast<T &&>(value);
}
template <class T>
concept integer = __is_integral(T) && !__is_same(__remove_cv(T), bool);
// Storage size includes padding for _BitInt. Query all value bits of the
// corresponding unsigned type instead of trusting sizeof/numeric_limits.
template <integer T> struct integer_traits {
  static consteval int width() {
    if constexpr (static_cast<T>(-1) > T{}) {
      unsafe { return __builtin_popcountg(static_cast<T>(-1)); }
    } else {
      using unsigned_type = __make_unsigned(T);
      unsafe { return __builtin_popcountg(static_cast<unsigned_type>(-1)); }
    }
    return 0;
  }
  static constexpr bool is_signed = static_cast<T>(-1) < T{};
  static consteval int value_bits() {
    unsafe { return width() - (static_cast<T>(-1) < T{}); }
    return 0;
  }
  static constexpr int digits = value_bits();
  static constexpr int max_exponent = 0;
  static constexpr int min_exponent = 0;
};
template <integer T> T checked_add(T a, T b) {
  unsafe {
    T result{};
    if (__builtin_add_overflow(a, b, &result))
      panic();
    return result;
  }
  return T{};
}
template <integer T> T checked_sub(T a, T b) {
  unsafe {
    T result{};
    if (__builtin_sub_overflow(a, b, &result))
      panic();
    return result;
  }
  return T{};
}
template <integer T> T checked_mul(T a, T b) {
  unsafe {
    T result{};
    if (__builtin_mul_overflow(a, b, &result))
      panic();
    return result;
  }
  return T{};
}
template <integer T> T checked_div(T a, T b) {
  if (b == T{})
    panic();
  unsafe {
    if constexpr (static_cast<T>(-1) < T{}) {
      if (b == static_cast<T>(-1)) {
        T neg{};
        if (__builtin_sub_overflow(T{}, a, &neg))
          panic();
      }
    }
    return a / b;
  }
  return T{};
}
template <integer T> T checked_rem(T a, T b) {
  if (b == T{})
    panic();
  unsafe {
    if constexpr (static_cast<T>(-1) < T{}) {
      if (b == static_cast<T>(-1)) {
        T neg{};
        if (__builtin_sub_overflow(T{}, a, &neg))
          panic();
      }
    }
    return a % b;
  }
  return T{};
}
template <integer T>
  requires(static_cast<T>(-1) > T{})
T checked_shl(T value, size_type count) {
  if (count >= static_cast<size_type>(integer_traits<T>::digits))
    panic();
  unsafe {
    T result = static_cast<T>(value << count);
    if (static_cast<T>(result >> count) != value)
      panic();
    return result;
  }
  return T{};
}
template <integer T>
  requires(static_cast<T>(-1) > T{})
T checked_shr(T value, size_type count) {
  if (count >= static_cast<size_type>(integer_traits<T>::digits))
    panic();
  unsafe { return static_cast<T>(value >> count); }
  return T{};
}
template <integer To, integer From> To checked_cast(From value) {
  unsafe {
    To result{};
    if (__builtin_add_overflow(value, To{}, &result))
      panic();
    return result;
  }
  return To{};
}
template <class T>
concept scalar = __is_arithmetic(T);
// A signature-branded dynamic callback. Construction accepts only a checked
// compile-time target; arbitrary raw function pointers cannot enter the type.
template <class Signature> class function;
template <scalar R, scalar... Args> class function<R(Args...)> {
  R (*target_)(Args...) = nullptr;
  template <auto Target> static R invoke(Args... args) { return Target(args...); }

public:
  function() = default;
  template <auto Target>
    requires(__is_convertible(decltype(Target), R (*)(Args...)) ||
             __is_convertible(decltype(Target), R (*)(Args...) noexcept))
  explicit function(callable<Target>) {
    auto checked_target = Target;
    unsafe { target_ = &invoke<Target>; }
  }
  R operator()(Args... args) const {
    if (target_ == nullptr)
      panic();
    unsafe { return target_(args...); }
    return R{};
  }
};
template <scalar T, size_type N>
  requires(N > 0u)
class array {
  T elements_[N] = {};

public:
  constexpr size_type size() const noexcept { return N; }
  T get(size_type index) const {
    if (index >= N)
      panic();
    unsafe { return elements_[index]; }
    return T{};
  }
  void set(size_type index, T value) {
    if (index >= N)
      panic();
    unsafe { elements_[index] = value; }
  }
  T operator[](size_type index) const { return get(index); }
};
template <scalar T>
class __attribute__((annotate("safecpp.unsafe.impl.send"),
                     annotate("safecpp.unsafe.impl.sync"))) vector {
  T *data_ = nullptr;
  size_type size_ = 0u;
  size_type capacity_ = 0u;

public:
  vector() = default;
  vector(const vector &) = delete;
  vector &operator=(const vector &) = delete;
  vector(vector &&other) noexcept {
    unsafe {
      data_ = other.data_;
      size_ = other.size_;
      capacity_ = other.capacity_;
      other.data_ = nullptr;
      other.size_ = 0u;
      other.capacity_ = 0u;
    }
  }
  __attribute__((annotate("safecpp.borrow.this"))) vector &
  operator=(vector &&other) noexcept {
    unsafe {
      if (this != &other) {
        delete[] data_;
        data_ = other.data_;
        size_ = other.size_;
        capacity_ = other.capacity_;
        other.data_ = nullptr;
        other.size_ = 0u;
        other.capacity_ = 0u;
      }
      return *this;
    }
    panic();
  }
  ~vector() {
    unsafe { delete[] data_; }
  }
  size_type size() const noexcept { return size_; }
  size_type capacity() const noexcept { return capacity_; }
  bool empty() const noexcept { return size_ == 0u; }
  void reserve(size_type capacity) {
    if (capacity <= capacity_)
      return;
    unsafe {
      T *fresh = new T[capacity]{};
      for (size_type i = 0u; i < size_; ++i)
        fresh[i] = data_[i];
      delete[] data_;
      data_ = fresh;
      capacity_ = capacity;
    }
  }
  void push_back(T value) {
    if (size_ == capacity_)
      reserve(capacity_ == 0u ? size_type{4u} : checked_mul(capacity_, size_type{2u}));
    unsafe { data_[size_] = value; }
    size_ = checked_add(size_, size_type{1u});
  }
  T get(size_type index) const {
    if (index >= size_)
      panic();
    unsafe { return data_[index]; }
    return T{};
  }
  void set(size_type index, T value) {
    if (index >= size_)
      panic();
    unsafe { data_[index] = value; }
  }
  T operator[](size_type index) const { return get(index); }
  T pop_back() {
    if (size_ == 0u)
      panic();
    size_ = checked_sub(size_, size_type{1u});
    unsafe { return data_[size_]; }
    return T{};
  }
  void clear() noexcept { size_ = 0u; }
};
} // namespace std2
