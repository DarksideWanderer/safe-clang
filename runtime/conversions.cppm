module;
#include <limits>
export module safety_conversions;
import safety;

export namespace std2 {
template <class T>
concept conversion_number =
    integer<T> || __is_same(T, float) ||
    __is_same(T, double) || __is_same(T, long double);

template <conversion_number T> struct number_limits : std::numeric_limits<T> {};
template <integer T> struct number_limits<T> : integer_traits<T> {};

// A type-level guarantee: every source value is preserved exactly.
template <class To, class From>
concept lossless_conversion =
    conversion_number<To> && conversion_number<From> &&
    ((__is_integral(To) && __is_integral(From) &&
      (!number_limits<From>::is_signed || number_limits<To>::is_signed) &&
      number_limits<To>::digits >= number_limits<From>::digits) ||
     (!__is_integral(To) && __is_integral(From) &&
      number_limits<To>::digits >= number_limits<From>::digits &&
      number_limits<To>::max_exponent > number_limits<From>::digits) ||
     (!__is_integral(To) && !__is_integral(From) &&
      number_limits<To>::digits >= number_limits<From>::digits &&
      number_limits<To>::max_exponent >=
          number_limits<From>::max_exponent &&
      number_limits<To>::min_exponent <=
          number_limits<From>::min_exponent));

template <conversion_number T> struct conversion_result {
  bool ok = false;
  T value = T{}; // Failure never leaves an uninitialized payload.
};

template <conversion_number To, conversion_number From>
  requires lossless_conversion<To, From>
To into(From value) noexcept {
  unsafe { return static_cast<To>(value); }
  return To{};
}

// Success means exact finite-value preservation, including range and
// fractional checks. Identity/widening also preserve infinities and NaNs.
template <conversion_number To, conversion_number From>
conversion_result<To> try_into(From value) noexcept {
  if constexpr (lossless_conversion<To, From>) {
    return {true, into<To>(value)};
  } else {
    unsafe {
      if constexpr (__is_integral(To) && __is_integral(From)) {
        To result{};
        if (__builtin_add_overflow(value, To{}, &result))
          return {};
        return {true, result};
      } else if constexpr (__is_integral(To)) {
        // Power-of-two exclusive upper bounds avoid rounding INT_MAX upward
        // when long double has only double precision (notably macOS arm64).
        long double x = static_cast<long double>(value);
        long double upper = __builtin_ldexpl(1.0L, number_limits<To>::digits);
        long double lower = number_limits<To>::is_signed ? -upper : 0.0L;
        if (!(x >= lower && x < upper) || __builtin_truncl(x) != x)
          return {};
        return {true, static_cast<To>(x)};
      } else if constexpr (__is_integral(From)) {
        // Compare in the integer domain when the floating range is smaller.
        // Rounding a wide integer to long double before comparing could hide
        // an integer just above the largest representable float.
        if constexpr (number_limits<To>::max_exponent <=
                      number_limits<From>::digits) {
          From upper = static_cast<From>(number_limits<To>::max());
          if (value > upper)
            return {};
          if constexpr (number_limits<From>::is_signed)
            if (value < -upper)
              return {};
        }
        To result = static_cast<To>(value);
        auto back = try_into<From>(result);
        if (!back.ok || back.value != value)
          return {};
        return {true, result};
      } else {
        long double x = static_cast<long double>(value);
        long double limit = static_cast<long double>(number_limits<To>::max());
        if (!(x >= -limit && x <= limit))
          return {};
        To result = static_cast<To>(value);
        if (static_cast<From>(result) != value)
          return {};
        return {true, result};
      }
    }
  }
  return {};
}

template <conversion_number To, conversion_number From> To checked_into(From value) {
  auto result = try_into<To>(value);
  if (!result.ok)
    panic();
  return result.value;
}
} // namespace std2
