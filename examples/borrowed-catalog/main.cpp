#feature on safety
#include <std2.h>

std2::vector<std2::string_view>/a row/(a)(std2::string_view/a title) safe {
  std2::vector<std2::string_view> result;
  result^.push_back(title);
  return rel result;
}

std2::string_view/a extract/(a)(std2::vector<std2::string_view>/a entries) safe {
  return std2::string_view(*entries[0]);
}

int main() safe {
  const char alpha[] = {'a', 'l', 'p', 'h', 'a'};
  const char beta[] = {'b', 'e', 't', 'a'};
  auto first = row(std2::string_view(alpha));
  auto title = extract(rel first);
  std2::println(title);
  auto second = row(std2::string_view(beta));
  std2::println(*second[0]);
  return 0;
}
