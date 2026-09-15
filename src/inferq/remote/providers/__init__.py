"""Cloud provider backends.

Each module here implements the interfaces in :mod:`inferq.remote.base` on top
of one vendor's SDK. Nothing is imported eagerly: :mod:`inferq.remote.factory`
imports the selected provider on demand, so installing ``inferq[aws]`` without
``inferq[azure]`` (or the reverse) is a supported configuration.
"""

__all__: list[str] = []
