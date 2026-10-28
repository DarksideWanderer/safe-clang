import native_example;

int main() {
  unsigned value = 7u;
  return checked_sum() == 42u && audited_load(value) == 7u ? 0 : 1;
}
