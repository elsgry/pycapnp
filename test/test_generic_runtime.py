import types

import pytest

import importlib.util
import pathlib
import sys

_PACKAGE_NAME = "capnp"
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GENERIC_PATH = _ROOT / "capnp" / "_generic.py"

package = sys.modules.setdefault(_PACKAGE_NAME, types.ModuleType(_PACKAGE_NAME))
package.__path__ = [str((_ROOT / "capnp").resolve())]

spec = importlib.util.spec_from_file_location(f"{_PACKAGE_NAME}._generic", _GENERIC_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules.setdefault(f"{_PACKAGE_NAME}._generic", module)
assert spec.loader is not None
spec.loader.exec_module(module)

Codec = module.Codec
CodecLookupError = module.CodecLookupError
CodecRegistrationError = module.CodecRegistrationError
_clear_registry = module._clear_registry
find_codec = module.find_codec
register_codec = module.register_codec


class _Base:
    pass


class _Child(_Base):
    pass


def setup_function(function):
    _clear_registry()


def teardown_function(function):
    _clear_registry()


def _dummy_codec(tag):
    return Codec(capnp_type=tag, to_capnp=lambda value: (tag, value), from_capnp=lambda reader: reader.value)


def test_register_and_find_codec_exact_type():
    module = types.ModuleType("example_capnp")
    codec = _dummy_codec("id")

    register_codec(module, _Base, codec)

    resolved = find_codec(module, _Base)
    assert resolved is codec


def test_find_codec_accepts_instances():
    module = types.ModuleType("example_capnp")
    codec = _dummy_codec("id")

    register_codec(module, _Base, codec)

    instance = _Base()
    assert find_codec(module, instance) is codec


def test_mro_lookup_uses_base_class_registration():
    module = types.ModuleType("example_capnp")
    codec = _dummy_codec("base")

    register_codec(module, _Base, codec)

    resolved = find_codec(module, _Child)
    assert resolved is codec


def test_register_codec_validates_inputs():
    module = types.ModuleType("example_capnp")
    codec = _dummy_codec("base")

    with pytest.raises(CodecRegistrationError):
        register_codec(object(), _Base, codec)

    with pytest.raises(CodecRegistrationError):
        register_codec(module, 123, codec)  # type: ignore[arg-type]

    with pytest.raises(CodecRegistrationError):
        register_codec(module, _Base, object())  # type: ignore[arg-type]


def test_find_codec_raises_helpful_error_when_missing():
    module = types.ModuleType("example_capnp")

    with pytest.raises(CodecLookupError) as excinfo:
        find_codec(module, _Base)

    message = str(excinfo.value)
    assert "example_capnp" in message
    assert "_Base" in message


def test_find_codec_lists_available_types():
    module = types.ModuleType("example_capnp")
    register_codec(module, _Base, _dummy_codec("base"))

    class _Unrelated:  # local type to force failure branch
        pass

    with pytest.raises(CodecLookupError) as excinfo:
        find_codec(module, _Unrelated)

    assert "_Base" in str(excinfo.value)

