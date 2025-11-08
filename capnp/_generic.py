"""Runtime support for generated Python generic wrappers.

This module exposes a minimal registry that maps Python types to the
corresponding Cap'n Proto pointer types alongside the conversion functions
needed to bridge between them.  Generated wrappers for generic schema types
look up codecs through :func:`find_codec` so that user code can seamlessly
work with rich Python types (``uuid.UUID`` instances, integers that overflow
``int64`` when interpreted as unsigned, etc.) without having to manually
interact with the low level pointer-parameter constraints of Cap'n Proto.

The runtime is intentionally tiny – it keeps just enough state to resolve the
``Codec`` for a ``(schema_module, python_type)`` pair, with support for
walking the Python type's MRO to honour registrations on base classes.  This
behaviour mirrors the way ``isinstance`` performs dispatch which keeps the
runtime predictable and easy to reason about for library users.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Callable, Dict, Type

__all__ = [
    "Codec",
    "CodecRegistrationError",
    "CodecLookupError",
    "find_codec",
    "register_codec",
]


CodecEncoder = Callable[[Any], Any]
CodecDecoder = Callable[[Any], Any]


@dataclass(frozen=True)
class Codec:
    """A pair of conversion functions for a Cap'n Proto pointer parameter.

    Parameters
    ----------
    capnp_type:
        The Cap'n Proto pointer type that should be used when instantiating the
        generic schema.  Generated wrappers pass this value directly to the
        underlying ``capnp`` module when constructing the concrete schema type.
    to_capnp:
        A callable that receives a Python value and returns the object that
        should be written into the Cap'n Proto message.  For pointer types this
        is typically a builder returned by ``new_message`` or, for zero-copy
        scenarios, a value that can be assigned to the field directly.
    from_capnp:
        A callable that receives the reader object retrieved from the Cap'n
        Proto message and returns the corresponding Python value.
    """

    capnp_type: Any
    to_capnp: CodecEncoder
    from_capnp: CodecDecoder


class CodecRegistrationError(TypeError):
    """Raised when an invalid codec registration is attempted."""


class CodecLookupError(LookupError):
    """Raised when no codec could be found for the requested type."""


# The registry is keyed by the schema module and then by the Python type that
# the codec can serialise.  Using the module's ``__name__`` keeps lookups stable
# even when the same module object is imported under multiple aliases.
_registry: Dict[str, Dict[Type[Any], Codec]] = {}


def _module_key(schema_module: ModuleType | str) -> str:
    if isinstance(schema_module, ModuleType):
        return schema_module.__name__
    if isinstance(schema_module, str):
        return schema_module
    raise CodecRegistrationError(
        "schema_module must be a module or module name, got "
        f"{type(schema_module)!r}"
    )


def register_codec(schema_module: ModuleType | str, py_type: Type[Any], codec: Codec) -> None:
    """Register *codec* for ``py_type`` within ``schema_module``.

    Parameters
    ----------
    schema_module:
        The module that hosts the generated Cap'n Proto schema (e.g.
        ``my_schema.location_capnp``).  This can be the module object itself or
        its qualified name.
    py_type:
        The Python type that the codec handles.  The codec will be used for the
        exact type as well as subclasses by virtue of MRO based lookups.
    codec:
        The :class:`Codec` instance describing how to convert between Python
        values and the Cap'n Proto representation.
    """

    if not isinstance(py_type, type):
        raise CodecRegistrationError(
            "py_type must be a Python type, got " f"{type(py_type)!r}"
        )
    if not isinstance(codec, Codec):
        raise CodecRegistrationError(
            "codec must be an instance of Codec, got " f"{type(codec)!r}"
        )

    key = _module_key(schema_module)
    _registry.setdefault(key, {})[py_type] = codec


def find_codec(schema_module: ModuleType | str, py_type: Type[Any] | Any) -> Codec:
    """Return the codec registered for ``py_type`` within ``schema_module``.

    The lookup walks ``py_type``'s MRO so that codecs registered for a base
    class automatically apply to subclasses.  If no codec is registered a
    :class:`CodecLookupError` is raised with a helpful message that lists all
    known codecs for the schema module.
    """

    if not isinstance(py_type, type):
        py_type = type(py_type)

    key = _module_key(schema_module)
    module_registry = _registry.get(key)
    if not module_registry:
        raise CodecLookupError(
            f"No codecs registered for schema module '{key}', cannot encode type "
            f"{py_type.__module__}.{py_type.__qualname__}. "
            "Use register_codec() to provide conversions."
        )

    for cls in py_type.__mro__:
        codec = module_registry.get(cls)
        if codec is not None:
            return codec

    available = ", ".join(sorted(t.__name__ for t in module_registry)) or "<none>"
    raise CodecLookupError(
        f"No codec registered for type {py_type.__module__}.{py_type.__qualname__} "
        f"in schema module '{key}'. Available codecs: {available}"
    )


def _clear_registry() -> None:
    """Helper used by tests to reset the registry state."""

    _registry.clear()

