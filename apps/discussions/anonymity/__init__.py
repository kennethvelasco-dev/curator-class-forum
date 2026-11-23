"""Anonymous posting support for class discussions (Issue #36).

Anonymity is a display concern only. The real author of every Thread and
Reply stays in the database (Issue #31 contract); nothing in this package
removes or rewrites it.

Modules:
    labels           Pseudonym format and generation (pure functions).
    identity         ``PostIdentity`` and the Author-badge rule (pure).
    forms            ``AnonymityFormMixin`` adding the "Post Anonymously" choice.
    leak_assertions  Test helper that fails when real identity data leaks.
    models, service  Persisted thread-scoped aliases (need Issue #31 models).
"""
