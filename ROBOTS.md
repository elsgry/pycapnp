# ROBOTS.md — Python Generics for Cap’n Proto (pycapnp enhancement)

## 1) Mission

Implement **first-class Python generics for Cap’n Proto schema generics** in `pycapnp` via a new codegen path and a tiny runtime. Developers should be able to use:

```py
from my_schema.location_generic import Location
loc = Location[str]("NYC", 40.71, -74.0)
loc2 = Location[int](2**63, 51.5, -0.12)
```

…with accurate type hints, minimal overhead, and **no schema changes**.

## 2) Goals (Must)

* Generate **`typing.Generic[...]` classes** for Cap’n Proto generic structs/interfaces.
* Hide the **pointer-parameter constraint** behind a **codec registry** (auto wrap/unbox scalars and custom types).
* Ship **PEP 561 stubs** so mypy/pyright infer `Location[T].id: T`.
* Preserve wire compatibility and the existing raw API.
* Keep overhead negligible vs current `pycapnp` (<2% in simple construct+serialize microbenchmarks).

## 3) Non-goals (Won’t for v1)

* No HKTs (higher-kinded types).
* No cross-module generic unification beyond explicit codec registration.
* No changes to Cap’n Proto core or schema language.

## 4) Outputs / Deliverables

1. **Runtime module**: `capnp/_generic.py` (Codec, registry, helpers).
2. **Codegen templates** (Jinja or Python format strings):

   * `*_generic.py` wrapper per generic type.
   * `*_generic.pyi` stubs per generic type.
   * `*_codecs.py` per schema module (default codec registrations when wrappers exist).
3. **Compiler flag**: `--python-generics={off|stubs|full}`; default `off`.
4. **Docs**: new “Python generics” page + migration notes.
5. **Tests**: unit, typing, and microbenchmarks.

## 5) High-level Design

### 5.1 Runtime (`capnp/_generic.py`)

* `Codec(capnp_type, to_capnp, from_capnp)`.
* `_registry[(schema_module, py_type)] -> Codec` with MRO fallback.
* API: `register_codec(schema_module, py_type, codec)` and `find_codec(schema_module, py_type)`.

### 5.2 Generated Wrapper (per generic type)

Given schema `Foo(P1, P2, ...)`, emit `foo_generic.py` exposing:

```py
P1 = TypeVar("P1"); P2 = TypeVar("P2")
class Foo(Generic[P1, P2]):
    def __init__(self, a1: P1, a2: P2, ...):
        codec1 = find_codec(_mod, type(a1))
        codec2 = find_codec(_mod, type(a2))
        impl = _mod.Foo[codec1.capnp_type, codec2.capnp_type]
        # construct message, set fields via codecs
```

* `from_bytes(cls, data: bytes, py_types: tuple[type,...] | Type[P1]...)` loads the **concrete** instantiation and returns a typed wrapper.
* Properties unwrap via `from_capnp`.

### 5.3 Type Stubs (PEP 561)

* Emit `.pyi` alongside wrappers with `Generic[...]` and precise field types.
* Provide overloads for common `T` (str/int/bytes/uuid.UUID) to improve inference.

### 5.4 Default Codecs

Emit module-level registrations in `*_codecs.py` (imported by `*_generic.py`):

| Python type | Cap’n pointer type    | Wrapper required | to_capnp            | from_capnp            |
| ----------- | --------------------- | ---------------- | ------------------- | --------------------- |
| `str`       | `Text`                | No               | identity            | `str(r)`              |
| `bytes`     | `Data` via `BytesRef` | Yes              | new wrapper message | `bytes(r.value)`      |
| `int`       | `Number64`            | Yes              | mask → wrapper      | `int(r.value)`        |
| `uuid.UUID` | `Uuid128`             | Yes              | split → wrapper     | merge → `UUID(int=…)` |

> Emit only when the schema module defines the necessary wrapper structs.

## 6) Codegen Integration

* Extend the Python backend of `capnp compile -opython` to:

  1. Parse the AST: detect generic types and their parameters.
  2. Emit raw module as today (e.g., `location_capnp.py`).
  3. If `--python-generics=stubs|full`, render `*_generic.(py|pyi)`.
  4. If `--python-generics=full`, render `*_codecs.py` and autoload it from the wrapper.
* Naming: place wrappers next to raw module; suffix `_generic` to avoid import cycles.

## 7) Backward Compatibility

