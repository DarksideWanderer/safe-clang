module;
#include <new>
export module safety_mutable_borrows;
import safety;
export namespace std2 {
// Own one exclusive region. Factories construct elements from that region;
// get() creates a checked reborrow of the container and its owner together.
template <class T, class Owner>
class __attribute__((annotate("safecpp.unsafe.moved.drop"),
                     annotate("safecpp.unsafe.exclusive.sequence")))
mutable_borrowed_vector {
  static_assert(__is_nothrow_destructible(T),
                "elements must have non-throwing destructors");
  static_assert(__is_nothrow_constructible(T, T &&),
                "elements must have non-throwing move constructors");
  static void validate_drop(T value) {}
  Owner &owner_;
  __attribute__((annotate("safecpp.unsafe.sequence.storage"))) T *values_ =
      nullptr;
  size_type count_ = 0u, capacity_ = 0u;
  template <auto Factory>
  __attribute__((annotate("safecpp.borrow.from:owner"))) static T create(Owner &owner) {
    return Factory(owner);
  }
  __attribute__((annotate("safecpp.borrow.from:value"))) static T validate_relocation(T value) {
    return T(std2::move(value));
  }
  __attribute__((annotate("safecpp.unsafe"))) static T relocate(T &value) {
    return T(std2::move(value));
  }

public:
  __attribute__((annotate(
      "safecpp.stores.borrow:owner"))) explicit mutable_borrowed_vector(Owner &owner)
      : owner_(owner) {
    auto checked_drop = &validate_drop;
  }
  __attribute__((annotate("safecpp.stores.borrow:other")))
  mutable_borrowed_vector(mutable_borrowed_vector &&other)
      : owner_(other.owner_) {
    unsafe {
      values_ = other.values_;
      count_ = other.count_;
      capacity_ = other.capacity_;
      other.values_ = nullptr;
      other.count_ = 0u;
      other.capacity_ = 0u;
    }
  }
  mutable_borrowed_vector(const mutable_borrowed_vector &) = delete;
  mutable_borrowed_vector &operator=(const mutable_borrowed_vector &) = delete;
  ~mutable_borrowed_vector() {
    auto checked_drop = &validate_drop;
    unsafe {
      for (size_type i = 0u; i < count_; ++i)
        values_[i].~T();
      ::operator delete(values_, std::align_val_t{alignof(T)});
    }
  }
  size_type size() const { return count_; }
  void reserve(size_type capacity) {
    auto checked_move = &validate_relocation;
    auto checked_drop = &validate_drop;
    if (capacity <= capacity_)
      return;
    auto bytes = checked_mul(capacity, sizeof(T));
    unsafe {
      auto *next =
          static_cast<T *>(::operator new(bytes, std::align_val_t{alignof(T)}));
      for (size_type i = 0u; i < count_; ++i)
        ::new (static_cast<void *>(next + i)) T(relocate(values_[i]));
      for (size_type i = 0u; i < count_; ++i)
        values_[i].~T();
      ::operator delete(values_, std::align_val_t{alignof(T)});
      values_ = next;
      capacity_ = capacity;
    }
  }
  template <auto Factory> void emplace() {
    auto checked_factory = &create<Factory>;
    auto checked_drop = &validate_drop;
    if (count_ == capacity_)
      reserve(checked_add(capacity_, size_type{8u}));
    unsafe {
      ::new (static_cast<void *>(values_ + count_)) T(create<Factory>(owner_));
      ++count_;
    }
  }
  __attribute__((annotate("safecpp.borrow.this"))) T &get(size_type index) {
    if (index >= count_)
      panic();
    unsafe { return values_[index]; }
    panic();
  }
};
} // namespace std2
