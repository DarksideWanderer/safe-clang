export module native_example;
import safety;
unsafe_fn unsigned load(unsigned* p) { return *p; }
export unsigned checked_sum() {
  std2::vector<unsigned> values;
  values.push_back(12u);
  values.push_back(30u);
  return std2::checked_add(values.get(0u), values.get(1u));
}
export unsigned audited_load(unsigned& value) {
  unsafe { return load(&value); }
}