* No behavioral change when flag is `off` (default).
* Existing imports continue to work (`import location_capnp as capnp`).
* New API is additive: `from my_schema.location_generic import Location`.

## 8) CLI Flags & Behavior

* `--python-generics=off|stubs|full`.
* `--python-generics-scalar=wrap|error` (controls default codec emission for scalars).
* Future: `--python-generics-anypointer` to generate `AnyPointer`-based dynamic wrappers (out-of-scope for v1).

## 9) Testing Plan

### 9.1 Unit

* Round-trip for `str`, big `int (>= 2**63)`, `bytes`, `uuid.UUID`.
* Multi-parameter generic: `Pair(A,B)`.
* Missing codec → `TypeError` with helpful message.
* Wrapper-free path (Text/Data) remains zero-copy.

### 9.2 Typing

* `mypy` + `pyright` tests: `reveal_type(Location[str](...).id) -> builtins.str` etc.
* Overload resolution for `from_bytes(blob, str)`.

### 9.3 Benchmarks (pytest-benchmark)

* Construct + set + `to_bytes_packed` for raw vs generic wrapper.
* Target: ≤2% overhead median.

## 10) Repository Layout Changes

```
pycapnp/
  _generic.py          # NEW runtime
  codegen/
    templates/
      generic_wrapper.py.j2
      generic_wrapper.pyi.j2
      module_codecs.py.j2
  ... existing files ...
```

## 11) Acceptance Criteria

* ✅ Flagged build emits wrappers/stubs for generic schemas.
* ✅ `pip install` publishes `py.typed` and stubs.
* ✅ Typing tests pass on CPython 3.10–3.13.
* ✅ Benchmarks meet perf budget.
* ✅ Docs page with end-to-end example and codec recipe.

## 12) Rollout Plan

1. Land runtime + codegen behind `--python-generics=stubs`.
2. Add default codecs + `full` mode.
3. Publish pre-release (`0.x`) to gather feedback.
4. Stabilize and document integration patterns (dataclasses/Pydantic codecs).

## 13) Risks & Mitigations

* **Codec explosion**: encourage per-module codecs; document conventions.
* **Unsigned semantics**: recommend `bigint` for JS/TS consumers; in Python, `int` is unbounded.
* **User surprise on Any**: be explicit that *this is not AnyPointer*; codecs maintain type safety.

## 14) Developer Guide (How to)

1. Build local: `pip install -e .` (dev) and ensure `capnp` compiler on PATH.
2. Compile schema: `capnp compile -opython --python-generics=full schema/location.capnp`.
3. Use in app:

   ```py
   from my_schema.location_generic import Location
   a = Location[str]("NYC", 40.71, -74.0)
   b = Location[int](2**63, 51.5, -0.12)
   ```
4. Register custom type:

   ```py
   from my_schema._codecs import register_codec, Codec
   from my_schema import location_capnp as mod
   class OrderId: ...
   register_codec(mod, OrderId, Codec(mod.Number64,
                                     lambda o: mod.Number64.new_message(value=o.n),
                                     lambda r: OrderId(int(r.value))))
   ```

## 15) Example Schema for CI tests

```capnp
@0x1a2b3c4d1a2b3c4d;
struct Location(Id) { id @0 :Id; lat @1 :Float64; lon @2 :Float64; }
struct Number64 { value @0 :UInt64; }
struct BytesRef { value @0 :Data; }
struct Uuid128 { hi @0 :UInt64; lo @1 :UInt64; }
struct Pair(A, B) { a @0 :A; b @1 :B; }
```

## 16) CI Matrix

* OS: ubuntu-latest, macos-latest, windows-latest.
* Py: 3.10, 3.11, 3.12, 3.13.
* Steps: build, `capnp compile` samples, unit + typing tests, benchmark smoke.

## 17) Documentation TODO

* New page: *Python Generics in pycapnp* with quickstart, codec cookbook, and pitfalls.
* Update README: reference `--python-generics`.

## 18) Out of Scope / Future Work

* Auto-derivation of codecs from dataclasses/attrs/pydantic via reflection.
* `AnyPointer` dynamic generic wrapper (type-tagged).
* IDE plugin to generate wrapper codecs from schema automatically.

## 19) Owner & Contact

* Tech Lead: **Ellis Breen** (proposer)
* Maintainers to ping: `pycapnp` maintainers; Cap’n Proto community for review.

---

**End of ROBOTS.md**
