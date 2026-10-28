// Non-template, fixed-capacity range-add / range-sum segment tree.
// Half-open ranges [first,last). Unsigned arithmetic is modulo 2^64.
struct SegmentTree {
private:
  unsigned count=0u;
  unsigned long long sums[256]={};
  unsigned long long lazy[256]={};

public:
  SegmentTree() safe {}

  bool init(unsigned n) safe {
    if(n==0u || n>64u) return false;
    count=n;
    for(unsigned i=0u;i<256u;++i) {sums[i]=0ull;lazy[i]=0ull;}
    return true;
  }
private:
  void apply(unsigned node,unsigned width,unsigned long long delta) safe {
    sums[node]+=delta*width;
    lazy[node]+=delta;
  }
  void push(unsigned node,unsigned left,unsigned right) safe {
    if(lazy[node]==0ull || right-left<=1u) return;
    unsigned middle=left+(right-left)/2u;
    apply(node*2u,middle-left,lazy[node]);
    apply(node*2u+1u,right-middle,lazy[node]);
    lazy[node]=0ull;
  }
  void update(unsigned node,unsigned left,unsigned right,
              unsigned first,unsigned last,unsigned long long delta) safe {
    if(last<=left || right<=first) return;
    if(first<=left && right<=last) {apply(node,right-left,delta);return;}
    push(node,left,right);
    unsigned middle=left+(right-left)/2u;
    update(node*2u,left,middle,first,last,delta);
    update(node*2u+1u,middle,right,first,last,delta);
    sums[node]=sums[node*2u]+sums[node*2u+1u];
  }
  unsigned long long query(unsigned node,unsigned left,unsigned right,
                           unsigned first,unsigned last) safe {
    if(last<=left || right<=first) return 0ull;
    if(first<=left && right<=last) return sums[node];
    push(node,left,right);
    unsigned middle=left+(right-left)/2u;
    return query(node*2u,left,middle,first,last)+
           query(node*2u+1u,middle,right,first,last);
  }
public:
  bool add(unsigned first,unsigned last,unsigned long long delta) safe {
    if(count==0u || first>last || last>count) return false;
    if(first!=last) update(1u,0u,count,first,last,delta);
    return true;
  }
  bool sum(unsigned first,unsigned last,unsigned long long^ result) safe {
    if(count==0u || first>last || last>count) return false;
    *result=first==last?0ull:query(1u,0u,count,first,last);
    return true;
  }
};

int main() safe {
  SegmentTree tree;
  if(!tree.init(8u)) return 1;
  if(!tree.add(0u,8u,1ull) || !tree.add(2u,6u,3ull)) return 2;
  unsigned long long answer=0ull;
  if(!tree.sum(0u,8u,^answer) || answer!=20ull) return 3;
  if(!tree.sum(3u,5u,^answer) || answer!=8ull) return 4;
  if(tree.add(7u,9u,1ull) || tree.sum(4u,3u,^answer)) return 5;
  if(!tree.sum(4u,4u,^answer) || answer!=0ull) return 6;

  // Differential test against a plain array, including non-power-of-two sizes.
  unsigned random=17u;
  for(unsigned n=1u;n<=64u;++n) {
    if(!tree.init(n)) return 7;
    unsigned long long reference[64]={};
    for(unsigned step=0u;step<500u;++step) {
      random=random*1664525u+1013904223u;
      unsigned first=random%(n+1u);
      random=random*1664525u+1013904223u;
      unsigned last=random%(n+1u);
      if(first>last) {unsigned swap=first;first=last;last=swap;}
      random=random*1664525u+1013904223u;
      unsigned long long delta=random%1000u;
      if(!tree.add(first,last,delta)) return 8;
      for(unsigned i=first;i<last;++i) reference[i]+=delta;
      random=random*1664525u+1013904223u;
      first=random%(n+1u);
      random=random*1664525u+1013904223u;
      last=random%(n+1u);
      if(first>last) {unsigned swap=first;first=last;last=swap;}
      unsigned long long expected=0ull;
      for(unsigned i=first;i<last;++i) expected+=reference[i];
      if(!tree.sum(first,last,^answer) || answer!=expected) return 9;
    }
  }
  return 0;
}
