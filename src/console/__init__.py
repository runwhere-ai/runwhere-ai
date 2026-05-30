"""runwhere-ai business library (Service layer).

This package is the **single source of truth** for business rules consumed by
both gpuctl's existing `/api/v1/*` JSON routes (via Depends) and runwhere-ai's
new UI routes. See spec FR-117.

Contents:
    - auth        : AuthProvider abstraction + BearerTokenProvider (v1)
    - informer    : SharedInformer (K8s Watch + cache + wait_until for RYW)
    - pubsub      : TopicBus ((namespace, kind) fan-out)
    - consistency : ConsistencyGate (ETag / If-Match / 409→412 translation)
    - models      : User, Role, Subscription, InformerEvent, ConflictError
    - status_palette : K8s status → color + explanation
    - i18n        : zh-CN dictionary
    - forms       : WorkloadSpec + kind-specific Pydantic schemas
"""
