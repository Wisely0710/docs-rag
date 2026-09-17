# Clients

Two shell clients ship with the service: one pushes a documentation tree into a corpus
mirror and re-indexes it, the other runs a read-only query over ssh. Both derive the
scope from the service configuration at run time, and the sync client refuses any
target that is not exactly this corpus's mirror directory.
