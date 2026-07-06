"""lms-schema CLI — schema module composition and lifecycle management.

Subcommands (extensible):

    compose   — compose modules into a single schema + lock file
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .composer import compose, ComposerError


def _cmd_compose(args: argparse.Namespace) -> int:
    modules_dir = Path(args.modules_dir)
    if not modules_dir.is_dir():
        print(f"Error: --modules-dir '{modules_dir}' is not a directory", file=sys.stderr)
        return 1

    try:
        result = compose(modules_dir)
    except ComposerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write composed schema
    schema_path = out_dir / "composed.schema.json"
    schema_path.write_text(
        json.dumps(result.composed_schema, indent=2) + "\n"
    )

    # Write lock file
    lock: dict[str, dict[str, dict[str, str]]] = {"modules": {}}
    for info in result.modules:
        lock["modules"][info.name] = {
            "version": info.version,
            "checksum": info.checksum,
        }
    lock_path = out_dir / "modules.lock.json"
    lock_path.write_text(json.dumps(lock, indent=2) + "\n")

    print(f"Composed {len(result.modules)} modules → {schema_path}")
    print(f"Lock file written → {lock_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lms-schema",
        description="LMS Schema Module System CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # compose
    p_compose = sub.add_parser("compose", help="Compose modules into a single schema")
    p_compose.add_argument(
        "--modules-dir",
        default="schema/modules",
        help="Directory containing module sub-directories (default: schema/modules)",
    )
    p_compose.add_argument(
        "--out-dir",
        default="build",
        help="Output directory for composed schema and lock file (default: build)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "compose":
        sys.exit(_cmd_compose(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
