#pragma once
// Attribute payloads are serialized into Clang module files.
#define SAFETY_UNSAFE_FN __attribute__((annotate("safecpp.unsafe")))
// Only the then-statement grants unsafe permission. No runtime overhead.
#define SAFETY_UNSAFE if ([[clang::annotate("safecpp.unsafe.scope")]] bool safecpp_unsafe_scope = true)

#define SAFETY_RETURNS_BORROW(PARAMETER) __attribute__((annotate("safecpp.borrow.from:" #PARAMETER)))
#define SAFETY_RETURNS_THIS __attribute__((annotate("safecpp.borrow.this")))

// Checked parameter requirements at audited thread API boundaries.
#define SAFETY_SEND __attribute__((annotate("safecpp.send")))
#define SAFETY_SYNC __attribute__((annotate("safecpp.sync")))

#define SAFETY_SEND_TYPE __attribute__((annotate("safecpp.send")))
#define SAFETY_SYNC_TYPE __attribute__((annotate("safecpp.sync")))
// Explicit unsafe implementations assert audited ownership/synchronization.
#define SAFETY_UNSAFE_IMPL_SEND __attribute__((annotate("safecpp.unsafe.impl.send")))
#define SAFETY_UNSAFE_IMPL_SYNC __attribute__((annotate("safecpp.unsafe.impl.sync")))

#define SAFETY_STATIC_SEND __attribute__((annotate("safecpp.send.static")))

#define SAFETY_STORES_BORROW(PARAMETER) __attribute__((annotate("safecpp.stores.borrow:" #PARAMETER)))

#define SAFETY_RETURNS_STATIC __attribute__((annotate("safecpp.borrow.static")))

#define SAFETY_PINNED __attribute__((annotate("safecpp.pinned")))
#define SAFETY_STORES_SELF __attribute__((annotate("safecpp.stores.self")))

// Named universally checked borrow regions, erased into parameter provenance.
#define SAFETY_LIFETIME(NAME) __attribute__((annotate("safecpp.lifetime:" #NAME)))
#define SAFETY_RETURNS_LIFETIME(NAME) __attribute__((annotate("safecpp.borrow.lifetime:" #NAME)))
#define SAFETY_STORES_LIFETIME(NAME) __attribute__((annotate("safecpp.stores.lifetime:" #NAME)))
