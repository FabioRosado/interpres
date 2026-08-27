"""Bootstrap the Jerome-Ezekiel project data.

This script helps users acquire the required corpus data for the
jerome-ezekiel project. It does NOT automatically download copyrighted
material; instead it guides the user through verified acquisition steps.
"""

from __future__ import annotations

from pathlib import Path


def check_directory(path: Path, name: str) -> bool:
    if path.exists() and any(path.iterdir()):
        print(f"[OK] {name}: {path}")
        return True
    print(f"[MISSING] {name}: {path}")
    return False


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    projects_dir = root / "projects" / "jerome-ezekiel"

    print("Interpres bootstrap: jerome-ezekiel project data")
    print("=" * 50)

    ok = True

    # 1. whitakers_words
    try:
        from whitakers_words.parser import Parser  # noqa: F401
        print("[OK] whitakers_words: installed")
    except ImportError:
        print("[MISSING] whitakers_words: install with:")
        print("    pip install -e dependencies/whitakers_words")
        print("    or: pip install 'whitakers-words @ git+https://github.com/blagae/whitakers_words.git'")
        ok = False

    # 2. Clementine Vulgate
    vulgate = data_dir / "clementine-vulgate" / "vul.tsv"
    if not check_directory(vulgate.parent, "Clementine Vulgate"):
        print("    Obtain from: https://github.com/theunpleasantowl/vul-complete")
        print("    Clone to: data/clementine-vulgate/")
        ok = False

    # 3. CPDV
    cpcdv = data_dir / "cpdv"
    if not check_directory(cpcdv, "CPDV"):
        print("    Obtain from: https://github.com/following-imperfectly/cpdv-json")
        print("    Place JSON files in: data/cpdv/")
        ok = False

    # 4. Optional research authorities
    for name, filename in [
        ("Chronology authority", "chronology.jsonl"),
        ("Proper name authority", "proper-names.jsonl"),
        ("Source edition authority", "source-editions.jsonl"),
    ]:
        path = data_dir / "research" / filename
        if not path.exists():
            print(f"[OPTIONAL] {name}: {path} (not present)")

    # 5. Source file
    source = projects_dir / "book1.txt"
    if not check_directory(source.parent, "Jerome source (book1.txt)"):
        print("    Download Book I from: https://mlat.uzh.ch/browser/cps_2.HieStr.CoInEz")
        print("    Save as: projects/jerome-ezekiel/book1.txt")
        ok = False

    print("=" * 50)
    if ok:
        print("All required data present. Run: interpres doctor")
        return 0
    print("Missing required data. See instructions above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
