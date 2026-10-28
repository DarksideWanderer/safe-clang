export module safety_ownership;
import safety;
export namespace std2 {
// A scoped pinning borrow. Address-sensitive types must declare SAFETY_PINNED,
// so ending this borrow cannot re-enable moves of an address-sensitive value.
template <class T> class pin_ref {
  T &value_;

public:
  __attribute__((annotate("safecpp.stores.borrow:value"))) explicit pin_ref(T &value)
      : value_(value) {}
  pin_ref(const pin_ref &)
    requires(__is_const(T))
  = default;
  pin_ref(const pin_ref &) = delete;
  pin_ref &operator=(const pin_ref &) = delete;
  __attribute__((annotate("safecpp.stores.borrow:other"))) pin_ref(pin_ref &&other)
      : value_(other.value_) {}
  __attribute__((annotate("safecpp.borrow.this"))) const T &get() const {
    return value_;
  }
  __attribute__((annotate("safecpp.borrow.this"))) T &get_mut() { return value_; }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project() const {
    return Projection(get());
  }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project_mut() {
    return Projection(get_mut());
  }
};
// The pointee never moves; moving this handle transfers its allocation.
// Checked construction prevents external borrows escaping into an unbound heap.
template <class T>
class __attribute__((annotate("safecpp.unsafe.pinned.owner"))) pin_box {
  static void validate_drop(T value) {}
  T *value_ = nullptr;
  unsafe_fn explicit pin_box(T *value) : value_(value) {}
  static T move_out(T value) { return T(std2::move(value)); }
  template <class... Args>
  __attribute__((annotate("safecpp.validate.owned.construction"))) static void
  validate(Args... args) {
    T object(static_cast<Args &&>(args)...);
  }

  template <class... Args>
  __attribute__((annotate("safecpp.validate.owned.arguments"))) static void
  validate_reset(Args... args) {
    validate(static_cast<Args &&>(args)...);
  }

public:
  pin_box(const pin_box &) = delete;
  pin_box &operator=(const pin_box &) = delete;
  pin_box(pin_box &&other) noexcept {
    unsafe {
      value_ = other.value_;
      other.value_ = nullptr;
    }
  }
  ~pin_box() {
    auto checked_drop = &validate_drop;
    static_assert(__is_nothrow_destructible(T),
                  "pin_box requires a non-throwing destructor");
    unsafe { ::delete value_; }
  }
  template <class... Args> static pin_box make(Args... args) {
    static_assert(__is_nothrow_destructible(T),
                  "pin_box requires a non-throwing destructor");
    // Taking the specialization's address instantiates its safe body and
    // checks the constructor and destructor, without running a second copy.
    auto checked_constructor = &validate<Args...>;
    unsafe { return pin_box(::new T(static_cast<Args &&>(args)...)); }
    panic();
  }
  template <class... Args> void reset(Args... args) {
    static_assert(__is_nothrow_destructible(T),
                  "reset requires a non-throwing destructor");
    auto checked_constructor = &validate_reset<Args...>;
    // Construct first for exception safety, then drop the old pinned object
    // before releasing its storage. Existing borrows forbid this call.
    unsafe {
      T *replacement = ::new T(static_cast<Args &&>(args)...);
      ::delete value_;
      value_ = replacement;
    }
  }
  // An address-sensitive T has no safe move constructor, so the validator
  // rejects take() for pinned types. Borrow-carrying results lack an escape
  // contract and are also rejected before the unsafe storage operation.
  T take() {
    static_assert(__is_nothrow_constructible(T, T &&),
                  "take requires a non-throwing move");
    auto checked_move = &move_out;
    if (value_ == nullptr)
      panic();
    unsafe {
      T result(static_cast<T &&>(*value_));
      ::delete value_;
      value_ = nullptr;
      return result;
    }
    panic();
  }
  __attribute__((annotate("safecpp.borrow.this"))) pin_ref<const T> as_ref() const {
    return pin_ref<const T>(get());
  }
  __attribute__((annotate("safecpp.borrow.this"))) pin_ref<T> as_mut() {
    return pin_ref<T>(get_mut());
  }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project() const {
    return Projection(get());
  }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project_mut() {
    return Projection(get_mut());
  }
  __attribute__((annotate("safecpp.borrow.this"))) const T &get() const {
    if (value_ == nullptr)
      panic();
    unsafe { return *value_; }
    panic();
  }
  __attribute__((annotate("safecpp.borrow.this"))) T &get_mut() {
    if (value_ == nullptr)
      panic();
    unsafe { return *value_; }
    panic();
  }
};
// The explicit owner region remains exclusively borrowed until destruction.
// A moving handle transfers the allocation and retains that same region.
template <class T, class Owner>
class __attribute__((annotate("safecpp.unsafe.pinned.region"),
                     annotate("safecpp.unsafe.moved.drop"))) pin_region {
  static_assert(__is_nothrow_destructible(T),
                "pin_region requires a non-throwing destructor");
  Owner &owner_;
  static void validate_drop(T value) {}
  T *value_ = nullptr;
  template <class... Args>
  __attribute__((annotate("safecpp.validate.regional.construction"))) static void
  validate(Owner &owner, Args... args) {
    T object(owner, static_cast<Args &&>(args)...);
  }

public:
  template <class... Args>
  __attribute__((annotate("safecpp.stores.borrow:owner"))) explicit pin_region(
      Owner &owner, Args... args)
      : owner_(owner) {
    auto checked_constructor = &validate<Args...>;
    unsafe { value_ = ::new T(owner, static_cast<Args &&>(args)...); }
  }
  pin_region(const pin_region &) = delete;
  pin_region &operator=(const pin_region &) = delete;
  __attribute__((annotate("safecpp.stores.borrow:other")))
  pin_region(pin_region &&other) noexcept
      : owner_(other.owner_) {
    unsafe {
      value_ = other.value_;
      other.value_ = nullptr;
    }
  }
  ~pin_region() {
    auto checked_drop = &validate_drop;
    unsafe { ::delete value_; }
  }
  __attribute__((annotate("safecpp.borrow.this"))) pin_ref<const T> as_ref() const {
    return pin_ref<const T>(get());
  }
  __attribute__((annotate("safecpp.borrow.this"))) pin_ref<T> as_mut() {
    return pin_ref<T>(get_mut());
  }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project() const {
    return Projection(get());
  }
  template <auto Projection>
  __attribute__((annotate("safecpp.borrow.this"))) decltype(auto) project_mut() {
    return Projection(get_mut());
  }
  __attribute__((annotate("safecpp.borrow.this"))) const T &get() const {
    if (value_ == nullptr)
      panic();
    unsafe { return *value_; }
    panic();
  }
  __attribute__((annotate("safecpp.borrow.this"))) T &get_mut() {
    if (value_ == nullptr)
      panic();
    unsafe { return *value_; }
    panic();
  }
};
} // namespace std2
