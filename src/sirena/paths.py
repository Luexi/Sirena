from __future__ import annotations

import re
import unicodedata
from pathlib import Path


AUDIO_EXTENSIONS = {
    ".mp3",
    ".mpeg",
    ".m4a",
    ".mp4",
    ".wav",
    ".flac",
    ".ogg",
    ".aac",
    ".webm",
}


def project_root_from(module_file: str) -> Path:
    return Path(module_file).resolve().parents[2]


def _strip_known_audio_suffixes(path: Path) -> str:
    stem = path.name
    probe = Path(stem)
    while probe.suffix.lower() in AUDIO_EXTENSIONS:
        stem = probe.stem
        probe = Path(stem)
    return probe.stem if probe.suffix else stem


def slugify_audio_name(audio_path: Path) -> str:
    base_name = _strip_known_audio_suffixes(audio_path)
    normalized = unicodedata.normalize("NFKD", base_name.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug or "audio"


def find_audio_candidates(project_root: Path) -> list[Path]:
    candidates: list[Path] = []
    search_roots = [project_root / "audio", project_root]
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                candidates.append(path.resolve())
    return list(dict.fromkeys(candidates))


def detect_audio_file(project_root: Path) -> tuple[Path, list[Path], str]:
    candidates = find_audio_candidates(project_root)
    if not candidates:
        raise FileNotFoundError(
            "No se encontro ningun archivo de audio compatible en ./audio/ ni en la carpeta actual."
        )
    ordered = sorted(candidates, key=lambda path: (path.stat().st_size, path.stat().st_mtime), reverse=True)
    selected = ordered[0]
    note = (
        f"Se eligio `{selected.name}` entre {len(ordered)} archivo(s) aplicando tamano descendente y, "
        "en empate, fecha mas reciente."
    )
    return selected, ordered, note


def resolve_audio_selection(project_root: Path, audio_arg: str | None) -> tuple[Path, list[Path], str]:
    if not audio_arg:
        return detect_audio_file(project_root)

    candidate = Path(audio_arg).expanduser()
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve()
    if not candidate.exists():
        raise FileNotFoundError(f"No existe el audio indicado en --audio: {candidate}")
    if not candidate.is_file():
        raise FileNotFoundError(f"La ruta indicada en --audio no es un archivo: {candidate}")
    if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"Extension no compatible para audio: {candidate.suffix}")
    note = f"Se uso el archivo indicado por --audio: `{candidate.name}`."
    return candidate, [candidate], note


def build_output_dir(project_root: Path, audio_path: Path) -> Path:
    return project_root / "salidas" / slugify_audio_name(audio_path)
