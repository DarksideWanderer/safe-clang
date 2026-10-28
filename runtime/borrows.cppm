module;
#include <new>
export module safety_borrows;
import safety;
export namespace std2 {
// Explicit owner region. Readonly borrowed elements must originate in this
// region; the compiler checks each push. Heap manipulation is audited unsafe.
template <class T, class Owner>
class __attribute__((
    annotate("safecpp.unsafe.moved.drop"), annotate("safecpp.unsafe.borrowed.sequence"),
    annotate("safecpp.unsafe.impl.send"), annotate("safecpp.unsafe.impl.sync")))
borrowed_vector {
  static_assert(__is_nothrow_destructible(T),
                "borrowed_vector requires a non-throwing element destructor");
  // Instantiating this safe body checks parameter destruction, even though
  // actual heap destruction happens in the audited storage implementation.
  static void validate_drop(T value) {}
  const Owner &owner_;
  __attribute__((annotate("safecpp.unsafe.sequence.storage"))) T *values_ =
      nullptr;
  size_type count_ = 0u, capacity_ = 0u;
  __attribute__((annotate("safecpp.borrow.from:value"))) static T
  clone(__attribute__((annotate("safecpp.sync"))) const T &value) {
    return T(value);
  }

public:
  __attribute__((annotate("safecpp.stores.borrow:owner"))) explicit borrowed_vector(
      const Owner &owner)
      : owner_(owner) {
    auto checked_drop = &validate_drop;
  }
  __attribute__((annotate("safecpp.stores.borrow:other")))
  borrowed_vector(borrowed_vector &&other)
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
  borrowed_vector(const borrowed_vector &) = delete;
  borrowed_vector &operator=(const borrowed_vector &) = delete;
  ~borrowed_vector() {
    auto checked_drop = &validate_drop;
    unsafe {
      for (size_type i = 0u; i < count_; ++i)
        values_[i].~T();
      ::operator delete(values_, std::align_val_t{alignof(T)});
    }
  }
  size_type size() const { return count_; }
  __attribute__((annotate("safecpp.unsafe.mutates.storage"))) void
  reserve(size_type capacity) {
    auto checked_clone = &clone;
    auto checked_drop = &validate_drop;
    if (capacity <= capacity_)
      return;
    auto bytes = checked_mul(capacity, sizeof(T));
    unsafe {
      auto *next =
          static_cast<T *>(::operator new(bytes, std::align_val_t{alignof(T)}));
      size_type initialized = 0u;
      try {
        for (; initialized < count_; ++initialized)
          ::new (static_cast<void *>(next + initialized))
              T(clone(values_[initialized]));
      } catch (...) {
        for (size_type i = 0u; i < initialized; ++i)
          next[i].~T();
        ::operator delete(next, std::align_val_t{alignof(T)});
        throw;
      }
      for (size_type i = 0u; i < count_; ++i)
        values_[i].~T();
      ::operator delete(values_, std::align_val_t{alignof(T)});
      values_ = next;
      capacity_ = capacity;
    }
  }
  __attribute__((annotate("safecpp.unsafe.mutates.storage"),
                 annotate("safecpp.unsafe.adopts.borrow:value"))) void
  push_back(__attribute__((annotate("safecpp.sync"))) const T &value) {
    auto checked_clone = &clone;
    auto checked_drop = &validate_drop;
    if (count_ == capacity_)
      reserve(checked_add(capacity_, size_type{8u}));
    unsafe {
      ::new (static_cast<void *>(values_ + count_)) T(clone(value));
      ++count_;
    }
  }
  __attribute__((annotate("safecpp.borrow.this"))) T get(size_type index) const {
    auto checked_clone = &clone;
    auto checked_drop = &validate_drop;
    if (index >= count_)
      panic();
    unsafe { return clone(values_[index]); }
    panic();
  }
};
} // namespace std2
