#!/usr/bin/env python3
"""Reproduce PEP 696 TypeVar ordering violation in PyTorch on Python 3.12.

This script demonstrates the Python 3.12 typing error:
    "Type parameter ~_T1 without a default follows type parameter with a default"

The error occurs because PEP 696 (Python 3.12+) requires type parameters WITHOUT
defaults to come BEFORE parameters WITH defaults in Generic[]. PyTorch has several
violations of this rule.

Bug Locations in PyTorch (as of torch 2.5.x):
1. torch/fx/experimental/symbolic_shapes.py:2049
   - `class StatelessSymbolicContext(Generic[_P1, _T1], ...)`
   - _P1 is ParamSpec (has implicit default in typing_extensions)
   - _T1 is TypeVar (no default)

2. torch/_C/__init__.pyi:1119,1133
   - `class ScriptFunction(Generic[P, R])`
   - `class ScriptMethod(Generic[P, R])`
   - P is ParamSpec, R is TypeVar

3. torch/_inductor/utils.py:631
   - `class CachedMethod(Protocol, Generic[P, RV])`

4. torch/distributions/utils.py:144,175
   - `class lazy_property(Generic[T, R])`
   - `class _lazy_property_and_property(lazy_property[T, R], property)`
   - T is contravariant TypeVar, R is covariant TypeVar

The fix for each is to swap the order: Generic[_T1, _P1] instead of Generic[_P1, _T1]

Run: uv run python scripts/repro_pep696_pytorch.py
"""

import sys
from pathlib import Path


def check_python_version():
    """Verify we're on Python 3.12+ where PEP 696 is enforced."""
    print(f"Python version: {sys.version}")
    if sys.version_info < (3, 12):
        print("WARNING: This issue only manifests on Python 3.12+")
        print("You are running an older version where this would not be caught.")
        return False
    return True


def find_violations():
    """Find all PEP 696 violations in installed PyTorch."""
    import site

    site_packages = site.getsitepackages()[0]
    torch_path = Path(site_packages) / "torch"

    if not torch_path.exists():
        print(f"ERROR: PyTorch not found at {torch_path}")
        return []

    violations = []
    patterns = [
        # Pattern: Generic[ParamSpec, TypeVar] - wrong order
        ("Generic[_P1, _T1]", "Generic[_T1, _P1]"),
        ("Generic[P, R]", "Generic[R, P]"),
        ("Generic[P, RV]", "Generic[RV, P]"),
    ]

    files_to_check = [
        "fx/experimental/symbolic_shapes.py",
        "_C/__init__.pyi",
        "_inductor/utils.py",
    ]

    for rel_path in files_to_check:
        file_path = torch_path / rel_path
        if not file_path.exists():
            continue

        content = file_path.read_text()
        for bad_pattern, good_pattern in patterns:
            if bad_pattern in content:
                violations.append({
                    "file": str(file_path),
                    "pattern": bad_pattern,
                    "fix": good_pattern,
                    "patched": good_pattern in content,
                })

    return violations


def demonstrate_error():
    """Attempt to trigger the actual error by importing problematic module."""
    print("\n=== Attempting to trigger the error ===")

    try:
        # This import triggers the error on Python 3.12 if unpatched
        print("Importing torch.fx.experimental.symbolic_shapes...")
        from torch.fx.experimental import symbolic_shapes
        print("SUCCESS: Module imported without error (patched or compatible)")
        return True
    except TypeError as e:
        if "Type parameter" in str(e) and "default" in str(e):
            print(f"FAILED: {e}")
            print("\nThis is the PEP 696 violation we're demonstrating!")
            return False
        raise


