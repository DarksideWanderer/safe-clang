export module safety_regions;
export namespace std2 {
// Region tags describe admissible type substitutions. Actual storage lifetime
// is independently checked from every value's owner provenance by the CFG.
template <class Long, class Short>
concept outlives_region = __is_same(Long, Short) || __is_base_of(Long, Short);

template <class T, class Region> class shared_ref {
  template <class, class> friend class shared_ref;
  const T &value_;

public:
  __attribute__((annotate("safecpp.stores.borrow:owner"))) explicit shared_ref(
      const T &owner)
      : value_(owner) {}
  // Immutable target types and regions are covariant. Take the source view by
  // value so only its underlying owner, not its wrapper storage, is retained.
  template <class U, class Long>
    requires(outlives_region<Long, Region> && (__is_same(T, U) || __is_base_of(T, U)))
  __attribute__((annotate("safecpp.stores.borrow:other")))
  shared_ref(shared_ref<U, Long> other)
      : value_(other.value_) {}
  __attribute__((annotate("safecpp.borrow.this"))) const T &get() const {
    return value_;
  }
};

template <class T, class Region> class exclusive_ref {
  template <class, class> friend class exclusive_ref;
  T &value_;

public:
  __attribute__((annotate("safecpp.stores.borrow:owner"))) explicit exclusive_ref(
      T &owner)
      : value_(owner) {}
  exclusive_ref(const exclusive_ref &) = delete;
  exclusive_ref &operator=(const exclusive_ref &) = delete;
  __attribute__((annotate("safecpp.stores.borrow:other")))
  exclusive_ref(exclusive_ref &&other)
      : value_(other.value_) {}
  // The region is covariant; T is invariant for mutable access.
  template <class U, class Long>
    requires(outlives_region<Long, Region> && __is_same(T, U))
  __attribute__((annotate("safecpp.stores.borrow:other")))
  __attribute__((annotate("safecpp.transfers.borrow:other")))
  exclusive_ref(exclusive_ref<U, Long> &&other)
      : value_(other.value_) {}
  __attribute__((annotate("safecpp.borrow.this"))) const T &get() const {
    return value_;
  }
  __attribute__((annotate("safecpp.borrow.this"))) T &get_mut() { return value_; }
};

// A lifetime-indexed associated family. Provider::Item<Region> can be used by
// generic algorithms without erasing the type's region or owner obligations.
template <class T> struct borrow_family {
  template <class Region> using Item = shared_ref<T, Region>;
  template <class Region>
  __attribute__((annotate("safecpp.borrow.from:owner"))) static Item<Region>
  borrow(const T &owner) {
    return Item<Region>(owner);
  }
};
template <class Provider, class Region>
using lifetime_item = typename Provider::template Item<Region>;
} // namespace std2
