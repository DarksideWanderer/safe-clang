module;
#include <coroutine>
export module safety_coroutines;
import safety;
export namespace std2 {
struct __attribute__((annotate("safecpp.unsafe.coroutine.suspend"))) suspend {
  bool await_ready() const noexcept { return false; }
  void await_suspend(std::coroutine_handle<>) const noexcept {}
  void await_resume() const noexcept {}
};
// A frame is owned by one move-only handle. No borrowed input or this pointer
// may enter the frame; yielded values are scalar copies. There is deliberately
// no unsafe Send/Sync implementation for an arbitrary suspended frame.
template <scalar T> class generator {
public:
  struct __attribute__((annotate("safecpp.unsafe.coroutine.promise"))) promise_type {
    T current{};
    bool available = false;
    generator get_return_object() {
      unsafe {
        return generator(std::coroutine_handle<promise_type>::from_promise(*this));
      }
      panic();
    }
    suspend initial_suspend() const noexcept { return {}; }
    suspend final_suspend() const noexcept { return {}; }
    suspend yield_value(T value) noexcept {
      current = value;
      available = true;
      return {};
    }
    void return_void() noexcept { available = false; }
    void unhandled_exception() noexcept { panic(); }
  };

private:
  void *frame_ = nullptr;
  explicit generator(std::coroutine_handle<promise_type> frame) {
    unsafe { frame_ = frame.address(); }
  }

public:
  generator(const generator &) = delete;
  generator &operator=(const generator &) = delete;
  generator(generator &&other) noexcept {
    unsafe {
      frame_ = other.frame_;
      other.frame_ = nullptr;
    }
  }
  ~generator() {
    unsafe {
      if (frame_)
        std::coroutine_handle<promise_type>::from_address(frame_).destroy();
    }
  }
  bool next() {
    unsafe {
      if (!frame_)
        return false;
      auto frame = std::coroutine_handle<promise_type>::from_address(frame_);
      while (!frame.done()) {
        frame.promise().available = false;
        frame.resume();
        if (!frame.done() && frame.promise().available)
          return true;
      }
      return false;
    }
    panic();
  }
  T value() const {
    unsafe {
      if (!frame_)
        panic();
      auto frame = std::coroutine_handle<promise_type>::from_address(frame_);
      if (frame.done() || !frame.promise().available)
        panic();
      return frame.promise().current;
    }
    panic();
  }
};
} // namespace std2