def show_fix():
    """Show how to fix the violations."""
    print("\n=== Fix Instructions ===")
    print("""
To fix PEP 696 violations in PyTorch, edit the following files:

1. torch/fx/experimental/symbolic_shapes.py
   Line ~2049:
   - OLD: class StatelessSymbolicContext(Generic[_P1, _T1], SymbolicContext):
   + NEW: class StatelessSymbolicContext(Generic[_T1, _P1], SymbolicContext):

2. torch/_C/__init__.pyi
   Line ~1119:
   - OLD: class ScriptFunction(Generic[P, R]):
   + NEW: class ScriptFunction(Generic[R, P]):

   Line ~1133:
   - OLD: class ScriptMethod(Generic[P, R]):
   + NEW: class ScriptMethod(Generic[R, P]):

3. torch/_inductor/utils.py
   Line ~631:
   - OLD: class CachedMethod(Protocol, Generic[P, RV]):
   + NEW: class CachedMethod(Protocol, Generic[RV, P]):

Alternatively, set TORCHDYNAMO_DISABLE=1 to bypass the inductor entirely.
""")


def apply_patches():
    """Apply patches to fix PEP 696 violations."""
    import site

    site_packages = site.getsitepackages()[0]
    torch_path = Path(site_packages) / "torch"

    patches = [
        (
            torch_path / "fx/experimental/symbolic_shapes.py",
            "class StatelessSymbolicContext(Generic[_P1, _T1],",
            "class StatelessSymbolicContext(Generic[_T1, _P1],"
        ),
        (
            torch_path / "_C/__init__.pyi",
            "class ScriptFunction(Generic[P, R]):",
            "class ScriptFunction(Generic[R, P]):"
        ),
        (
            torch_path / "_C/__init__.pyi",
            "class ScriptMethod(Generic[P, R]):",
            "class ScriptMethod(Generic[R, P]):"
        ),
        (
            torch_path / "_inductor/utils.py",
            "class CachedMethod(Protocol, Generic[P, RV]):",
            "class CachedMethod(Protocol, Generic[RV, P]):"
        ),
        # Distribution utils: covariant R must come before contravariant T
        (
            torch_path / "distributions/utils.py",
            "class lazy_property(Generic[T, R]):",
            "class lazy_property(Generic[R, T]):"
        ),
        (
            torch_path / "distributions/utils.py",
            "_lazy_property_and_property[T, R]",
            "_lazy_property_and_property[R, T]"
        ),
        (
            torch_path / "distributions/utils.py",
            "class _lazy_property_and_property(lazy_property[T, R],",
            "class _lazy_property_and_property(lazy_property[R, T],"
        ),
    ]

    applied = []
    for file_path, old, new in patches:
        if not file_path.exists():
            continue

        content = file_path.read_text()
        if old in content:
            content = content.replace(old, new)
            file_path.write_text(content)
            applied.append(str(file_path))
            print(f"PATCHED: {file_path.name}")
        elif new in content:
            print(f"ALREADY PATCHED: {file_path.name}")
        else:
            print(f"NOT FOUND: {old[:50]}... in {file_path.name}")

    return applied


def main():
    """Main entry point."""
    print("=" * 70)
    print("PEP 696 TypeVar Ordering Violation Reproducer")
    print("=" * 70)

    is_312 = check_python_version()
    print()

    # Find violations
    print("=== Scanning for PEP 696 violations ===")
    violations = find_violations()

    if not violations:
        print("No known violations found (may already be patched)")
    else:
        for v in violations:
            status = "PATCHED" if v["patched"] else "UNPATCHED"
            print(f"[{status}] {Path(v['file']).name}: {v['pattern']} -> {v['fix']}")

    # Try to trigger the error
    if is_312:
        success = demonstrate_error()
        if not success:
            show_fix()

            print("\n=== Auto-patch option ===")
            print("Run with --patch to automatically apply fixes:")
            print("  uv run python scripts/repro_pep696_pytorch.py --patch")

    # Apply patches if requested
    if "--patch" in sys.argv:
        print("\n=== Applying patches ===")
        applied = apply_patches()
        if applied:
            print(f"\nPatched {len(applied)} file(s). Re-run to verify:")
            print("  uv run python scripts/repro_pep696_pytorch.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
