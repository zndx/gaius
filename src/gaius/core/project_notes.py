"""Project note creation with bidirectional linking.

Creates Zettelkasten-style project notes with prev/next links
that maintain a chain of related notes across sessions.
"""

from datetime import datetime
from pathlib import Path
import re
from typing import Optional


def find_previous_project_note(kb_root: Path, project_type: str) -> Optional[Path]:
    """Find most recent note of this project type.

    Searches scratch directories in reverse chronological order
    for notes matching the pattern *_{project_type}.md

    Args:
        kb_root: Root path of the knowledge base
        project_type: Type of project note (e.g., 'charter', 'standup')

    Returns:
        Path to most recent matching note, or None if none found
    """
    pattern = re.compile(rf"\d{{6}}_{re.escape(project_type)}\.md$")
    scratch_dir = kb_root / "scratch"

    if not scratch_dir.exists():
        return None

    candidates = []
    # Sort date directories in reverse order (most recent first)
    date_dirs = sorted(
        [d for d in scratch_dir.iterdir() if d.is_dir()],
        reverse=True,
    )

    for date_dir in date_dirs:
        # Within each date, find matching notes sorted by time (reverse)
        notes = sorted(
            [n for n in date_dir.iterdir() if pattern.match(n.name)],
            reverse=True,
        )
        candidates.extend(notes)

    return candidates[0] if candidates else None


def create_project_note(
    kb_root: Path,
    project_type: str,
    title: Optional[str] = None,
) -> tuple[Path, str]:
    """Create new project note with bidirectional linking.

    Creates a new Zettelkasten note in today's scratch directory with:
    - Link to the project agenda: [[current/projects/{type}/agenda]]
    - prev: link to most recent note of same type
    - next: initially empty (will be filled by subsequent notes)

    Also updates the previous note's next: field to point to this note.

    Args:
        kb_root: Root path of the knowledge base
        project_type: Type of project note (e.g., 'charter', 'standup')
        title: Optional title override (defaults to project_type.title())

    Returns:
        Tuple of (path to created note, note content)
    """
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")

    # Create scratch directory if needed
    scratch_dir = kb_root / "scratch" / date_str
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # Find previous note of this type
    prev_note = find_previous_project_note(kb_root, project_type)

    # Build prev link
    if prev_note:
        # Use relative path from kb_root
        try:
            prev_rel = prev_note.relative_to(kb_root)
            prev_link = f"[[{prev_rel}]]"
        except ValueError:
            prev_link = f"[[{prev_note}]]"
    else:
        prev_link = ""

    # Build note content
    display_title = title or project_type.replace("_", " ").title()
    lines = [
        f"[[current/projects/{project_type}/agenda]]",
        f"prev: {prev_link}",
        "next:",
        "",
        f"# {display_title} - {date_str}",
        "",
        "## Notes",
        "",
    ]
    content = "\n".join(lines)

    # Create new note
    new_note = scratch_dir / f"{time_str}_{project_type}.md"
    new_note.write_text(content)

    # Update previous note's next: field to point to this note
    if prev_note and prev_note.exists():
        _update_next_link(prev_note, kb_root, new_note)

    return new_note, content


def _update_next_link(prev_note: Path, kb_root: Path, new_note: Path) -> bool:
    """Update a note's next: field to point to a new note.

    Args:
        prev_note: Path to the previous note to update
        kb_root: Root path of the knowledge base
        new_note: Path to the new note to link to

    Returns:
        True if update succeeded, False otherwise
    """
    try:
        prev_content = prev_note.read_text()

        # Calculate relative path for the new link
        try:
            new_rel = new_note.relative_to(kb_root)
            new_link = f"[[{new_rel}]]"
        except ValueError:
            new_link = f"[[{new_note}]]"

        # Replace empty next: with link to new note
        # Match "next:" followed by optional whitespace and end of line
        updated = re.sub(
            r"^(next:)\s*$",
            rf"\1 {new_link}",
            prev_content,
            flags=re.MULTILINE,
        )

        if updated != prev_content:
            prev_note.write_text(updated)
            return True

        return False
    except Exception:
        return False


def get_project_chain(kb_root: Path, project_type: str) -> list[Path]:
    """Get the full chain of project notes in chronological order.

    Args:
        kb_root: Root path of the knowledge base
        project_type: Type of project note (e.g., 'charter')

    Returns:
        List of paths in chronological order (oldest first)
    """
    pattern = re.compile(rf"\d{{6}}_{re.escape(project_type)}\.md$")
    scratch_dir = kb_root / "scratch"

    if not scratch_dir.exists():
        return []

    candidates = []
    for date_dir in sorted(scratch_dir.iterdir()):
        if date_dir.is_dir():
            notes = sorted(
                [n for n in date_dir.iterdir() if pattern.match(n.name)]
            )
            candidates.extend(notes)

    return candidates


def list_project_types(kb_root: Path) -> list[str]:
    """List all project types that have notes.

    Args:
        kb_root: Root path of the knowledge base

    Returns:
        List of unique project type names
    """
    pattern = re.compile(r"\d{6}_(.+)\.md$")
    scratch_dir = kb_root / "scratch"

    if not scratch_dir.exists():
        return []

    types = set()
    for date_dir in scratch_dir.iterdir():
        if date_dir.is_dir():
            for note in date_dir.iterdir():
                match = pattern.match(note.name)
                if match:
                    types.add(match.group(1))

    return sorted(types)
