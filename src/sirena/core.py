#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import subprocess
import json
import logging
import os
import re
import sys
import textwrap
import unicodedata
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import py7zr
from faster_whisper import BatchedInferencePipeline, WhisperModel


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
STOPWORDS = {
    "a",
    "al",
    "algo",
    "algun",
    "alguna",
    "algunas",
    "alguno",
    "algunos",
    "ante",
    "antes",
    "asi",
    "aun",
    "aunque",
    "bajo",
    "bien",
    "cada",
    "casi",
    "como",
    "con",
    "contra",
    "cual",
    "cuales",
    "cuando",
    "de",
    "del",
    "desde",
    "donde",
    "dos",
    "e",
    "el",
    "ella",
    "ellas",
    "ellos",
    "en",
    "entre",
    "era",
    "eramos",
    "eran",
    "es",
    "esa",
    "esas",
    "ese",
    "eso",
    "esos",
    "esta",
    "estaba",
    "estaban",
    "estado",
    "estais",
    "estamos",
    "estan",
    "estar",
    "estas",
    "este",
    "esto",
    "estos",
    "fue",
    "fueron",
    "ha",
    "hace",
    "hacia",
    "han",
    "hasta",
    "hay",
    "la",
    "las",
    "le",
    "les",
    "lo",
    "los",
    "mas",
    "me",
    "mi",
    "mis",
    "mucho",
    "muy",
    "nada",
    "ni",
    "no",
    "nos",
    "nosotros",
    "nuestra",
    "nuestro",
    "o",
    "otra",
    "otros",
    "para",
    "pero",
    "poco",
    "por",
    "porque",
    "que",
    "quien",
    "se",
    "sea",
    "segun",
    "ser",
    "si",
    "siempre",
    "sin",
    "sobre",
    "son",
    "su",
    "sus",
    "tambien",
    "te",
    "tiene",
    "todo",
    "tras",
    "tu",
    "un",
    "una",
    "uno",
    "unos",
    "usted",
    "ya",
    "y",
}
PENDING_CUES = (
    "pendiente",
    "monitor",
    "seguiremos",
    "proximo",
    "proxima",
    "manana",
    "despues",
    "mas adelante",
    "por confirmar",
    "a la espera",
    "veremos",
    "todavia",
    "faltara",
    "falta",
)
LOW_SIGNAL_CUES = (
    "buenos dias",
    "bienvenido",
    "bienvenida",
    "grupo aca",
    "muchas gracias",
    "gracias",
    "es un gusto",
    "continuamos",
    "saludar",
    "presento",
    "presentamos",
    "invitado",
    "no falta nadie",
    "honores a la bandera",
    "consejo directivo",
    "moderadora",
    "secretaria",
    "servidor de ustedes",
    "lectura del acta",
    "quienes votan a favor",
    "votan a favor",
    "formacion academica",
    "trayectoria en",
    "le damos la mas cordial",
    "es un honor tenerlo aqui",
    "presento a mis invitados",
    "le paso los microfonos",
    "orden del dia",
)
GLOSSARY_STOPWORDS = {
    "acasocio",
    "ahora",
    "antes",
    "bienvenido",
    "bienvenida",
    "bueno",
    "buenos",
    "casa",
    "continuamos",
    "congreso",
    "creo",
    "derecho",
    "diputado",
    "entonces",
    "esa",
    "esas",
    "ese",
    "estado",
    "esta",
    "este",
    "esto",
    "finalizado",
    "gracias",
    "grupo",
    "guerrero",
    "hay",
    "hola",
    "los",
    "muchas",
    "muy",
    "nacional",
    "nadie",
    "necesitamos",
    "nosotros",
    "otra",
    "para",
    "pareciera",
    "pero",
    "por",
    "presidenta",
    "pues",
    "que",
    "quiero",
    "reforma",
    "sin",
    "soy",
    "tenemos",
    "tiene",
    "una",
    "usted",
    "vamos",
}
GPU_LIBS_URL = (
    "https://github.com/Purfview/whisper-standalone-win/releases/download/libs/"
    "cuBLAS.and.cuDNN_CUDA12_win_v3.7z"
)
SEVEN_ZIP_URL = "https://www.7-zip.org/a/7zr.exe"
GPU_ATTEMPTS = (
    {"device": "cuda", "compute_type": "float16", "batch_size": 8, "label": "GPU float16"},
    {"device": "cuda", "compute_type": "int8_float16", "batch_size": 4, "label": "GPU int8_float16"},
    {"device": "cpu", "compute_type": "int8", "batch_size": 1, "label": "CPU int8"},
)
PLACE_CANDIDATES = (
    "Acapulco",
    "Guerrero",
    "México",
    "Ciudad de México",
    "Oaxaca",
    "Tamaulipas",
    "Chiapas",
    "Estados Unidos",
)
MEDIA_CANDIDATES = (
    "La Jornada",
    "Reforma",
    "El Economista",
    "El Sur de Guerrero",
)
INSTITUTION_CANDIDATES = (
    "Grupo ACA",
    "Morena",
    "Congreso del Estado",
    "Congreso de la Unión",
    "Cámara de Diputados",
    "Cámara de Senadores",
    "Guardia Nacional",
    "UNAM",
    "Universidad de Yale",
    "Instituto de Administración Pública",
    "PRD",
    "Movimiento Ciudadano",
    "servidores de la nación",
)
PROGRAM_CANDIDATES = (
    "Plan B de la reforma electoral",
    "Jóvenes Construyendo el Futuro",
    "Salud Casa por Casa",
    "programas sociales",
)
PERSON_ENTITY_STOPWORDS = {
    "Ahora",
    "Buenos",
    "Congreso",
    "Continuamos",
    "Estado",
    "Forma",
    "Gobierno",
    "Grupo",
    "Guardia",
    "Hola",
    "Instituto",
    "La",
    "Los",
    "Muchas",
    "Morena",
    "Muy",
    "No",
    "Oaxaca",
    "Partido",
    "Presidenta",
    "Presidente",
    "Primero",
    "Que",
    "Reforma",
    "Salud",
    "Se",
    "Si",
    "Tania",
    "Tiempo",
    "Universidad",
    "Y",
    "Yo",
}
ACRONYM_STOPWORDS = {"ACA", "IVA", "PIB", "PRI", "PRD", "UNAM"}
THEME_DEFINITIONS = {
    "reforma_electoral": {
        "label": "Reforma electoral y representación",
        "headline": "Reforma electoral: Congreso, plurinominales y reglas de representación",
        "keywords": (
            "reforma electoral",
            "plan b",
            "congreso",
            "plurinominal",
            "sobrerepresent",
            "representacion proporcional",
            "diputados",
            "senadores",
            "nepotismo",
            "reeleccion",
            "lista nominal",
            "democracia participativa",
            "regidor",
            "sindicatura",
        ),
    },
    "programas_sociales": {
        "label": "Programas sociales y operación territorial",
        "headline": "Programas sociales: Salud Casa por Casa, Jóvenes y operación territorial",
        "keywords": (
            "programas sociales",
            "jovenes construyendo el futuro",
            "salud casa por casa",
            "servidores de la nacion",
            "pescadores",
            "bienestar",
            "prevencion",
        ),
    },
    "economia_inversion": {
        "label": "Economía, deuda e inversión",
        "headline": "Economía del debate: deuda, inversión, pymes y sostenibilidad fiscal",
        "keywords": (
            "deuda",
            "inversion",
            "pymes",
            "economia",
            "producto interno bruto",
            "pib",
            "presupuesto",
            "gasto",
            "austeridad",
            "iva",
            "recaud",
            "riqueza",
        ),
    },
    "seguridad": {
        "label": "Seguridad y despliegue territorial",
        "headline": "Seguridad: Guardia Nacional, policía y presencia territorial",
        "keywords": (
            "guardia nacional",
            "seguridad",
            "policia",
            "ejercito",
            "marina",
            "efectivos",
        ),
    },
    "politica_morena": {
        "label": "Morena, candidaturas y disputa territorial",
        "headline": "Morena y Guerrero: candidaturas, territorio y proceso interno",
        "keywords": (
            "morena",
            "gubernatura",
            "gobernadora",
            "encuestas",
            "militantes",
            "estela",
            "adelina",
            "betty",
            "territorio",
            "candidatura",
        ),
    },
}


@dataclass
class SegmentLite:
    id: int
    start: float
    end: float
    text: str
    avg_logprob: float = 0.0
    no_speech_prob: float = 0.0
    words: list | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pipeline local para transcribir podcasts en espanol.")
    parser.add_argument("--sample-only", action="store_true", help="Solo corre la muestra de validacion.")
    parser.add_argument(
        "--editorial-only",
        action="store_true",
        help="Regenera resumen, boletin y revision de nombres desde segmentos.csv sin volver a transcribir.",
    )
    parser.add_argument("--force-cpu", action="store_true", help="Omite los intentos con GPU.")
    parser.add_argument("--model", default="turbo", help="Modelo faster-whisper a usar. Default: turbo")
    parser.add_argument(
        "--layout",
        choices=("legible", "fiel", "ambas"),
        default="legible",
        help="Estilo de salida principal. Default: legible",
    )
    parser.add_argument(
        "--protocol",
        choices=("compact", "keep", "separate"),
        default="compact",
        help="Manejo del protocolo inicial. Default: compact",
    )
    parser.add_argument(
        "--sample-seconds",
        type=int,
        default=480,
        help="Segundos de muestra inicial para validar. Default: 480",
    )
    parser.add_argument(
        "--min-silence-ms",
        type=int,
        default=500,
        help="Minimo de silencio para VAD en milisegundos. Default: 500",
    )
    return parser.parse_args()


def setup_logging(outputs_dir: Path) -> logging.Logger:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pipeline_transcripcion")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(outputs_dir / "ejecucion.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def detect_audio_file(project_root: Path) -> tuple[Path, list[Path]]:
    candidates: list[Path] = []
    search_roots = [project_root / "audio", project_root]
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
                candidates.append(path)
    if not candidates:
        raise FileNotFoundError("No se encontro ningun archivo de audio compatible en ./audio/ ni en la carpeta actual.")
    candidates = list(dict.fromkeys(candidates))
    ordered = sorted(candidates, key=lambda path: (path.stat().st_size, path.stat().st_mtime), reverse=True)
    return ordered[0], ordered


def ensure_gpu_libraries(project_root: Path, logger: logging.Logger) -> dict:
    gpu_root = project_root / ".local_gpu_libs"
    archive_path = gpu_root / "cuDNN_cuda12.7z"
    extract_marker = gpu_root / ".ok"
    result = {
        "requested_url": GPU_LIBS_URL,
        "status": "not_attempted",
        "archive": str(archive_path),
        "root": str(gpu_root),
        "dll_dirs": [],
        "error": "",
    }
    gpu_root.mkdir(parents=True, exist_ok=True)

    if not archive_path.exists():
        logger.info("Descargando librerias NVIDIA locales para Windows...")
        try:
            urllib.request.urlretrieve(GPU_LIBS_URL, archive_path)
        except Exception as exc:
            result["status"] = "download_failed"
            result["error"] = str(exc)
            logger.warning("No se pudieron descargar las DLLs GPU locales: %s", exc)
            return result

    if not extract_marker.exists():
        logger.info("Extrayendo librerias GPU locales...")
        try:
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=gpu_root)
            extract_marker.write_text(datetime.now().isoformat(), encoding="utf-8")
        except Exception as exc:
            logger.warning("py7zr no pudo extraer las DLLs GPU locales: %s", exc)
            try:
                extract_with_7zr(project_root, archive_path, gpu_root, logger)
                extract_marker.write_text(datetime.now().isoformat(), encoding="utf-8")
            except Exception as secondary_exc:
                result["status"] = "extract_failed"
                result["error"] = f"{exc} | fallback_7zr: {secondary_exc}"
                logger.warning("Tampoco fue posible extraer las DLLs GPU con 7zr: %s", secondary_exc)
                return result

    dll_dirs = sorted({str(path.parent) for path in gpu_root.rglob("*.dll")})
    if dll_dirs:
        prepend_to_path(dll_dirs)
        result["status"] = "ready"
        result["dll_dirs"] = dll_dirs
        logger.info("DLLs GPU locales listas. Directorios detectados: %s", len(dll_dirs))
    else:
        result["status"] = "no_dlls_found"
        logger.warning("Se descargo el paquete GPU, pero no se encontraron DLLs dentro.")
    return result


def prepend_to_path(paths: Iterable[str]) -> None:
    clean_paths = [str(Path(item)) for item in paths if item]
    if not clean_paths:
        return
    existing = os.environ.get("PATH", "")
    os.environ["PATH"] = ";".join(clean_paths + [existing])


def ensure_7zr_binary(project_root: Path, logger: logging.Logger) -> Path:
    tools_dir = project_root / ".tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    binary_path = tools_dir / "7zr.exe"
    if binary_path.exists():
        return binary_path
    logger.info("Descargando 7zr.exe local para extraer DLLs GPU...")
    urllib.request.urlretrieve(SEVEN_ZIP_URL, binary_path)
    return binary_path


def extract_with_7zr(project_root: Path, archive_path: Path, destination: Path, logger: logging.Logger) -> None:
    binary_path = ensure_7zr_binary(project_root, logger)
    command = [
        str(binary_path),
        "x",
        str(archive_path),
        f"-o{destination}",
        "-y",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"7zr fallo con codigo {completed.returncode}: {completed.stdout.strip()} {completed.stderr.strip()}".strip()
        )
    logger.info("Extraccion con 7zr.exe completada.")


def read_hotwords(glossary_path: Path) -> str | None:
    if not glossary_path.exists():
        return None
    lines = [line.strip() for line in glossary_path.read_text(encoding="utf-8").splitlines()]
    words = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        if lower in GLOSSARY_STOPWORDS:
            continue
        if len(line.split()) == 1 and len(line) < 5 and not line.isupper():
            continue
        words.append(line)
    return ", ".join(words[:200]) if words else None


def transcribe_once(
    audio_path: Path,
    model_name: str,
    attempt: dict,
    sample_seconds: int | None,
    outputs_dir: Path,
    logger: logging.Logger,
    hotwords: str | None,
    min_silence_ms: int,
    model_cache_dir: Path,
) -> tuple[list, dict]:
    logger.info(
        "Intentando transcripcion con %s | model=%s | device=%s | compute_type=%s | batch_size=%s",
        attempt["label"],
        model_name,
        attempt["device"],
        attempt["compute_type"],
        attempt["batch_size"],
    )
    model = WhisperModel(
        model_name,
        device=attempt["device"],
        compute_type=attempt["compute_type"],
        cpu_threads=max((os.cpu_count() or 4) - 1, 1),
        download_root=str(model_cache_dir),
    )
    kwargs = {
        "language": "es",
        "beam_size": 5,
        "word_timestamps": True,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": min_silence_ms},
        "condition_on_previous_text": False,
    }
    if hotwords:
        kwargs["hotwords"] = hotwords
    if sample_seconds:
        kwargs["clip_timestamps"] = f"0,{float(sample_seconds)}"
        segments, info = model.transcribe(str(audio_path), **kwargs)
    else:
        pipeline = BatchedInferencePipeline(model=model)
        kwargs["batch_size"] = attempt["batch_size"]
        segments, info = pipeline.transcribe(str(audio_path), **kwargs)
    segment_list = list(segments)
    metadata = {
        "attempt": dict(attempt),
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": getattr(info, "duration", None),
        "duration_after_vad": getattr(info, "duration_after_vad", None),
        "segment_count": len(segment_list),
        "sample_seconds": sample_seconds,
        "status": "ok",
    }
    logger.info(
        "Transcripcion exitosa con %s. segmentos=%s idioma=%s prob=%.4f",
        attempt["label"],
        len(segment_list),
        info.language,
        info.language_probability,
    )
    return segment_list, metadata


def run_transcription(
    audio_path: Path,
    model_name: str,
    force_cpu: bool,
    sample_seconds: int | None,
    outputs_dir: Path,
    logger: logging.Logger,
    hotwords: str | None,
    min_silence_ms: int,
    model_cache_dir: Path,
) -> tuple[list, dict]:
    attempts = [GPU_ATTEMPTS[-1]] if force_cpu else list(GPU_ATTEMPTS)
    errors: list[dict] = []
    for attempt in attempts:
        try:
            return transcribe_once(
                audio_path=audio_path,
                model_name=model_name,
                attempt=attempt,
                sample_seconds=sample_seconds,
                outputs_dir=outputs_dir,
                logger=logger,
                hotwords=hotwords,
                min_silence_ms=min_silence_ms,
                model_cache_dir=model_cache_dir,
            )
        except Exception as exc:
            logger.warning("Fallo %s: %s", attempt["label"], exc)
            errors.append({"attempt": dict(attempt), "error": str(exc)})
    raise RuntimeError(json.dumps(errors, ensure_ascii=False, indent=2))


def format_ts_compact(seconds: float) -> str:
    total_ms = int(round(max(seconds, 0) * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_ts_srt(seconds: float) -> str:
    return format_ts_compact(seconds).replace(".", ",")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def simplify_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_space(text).lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_joined_text(parts: list[str]) -> str:
    if not parts:
        return ""
    return normalize_space(" ".join(part.strip() for part in parts if part.strip()))


def transcript_faithful_text(segments: list) -> str:
    return "\n\n".join(normalize_space(segment.text) for segment in segments if normalize_space(segment.text))


def transcript_faithful_with_timestamps(segments: list) -> str:
    lines = []
    for segment in segments:
        text = normalize_space(segment.text)
        if not text:
            continue
        lines.append(
            f"[{format_ts_compact(segment.start)} --> {format_ts_compact(segment.end)}] {text}"
        )
    return "\n".join(lines)


def write_segments_csv(segments: list, csv_path: Path) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "segment_id",
                "start",
                "end",
                "duration",
                "avg_logprob",
                "no_speech_prob",
                "text",
                "words_json",
            ]
        )
        for segment in segments:
            words = [asdict(word) for word in segment.words] if segment.words else []
            writer.writerow(
                [
                    segment.id,
                    f"{segment.start:.3f}",
                    f"{segment.end:.3f}",
                    f"{(segment.end - segment.start):.3f}",
                    f"{segment.avg_logprob:.4f}",
                    f"{segment.no_speech_prob:.4f}",
                    normalize_space(segment.text),
                    json.dumps(words, ensure_ascii=False),
                ]
            )


def write_srt(segments: list, srt_path: Path) -> None:
    lines: list[str] = []
    counter = 1
    for segment in segments:
        text = normalize_space(segment.text)
        if not text:
            continue
        lines.append(str(counter))
        lines.append(f"{format_ts_srt(segment.start)} --> {format_ts_srt(segment.end)}")
        lines.append(text)
        lines.append("")
        counter += 1
    srt_path.write_text("\n".join(lines), encoding="utf-8")


def tokenize(text: str) -> list[str]:
    text = text.lower()
    return re.findall(r"[a-z0-9áéíóúñü]{3,}", text)


def is_low_signal_text(text: str) -> bool:
    lower = simplify_for_match(text)
    if not lower:
        return True
    cue_hits = sum(1 for cue in LOW_SIGNAL_CUES if cue in lower)
    short_tokens = len(tokenize(lower)) < 18
    return cue_hits >= 2 or (cue_hits >= 1 and short_tokens)


def score_units(units: list[dict]) -> list[dict]:
    counter: Counter[str] = Counter()
    prepared_units: list[tuple] = []
    for unit in units:
        text = normalize_space(unit["text"])
        tokens = [token for token in tokenize(text) if token not in STOPWORDS]
        prepared_units.append((unit, text, tokens))
        counter.update(tokens)

    scored: list[dict] = []
    for unit, text, tokens in prepared_units:
        unique_tokens = set(tokens)
        score = sum(counter[token] for token in unique_tokens)
        score += min(len(tokens), 25) * 0.5
        score += max(unit["end"] - unit["start"], 0) * 0.05
        if is_low_signal_text(text) or unit.get("kind") == "protocol":
            score *= 0.05
        scored.append({"unit": unit, "text": text, "tokens": tokens, "score": score})
    return scored


def choose_summary_units(units: list[dict], target_count: int = 6) -> list[dict]:
    scored = score_units(units)
    ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
    chosen: list[dict] = []
    seen = set()
    for item in ranked:
        text = item["text"]
        if len(text) < 40:
            continue
        if is_low_signal_text(text):
            continue
        fingerprint = " ".join(tokenize(text)[:12])
        if not fingerprint or fingerprint in seen:
            continue
        seen.add(fingerprint)
        chosen.append(item)
        if len(chosen) >= target_count:
            break
    return sorted(chosen, key=lambda item: item["unit"]["start"])


def detect_protocol_end_index(items: list[dict]) -> int:
    if not items:
        return 0
    lookahead = items[: min(len(items), 12)]
    if not lookahead:
        return 0
    low_signal_ratio = sum(1 for item in lookahead if item["low_signal"]) / len(lookahead)
    if low_signal_ratio < 0.45:
        return 0
    upper_limit = min(len(items), 80)
    for idx in range(0, upper_limit):
        if idx < 6 and items[idx]["segment"].start < 180:
            continue
        window = items[idx : idx + 4]
        if len(window) < 3:
            break
        substantive = [
            item
            for item in window
            if not item["low_signal"] and len(item["tokens"]) >= 18
        ]
        if len(substantive) >= 3:
            return idx
    return 0


def classify_reading_sections(blocks: list[dict]) -> list[dict]:
    qna_start = None
    for idx, block in enumerate(blocks):
        lower = block["text"].lower()
        if any(
            cue in lower
            for cue in (
                "preguntas y respuestas",
                "ronda de preguntas",
                "bloque de preguntas",
                "continuamos con el arquitecto",
                "es cuanto",
            )
        ):
            qna_start = idx
            break

    sections: list[dict] = []
    protocol_blocks = [block for block in blocks if block["kind"] == "protocol"]
    body_blocks = [block for block in blocks if block["kind"] != "protocol"]
    if protocol_blocks:
        sections.append({"title": "Apertura y protocolo", "blocks": protocol_blocks})

    if body_blocks:
        if qna_start is None:
            sections.append({"title": "Ponencia y desarrollo", "blocks": body_blocks})
        else:
            content_blocks = [block for block in body_blocks if block.get("body_index", 0) < qna_start]
            qna_blocks = [block for block in body_blocks if block.get("body_index", 0) >= qna_start]
            if content_blocks:
                sections.append({"title": "Ponencia y desarrollo", "blocks": content_blocks})
            if qna_blocks:
                sections.append({"title": "Preguntas y respuestas", "blocks": qna_blocks})
    return [section for section in sections if section["blocks"]]


def merge_block_text(parts: list[str]) -> str:
    return normalize_joined_text(parts)


def ends_with_strong_punctuation(text: str) -> bool:
    return normalize_space(text).endswith((".", "!", "?", ":", ";"))


def build_reading_blocks(segments: list, protocol_mode: str = "compact") -> list[dict]:
    items: list[dict] = []
    for index, segment in enumerate(segments):
        text = normalize_space(segment.text)
        if not text:
            continue
        items.append(
            {
                "index": index,
                "segment": segment,
                "text": text,
                "tokens": tokenize(text),
                "low_signal": is_low_signal_text(text),
            }
        )
    if not items:
        return []

    protocol_end = detect_protocol_end_index(items) if protocol_mode in {"compact", "separate"} else 0
    blocks: list[dict] = []
    current: list[dict] = []
    current_kind = "content"

    for idx, item in enumerate(items):
        kind = "protocol" if idx < protocol_end and protocol_mode in {"compact", "separate"} else "content"
        if not current:
            current = [item]
            current_kind = kind
            continue

        prev_segment = current[-1]["segment"]
        gap = item["segment"].start - prev_segment.end
        duration = item["segment"].end - current[0]["segment"].start
        current_text = current[-1]["text"]
        char_count = sum(len(unit["text"]) for unit in current)
        should_split = False

        if kind != current_kind:
            should_split = True
        elif kind == "protocol":
            should_split = gap > 20 or duration > 240 or char_count > 1100
        else:
            if gap > 12 or duration > 210 or char_count > 1500:
                should_split = True
            elif gap > 6 and ends_with_strong_punctuation(current_text):
                should_split = True
            elif len(item["tokens"]) >= 18 and len(current[-1]["tokens"]) >= 18 and ends_with_strong_punctuation(current_text):
                should_split = True

        if should_split:
            blocks.append(make_block(current, current_kind))
            current = [item]
            current_kind = kind
        else:
            current.append(item)

    if current:
        blocks.append(make_block(current, current_kind))

    blocks = relabel_initial_protocol_blocks(blocks, protocol_mode)
    blocks = prune_trivial_blocks(blocks)
    body_counter = 0
    for block in blocks:
        if block["kind"] != "protocol":
            block["body_index"] = body_counter
            body_counter += 1

    if protocol_mode == "separate":
        return blocks

    return blocks


def make_block(block_items: list[dict], kind: str) -> dict:
    text = merge_block_text([item["text"] for item in block_items])
    first_sentence = split_sentences(text)[0] if split_sentences(text) else text
    return {
        "start": block_items[0]["segment"].start,
        "end": block_items[-1]["segment"].end,
        "text": text,
        "headline": build_headline(first_sentence or text),
        "segment_count": len(block_items),
        "kind": kind,
    }


def relabel_initial_protocol_blocks(blocks: list[dict], protocol_mode: str) -> list[dict]:
    if protocol_mode not in {"compact", "separate"}:
        return blocks

    protocol_markers = (
        "honores a la bandera",
        "grupo aca",
        "lectura del acta",
        "formacion academica",
        "orden del dia",
        "consejo directivo",
        "moderadora",
        "presento a mi invitado",
        "presento a mis invitados",
        "bienvenido",
    )
    protocol_detected = False
    for block in blocks:
        if block["start"] > 20 * 60:
            break
        simplified = simplify_for_match(block["text"])
        token_count = len(tokenize(block["text"]))
        protocol_like = is_low_signal_text(block["text"]) or any(marker in simplified for marker in protocol_markers)
        if protocol_like or (protocol_detected and token_count < 220 and "preguntas y respuestas" not in simplified):
            block["kind"] = "protocol"
            protocol_detected = True
            continue
        if protocol_detected:
            break
    return blocks


def prune_trivial_blocks(blocks: list[dict]) -> list[dict]:
    cleaned: list[dict] = []
    for block in blocks:
        token_count = len(tokenize(block["text"]))
        if token_count <= 2 and len(block["text"]) <= 20 and block["start"] < 600:
            continue
        cleaned.append(block)
    return cleaned


def render_reading_text(blocks: list[dict], include_timestamps: bool = False) -> str:
    sections = classify_reading_sections(blocks)
    rendered_sections: list[str] = []
    for section in sections:
        section_lines = [section["title"]]
        for block in section["blocks"]:
            paragraph = textwrap.fill(block["text"], width=100)
            if include_timestamps:
                paragraph = (
                    f"[{format_ts_compact(block['start'])} --> {format_ts_compact(block['end'])}]\n{paragraph}"
                )
            section_lines.append(paragraph)
        rendered_sections.append("\n\n".join(section_lines))
    return "\n\n".join(rendered_sections).strip()


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[\.\?\!])\s+", normalize_space(text))
    return [piece.strip() for piece in pieces if piece.strip()]


def build_headline(text: str, max_words: int = 12) -> str:
    text = normalize_space(text)
    text = re.sub(r"^[\-\.\,\:\;]+", "", text)
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(",.;:") + "..."
    return text[:1].upper() + text[1:] if text else "Sin titular claro"


def find_pending_topics(units: list[dict]) -> list[str]:
    matches: list[str] = []
    for unit in units:
        text = normalize_space(unit["text"])
        lower = simplify_for_match(text)
        if any(cue in lower for cue in PENDING_CUES) and not is_low_signal_text(text):
            excerpt = text if len(text) <= 180 else text[:177].rstrip() + "..."
            matches.append(f"- [{format_ts_compact(unit['start'])}] {excerpt}")
    return matches[:6]


def generate_summary_md(
    reading_blocks: list[dict],
    metadata: dict,
    audio_path: Path,
    selected_audio_note: str,
) -> str:
    substantive_blocks = [block for block in reading_blocks if block["kind"] != "protocol"]
    chosen = choose_summary_units(substantive_blocks, target_count=6)
    top_blocks = sorted(substantive_blocks, key=lambda block: len(tokenize(block["text"])), reverse=True)[:5]
    executive_lines = [
        f"- [{format_ts_compact(item['unit']['start'])}] {item['text']}"
        for item in chosen
    ]
    block_lines = [
        f"### {block['headline']}\n\n"
        f"Rango: {format_ts_compact(block['start'])} - {format_ts_compact(block['end'])}\n\n"
        f"{textwrap.fill(block['text'][:900].rstrip() + ('...' if len(block['text']) > 900 else ''), width=100)}"
        for block in top_blocks
    ]
    pending = find_pending_topics(substantive_blocks)
    quality_note = (
        f"- Dispositivo final: {metadata['attempt']['device']} / {metadata['attempt']['compute_type']}\n"
        f"- Modelo: {metadata['model_name']}\n"
        f"- Idioma detectado: {metadata['language']} ({metadata['language_probability']:.4f})\n"
        f"- Segmentos: {metadata['segment_count']}\n"
        f"- Archivo usado: `{audio_path.name}`\n"
        f"- Seleccion: {selected_audio_note}"
    )
    return (
        "# Resumen de transcripcion\n\n"
        "## Resumen ejecutivo\n\n"
        + ("\n".join(executive_lines) if executive_lines else "- No hubo suficientes segmentos utiles para resumir.")
        + "\n\n## Bloques principales\n\n"
        + ("\n\n".join(block_lines) if block_lines else "No se pudieron construir bloques tematicos.")
        + "\n\n## Pendientes o focos detectados\n\n"
        + ("\n".join(pending) if pending else "- No se detectaron pendientes explicitos en la transcripcion.")
        + "\n\n## Notas de calidad\n\n"
        + quality_note
        + "\n"
    )


def generate_email_md(reading_blocks: list[dict]) -> str:
    substantive_blocks = [block for block in reading_blocks if block["kind"] != "protocol"]
    chosen = choose_summary_units(substantive_blocks, target_count=8)
    top_blocks = sorted(substantive_blocks, key=lambda block: len(tokenize(block["text"])), reverse=True)[:6]
    subject_basis = build_headline(chosen[0]["text"], max_words=10) if chosen else "Actualizacion del podcast"
    headlines = [f"- {build_headline(item['text'])}" for item in chosen[:8]]
    development = []
    for block in top_blocks:
        excerpt = block["text"] if len(block["text"]) <= 500 else block["text"][:497].rstrip() + "..."
        development.append(
            f"### {block['headline']}\n\n"
            f"{excerpt}\n\n"
            f"Ventana temporal: {format_ts_compact(block['start'])} - {format_ts_compact(block['end'])}"
        )
    pending = find_pending_topics(substantive_blocks)
    conclusion = chosen[-1]["text"] if chosen else "No hubo suficiente material para una conclusion automatica."
    executive = " ".join(item["text"] for item in chosen[:3]) if chosen else "No hubo suficiente material para un resumen ejecutivo."
    return (
        "# Boletin por email\n\n"
        f"## Asunto sugerido\n\n{subject_basis}\n\n"
        f"## Resumen ejecutivo\n\n{executive}\n\n"
        "## 5 a 10 titulares\n\n"
        + ("\n".join(headlines) if headlines else "- No se pudieron extraer titulares confiables.")
        + "\n\n## Desarrollo breve por bloques\n\n"
        + ("\n\n".join(development) if development else "No se pudieron construir bloques de desarrollo.")
        + "\n\n## Conclusion\n\n"
        + conclusion
        + "\n\n## Pendientes o temas a monitorear\n\n"
        + ("\n".join(pending) if pending else "- No se detectaron pendientes explicitos en la transcripcion.")
        + "\n"
    )


def build_glossary(segments: list, glossary_path: Path) -> None:
    title_case_counter: Counter[str] = Counter()
    acronym_counter: Counter[str] = Counter()
    for segment in segments:
        text = normalize_space(segment.text)
        for match in re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b", text):
            if len(match) > 2 and match.lower() not in GLOSSARY_STOPWORDS:
                title_case_counter[match] += 1
        for match in re.findall(r"\b[A-Z]{2,8}\b", text):
            acronym_counter[match] += 1
    candidates = [
        term
        for term, count in title_case_counter.most_common()
        if count >= 2
        and (len(term.split()) > 1 or term.isupper() or len(term) >= 6)
        and not is_low_signal_text(term)
    ]
    acronyms = [term for term, count in acronym_counter.most_common() if count >= 2]
    lines = [
        "# Glosario sugerido para reforzar nombres propios y siglas.",
        "# Puedes editar este archivo y volver a correr run_transcripcion.bat.",
        "# En la siguiente ejecucion se usara como hotwords en faster-whisper.",
        "",
    ]
    if candidates:
        lines.append("# Nombres o instituciones detectadas")
        lines.extend(candidates[:100])
        lines.append("")
    if acronyms:
        lines.append("# Siglas detectadas")
        lines.extend(acronyms[:100])
        lines.append("")
    if not candidates and not acronyms:
        lines.append("# No se detectaron candidatos claros automaticamente en esta corrida.")
    glossary_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def load_segments_from_csv(csv_path: Path) -> list[SegmentLite]:
    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontro {csv_path}")
    segments: list[SegmentLite] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            text = normalize_space(row.get("text", ""))
            if not text:
                continue
            segments.append(
                SegmentLite(
                    id=int(row.get("segment_id", len(segments) + 1)),
                    start=float(row.get("start", 0.0)),
                    end=float(row.get("end", 0.0)),
                    text=text,
                    avg_logprob=float(row.get("avg_logprob", 0.0) or 0.0),
                    no_speech_prob=float(row.get("no_speech_prob", 0.0) or 0.0),
                    words=None,
                )
            )
    return segments


def load_existing_metadata(outputs_dir: Path) -> dict:
    diagnostic_path = outputs_dir / "diagnostico.json"
    metadata = {
        "attempt": {"device": "desconocido", "compute_type": "desconocido"},
        "model_name": "desconocido",
        "language": "es",
        "language_probability": 0.0,
        "segment_count": 0,
    }
    if not diagnostic_path.exists():
        return metadata
    try:
        payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    except Exception:
        return metadata
    full_run = payload.get("full_run") or payload.get("sample_validation") or {}
    metadata.update(full_run)
    metadata["model_name"] = full_run.get("model_name") or payload.get("model_requested", "desconocido")
    metadata["attempt"] = full_run.get("attempt") or metadata["attempt"]
    metadata["segment_count"] = full_run.get("segment_count") or payload.get("segment_count", 0)
    return metadata


def count_numbers(text: str) -> int:
    return len(re.findall(r"\b\d+(?:[\.,]\d+)?%?\b", text))


def count_acronyms(text: str) -> int:
    return len(
        [
            match
            for match in re.findall(r"\b[A-ZÁÉÍÓÚÑ]{2,8}\b", text)
            if match not in ACRONYM_STOPWORDS
        ]
    )


def clean_editorial_sentence(text: str) -> str:
    text = normalize_space(text)
    text = re.sub(
        r"^(?:y|pues|bueno|entonces|mire[n]?|digamos|este|esta|as[ií]|ahora|o sea|finalmente|por otra parte)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text[:1].upper() + text[1:] if text else text


def extract_entity_catalog(blocks: list[dict]) -> dict:
    corpus = " ".join(block["text"] for block in blocks)
    simplified = simplify_for_match(corpus)
    persons: Counter[str] = Counter()
    places: Counter[str] = Counter()
    institutions: Counter[str] = Counter()
    media: Counter[str] = Counter()
    programs: Counter[str] = Counter()
    acronyms: Counter[str] = Counter()

    person_pattern = re.compile(r"\b(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,3})\b")
    for match in person_pattern.findall(corpus):
        normalized = normalize_space(match)
        normalized = re.sub(r"^(Soy|Hola|Buenos días|Muy buenos días|Gracias|Diputado|Licenciado)\s+", "", normalized)
        words = normalized.split()
        if any(word in PERSON_ENTITY_STOPWORDS for word in words):
            continue
        simplified_name = simplify_for_match(normalized)
        if any(simplify_for_match(term) in simplified_name for term in INSTITUTION_CANDIDATES + PROGRAM_CANDIDATES):
            continue
        if any(
            token in simplified_name
            for token in (
                "producto interno bruto",
                "cuarta transformacion",
                "estados unidos",
                "jovenes construyendo",
                "america latina",
                "plan mexico",
            )
        ):
            continue
        persons[normalized] += 1

    for term in PLACE_CANDIDATES:
        count = simplified.count(simplify_for_match(term))
        if count:
            places[term] += count
    for term in INSTITUTION_CANDIDATES:
        count = simplified.count(simplify_for_match(term))
        if count:
            institutions[term] += count
    for term in MEDIA_CANDIDATES:
        count = simplified.count(simplify_for_match(term))
        if count:
            media[term] += count
    for term in PROGRAM_CANDIDATES:
        count = simplified.count(simplify_for_match(term))
        if count:
            programs[term] += count

    for match in re.findall(r"\b[A-ZÁÉÍÓÚÑ]{2,8}\b", corpus):
        if match in ACRONYM_STOPWORDS:
            continue
        acronyms[match] += 1

    unique_persons = []
    seen_persons = set()
    for term, _ in persons.most_common(80):
        key = simplify_for_match(term)
        if key in seen_persons:
            continue
        seen_persons.add(key)
        unique_persons.append(term)

    return {
        "personas": unique_persons[:40],
        "lugares": [term for term, _ in places.most_common(20)],
        "instituciones": [term for term, _ in institutions.most_common(30)],
        "medios": [term for term, _ in media.most_common(20)],
        "programas": [term for term, _ in programs.most_common(20)],
        "siglas": [term for term, _ in acronyms.most_common(20)],
    }


def summarize_protocol_blocks(protocol_blocks: list[dict], entity_catalog: dict) -> list[str]:
    if not protocol_blocks:
        return []
    text = " ".join(block["text"] for block in protocol_blocks)
    simplified = simplify_for_match(text)
    paragraphs: list[str] = []

    opening_parts = []
    if "honores a la bandera" in simplified:
        opening_parts.append("honores a la bandera")
    if "moderadora" in simplified:
        if "escobar" in simplified:
            opening_parts.append("la presentación de la moderadora Denise Escobar")
        else:
            opening_parts.append("la presentación de la moderadora")
    if "grupo aca" in simplified:
        opening_parts.append("saludos y presentación de asistentes de Grupo ACA")
    if opening_parts:
        paragraphs.append(
            "La sesión abrió con "
            + ", ".join(opening_parts[:-1] + ([f"y {opening_parts[-1]}"] if len(opening_parts) > 1 else opening_parts))
            + "."
        )

    second_parts = []
    if "lectura del acta" in simplified or "votan a favor" in simplified:
        second_parts.append("se sometió a votación la omisión de la lectura del acta anterior")
    if "formacion academica" in simplified or "trayectoria" in simplified:
        if "pablo sandoval" in simplified:
            second_parts.append("se leyó una semblanza del ponente Pablo Sandoval")
        else:
            second_parts.append("se leyó la semblanza del ponente")
    if "preguntas y respuestas" in simplified or "ronda de preguntas" in simplified:
        second_parts.append("antes de pasar a la ponencia y a la ronda de preguntas")
    if second_parts:
        paragraphs.append("En la apertura, además, " + ", ".join(second_parts) + ".")

    if not paragraphs:
        participants = ", ".join(entity_catalog.get("personas", [])[:4])
        base = "La apertura estuvo dominada por saludos, presentación de invitados y formalidades previas al bloque principal."
        if participants:
            base += f" Entre los nombres que aparecen en ese tramo figuran {participants}."
        paragraphs.append(base)

    return paragraphs[:3]


def score_theme_block(block: dict, theme_id: str) -> int:
    simplified = simplify_for_match(block["text"])
    return sum(simplified.count(keyword) for keyword in THEME_DEFINITIONS[theme_id]["keywords"])


def detect_theme_clusters(blocks: list[dict]) -> list[dict]:
    themed_blocks: list[dict] = []
    for block in blocks:
        if block["kind"] == "protocol":
            continue
        scores = {theme_id: score_theme_block(block, theme_id) for theme_id in THEME_DEFINITIONS}
        best_theme = max(scores, key=scores.get)
        best_score = scores[best_theme]
        if best_score <= 0:
            continue
        enriched = dict(block)
        enriched["theme_id"] = best_theme
        enriched["theme_score"] = best_score
        themed_blocks.append(enriched)

    grouped: list[dict] = []
    for theme_id, config in THEME_DEFINITIONS.items():
        members = [block for block in themed_blocks if block["theme_id"] == theme_id]
        if not members:
            continue
        members = sorted(members, key=lambda block: (block["theme_score"], len(tokenize(block["text"]))), reverse=True)
        grouped.append(
            {
                "theme_id": theme_id,
                "label": config["label"],
                "headline": config["headline"],
                "blocks": members,
                "score": sum(block["theme_score"] for block in members),
            }
        )
    return sorted(grouped, key=lambda item: item["score"], reverse=True)


def extract_salient_sentences(blocks: list[dict], theme_id: str, limit: int = 3) -> list[str]:
    chosen: list[tuple[int, str]] = []
    seen = set()
    keywords = THEME_DEFINITIONS[theme_id]["keywords"]
    for block in blocks:
        for sentence in split_sentences(block["text"]):
            sentence = clean_editorial_sentence(sentence)
            if len(tokenize(sentence)) < 9:
                continue
            simplified = simplify_for_match(sentence)
            if any(cue in simplified for cue in ("bienvenido", "continuamos", "buenos dias", "gracias")):
                continue
            score = sum(simplified.count(keyword) for keyword in keywords) * 4
            score += count_numbers(sentence) * 3
            score += count_acronyms(sentence) * 2
            score += len(re.findall(r"\b(?:[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2})\b", sentence)) * 2
            score += min(len(tokenize(sentence)), 40)
            fingerprint = " ".join(tokenize(sentence)[:14])
            if not fingerprint or fingerprint in seen:
                continue
            seen.add(fingerprint)
            chosen.append((score, sentence))
    chosen.sort(key=lambda item: item[0], reverse=True)
    return [sentence for _, sentence in chosen[:limit]]


def build_editorial_theme_sections(reading_blocks: list[dict]) -> list[dict]:
    theme_clusters = detect_theme_clusters(reading_blocks)
    sections: list[dict] = []
    for cluster in theme_clusters[:6]:
        summary_sentences = build_theme_summary(cluster["theme_id"], cluster["blocks"])
        if not summary_sentences:
            summary_sentences = extract_salient_sentences(cluster["blocks"], cluster["theme_id"], limit=2)
        if not summary_sentences:
            continue
        sections.append(
            {
                "theme_id": cluster["theme_id"],
                "label": cluster["label"],
                "headline": cluster["headline"],
                "sentences": summary_sentences,
                "summary": " ".join(summary_sentences[:2]),
                "start": min(block["start"] for block in cluster["blocks"]),
                "end": max(block["end"] for block in cluster["blocks"]),
            }
        )
    return sections


def build_theme_summary(theme_id: str, blocks: list[dict]) -> list[str]:
    text = " ".join(block["text"] for block in blocks)
    simplified = simplify_for_match(text)
    lines: list[str] = []

    if theme_id == "reforma_electoral":
        if "32 diput" in simplified and "20 diput" in simplified and "12 diput" in simplified:
            lines.append(
                "Se defendió una reforma para dejar el Congreso local en 32 diputaciones: 20 de mayoría relativa y 12 de representación proporcional."
            )
        if "15 y 1" in simplified or "regidor" in simplified or "sindicatura" in simplified:
            lines.append(
                "El paquete también mencionó límites de hasta 15 regidurías y una sindicatura por ayuntamiento, además de reglas sobre representación, nepotismo y reelección."
            )
        if "0.7%" in text or "0.7" in simplified:
            lines.append(
                "Entre los puntos expuestos apareció además un tope presupuestal de 0.7% para el Congreso estatal."
            )

    elif theme_id == "programas_sociales":
        if "salud casa por casa" in simplified:
            lines.append(
                "Salud Casa por Casa fue presentado como un programa todavía en fase de arranque, por lo que su balance se planteó como una discusión aún abierta."
            )
        if "jovenes construyendo el futuro" in simplified:
            lines.append(
                "Jóvenes Construyendo el Futuro apareció como un eje de debate sobre inserción laboral, seguimiento y resultados concretos."
            )
        if "42%" in text or "42 millones" in text:
            lines.append(
                "También se discutió la operación de los programas sociales, la universalidad de los apoyos y el riesgo de clientelismo en su aplicación territorial."
            )

    elif theme_id == "economia_inversion":
        if "deuda" in simplified or "inversion" in simplified:
            lines.append(
                "El bloque económico giró sobre deuda pública, inversión extranjera y la viabilidad de sostener programas sociales con una economía bajo presión."
            )
        if "pymes" in simplified or "riqueza" in simplified:
            lines.append(
                "En paralelo se pidió una política económica más cercana a pymes y sectores productivos de Guerrero."
            )
        if "25%" in text:
            lines.append(
                "La propuesta de reforma también se vinculó con la idea de recortar 25% del gasto electoral y partidista."
            )

    elif theme_id == "seguridad":
        if "guardia nacional" in simplified:
            lines.append(
                "En seguridad se reclamó mayor presencia territorial y se puso como referencia el despliegue de la Guardia Nacional."
            )
        if "nueva policia" in simplified or "policia" in simplified:
            lines.append(
                "Las intervenciones insistieron en la necesidad de una nueva policía orientada al ciudadano y no a la protección del gobernante."
            )

    elif theme_id == "politica_morena":
        if "morena" in simplified and ("encuestas" in simplified or "gubernatura" in simplified):
            lines.append(
                "El debate se abrió hacia el proceso interno de Morena en Guerrero, con referencias a encuestas, territorio y candidaturas."
            )
        if any(name in simplified for name in ("estela", "adelina", "betty")):
            lines.append(
                "Entre las preguntas aparecieron nombres de aspirantes y figuras políticas ligadas a la disputa por la gubernatura."
            )

    if not lines:
        return []
    return lines[:3]


def build_email_subject(theme_sections: list[dict], entity_catalog: dict) -> str:
    place = "Guerrero" if "Guerrero" in entity_catalog.get("lugares", []) else (entity_catalog.get("lugares") or ["Podcast"])[0]
    themes = [section["headline"] for section in theme_sections[:3]]
    if not themes:
        return f"{place}: principales temas del podcast"
    short_parts = []
    for headline in themes:
        short = headline.split(":")[0]
        if short not in short_parts:
            short_parts.append(short)
    return f"{place}: " + ", ".join(short_parts[:3])


def generate_revision_nombres_propios_md(entity_catalog: dict) -> str:
    personas = [item for item in entity_catalog.get("personas", []) if not item.startswith("Soy ")]
    lines = [
        "# Revision rapida de nombres propios",
        "",
        "Lista preliminar extraida de la transcripcion para revision manual.",
        "",
        "## Personas",
        "",
    ]
    lines.extend(f"- {item}" for item in personas[:30] or ["- Sin detecciones claras"])
    lines.extend(["", "## Lugares", ""])
    lines.extend(f"- {item}" for item in entity_catalog.get("lugares", [])[:20] or ["- Sin detecciones claras"])
    lines.extend(["", "## Instituciones y partidos", ""])
    lines.extend(f"- {item}" for item in entity_catalog.get("instituciones", [])[:25] or ["- Sin detecciones claras"])
    lines.extend(["", "## Programas y politicas", ""])
    lines.extend(f"- {item}" for item in entity_catalog.get("programas", [])[:20] or ["- Sin detecciones claras"])
    lines.extend(["", "## Medios", ""])
    lines.extend(f"- {item}" for item in entity_catalog.get("medios", [])[:20] or ["- Sin detecciones claras"])
    lines.extend(["", "## Siglas", ""])
    lines.extend(f"- {item}" for item in entity_catalog.get("siglas", [])[:20] or ["- Sin detecciones claras"])
    return "\n".join(lines) + "\n"


def generate_editorial_summary_md(
    reading_blocks: list[dict],
    metadata: dict,
    audio_path: Path,
    selected_audio_note: str,
) -> str:
    entity_catalog = extract_entity_catalog(reading_blocks)
    protocol_paragraphs = summarize_protocol_blocks(
        [block for block in reading_blocks if block["kind"] == "protocol"],
        entity_catalog,
    )
    theme_sections = build_editorial_theme_sections(reading_blocks)
    executive_lines = [f"- {section['summary']}" for section in theme_sections[:5]]
    theme_blocks = [
        f"### {section['headline']}\n\n"
        f"Rango: {format_ts_compact(section['start'])} - {format_ts_compact(section['end'])}\n\n"
        f"{textwrap.fill(section['summary'], width=100)}"
        for section in theme_sections[:5]
    ]
    pending = find_pending_topics([block for block in reading_blocks if block["kind"] != "protocol"])
    quality_note = (
        f"- Dispositivo final: {metadata['attempt']['device']} / {metadata['attempt']['compute_type']}\n"
        f"- Modelo: {metadata['model_name']}\n"
        f"- Idioma detectado: {metadata['language']} ({metadata['language_probability']:.4f})\n"
        f"- Segmentos: {metadata['segment_count']}\n"
        f"- Archivo usado: `{audio_path.name}`\n"
        f"- Seleccion: {selected_audio_note}"
    )
    names_focus = []
    if entity_catalog.get("personas"):
        names_focus.append("Personas: " + ", ".join(entity_catalog["personas"][:8]))
    if entity_catalog.get("instituciones"):
        names_focus.append("Instituciones: " + ", ".join(entity_catalog["instituciones"][:8]))
    if entity_catalog.get("lugares"):
        names_focus.append("Lugares: " + ", ".join(entity_catalog["lugares"][:6]))
    return (
        "# Resumen de transcripcion\n\n"
        "## Apertura y protocolo\n\n"
        + ("\n\n".join(protocol_paragraphs) if protocol_paragraphs else "Sin bloque protocolario claramente distinguible.")
        + "\n\n## Resumen ejecutivo\n\n"
        + ("\n".join(executive_lines) if executive_lines else "- No hubo suficientes bloques sustantivos para resumir.")
        + "\n\n## Temas principales\n\n"
        + ("\n\n".join(theme_blocks) if theme_blocks else "No se pudieron construir temas principales.")
        + "\n\n## Nombres, instituciones y referencias\n\n"
        + ("\n".join(f"- {line}" for line in names_focus) if names_focus else "- Revisar revision_nombres_propios.md")
        + "\n\n## Pendientes o focos detectados\n\n"
        + ("\n".join(pending) if pending else "- No se detectaron pendientes explicitos en la transcripcion.")
        + "\n\n## Notas de calidad\n\n"
        + quality_note
        + "\n"
    )


def generate_editorial_email_md(reading_blocks: list[dict]) -> str:
    entity_catalog = extract_entity_catalog(reading_blocks)
    protocol_paragraphs = summarize_protocol_blocks(
        [block for block in reading_blocks if block["kind"] == "protocol"],
        entity_catalog,
    )
    theme_sections = build_editorial_theme_sections(reading_blocks)
    subject = build_email_subject(theme_sections, entity_catalog)
    executive = " ".join(section["summary"] for section in theme_sections[:2]) or "No hubo suficientes bloques para un resumen ejecutivo."
    headlines = [f"- {section['headline']}" for section in theme_sections[:8]]
    developments = []
    for section in theme_sections[:5]:
        developments.append(
            f"### {section['headline']}\n\n"
            f"{textwrap.fill(section['summary'], width=100)}\n\n"
            f"Ventana temporal: {format_ts_compact(section['start'])} - {format_ts_compact(section['end'])}"
        )
    pending = find_pending_topics([block for block in reading_blocks if block["kind"] != "protocol"])
    closing = (
        theme_sections[0]["summary"]
        if theme_sections
        else "El contenido principal requiere una revision manual adicional para definir un cierre editorial."
    )
    return (
        "# Boletin por email\n\n"
        f"## Asunto sugerido\n\n{subject}\n\n"
        "## Apertura y protocolo\n\n"
        + ("\n\n".join(protocol_paragraphs[:2]) if protocol_paragraphs else "La apertura fue protocolaria y se omite en esta version de lectura.")
        + "\n\n## Resumen ejecutivo\n\n"
        + executive
        + "\n\n## 5 a 10 titulares claros\n\n"
        + ("\n".join(headlines) if headlines else "- No se pudieron construir titulares claros.")
        + "\n\n## Desarrollo por temas\n\n"
        + ("\n\n".join(developments) if developments else "No se pudieron construir desarrollos por temas.")
        + "\n\n## Cierre\n\n"
        + closing
        + "\n\n## Pendientes o temas a monitorear\n\n"
        + ("\n".join(pending) if pending else "- No se detectaron pendientes explicitos en la transcripcion.")
        + "\n"
    )


def validate_outputs(paths: Iterable[Path]) -> list[str]:
    issues = []
    for path in paths:
        if not path.exists():
            issues.append(f"Falta {path.name}")
            continue
        if path.stat().st_size == 0:
            issues.append(f"Archivo vacio: {path.name}")
    return issues


def save_diagnostic(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    outputs_dir = project_root / "salidas"
    model_cache_dir = project_root / ".cache_models"
    logger = setup_logging(outputs_dir)
    logger.info("Iniciando pipeline local de transcripcion.")

    if args.editorial_only:
        selected_audio, all_audio = detect_audio_file(project_root)
        selected_audio_note = (
            f"Se eligio `{selected_audio.name}` entre {len(all_audio)} archivo(s) aplicando tamano descendente y, "
            "en empate, fecha mas reciente."
        )
        segments = load_segments_from_csv(outputs_dir / "segmentos.csv")
        metadata = load_existing_metadata(outputs_dir)
        metadata["segment_count"] = len(segments)
        reading_blocks = build_reading_blocks(segments, protocol_mode=args.protocol)
        resumen_path = outputs_dir / "resumen.md"
        boletin_path = outputs_dir / "boletin_email.md"
        revision_path = outputs_dir / "revision_nombres_propios.md"
        resumen_path.write_text(
            generate_editorial_summary_md(
                reading_blocks=reading_blocks,
                metadata=metadata,
                audio_path=selected_audio,
                selected_audio_note=selected_audio_note,
            ),
            encoding="utf-8",
        )
        boletin_path.write_text(generate_editorial_email_md(reading_blocks), encoding="utf-8")
        revision_path.write_text(
            generate_revision_nombres_propios_md(extract_entity_catalog(reading_blocks)),
            encoding="utf-8",
        )
        issues = validate_outputs([resumen_path, boletin_path, revision_path])
        if issues:
            logger.error("La regeneracion editorial termino con archivos faltantes o vacios: %s", issues)
            return 1
        logger.info("Regeneracion editorial completada en %s", outputs_dir)
        return 0

    selected_audio, all_audio = detect_audio_file(project_root)
    selected_audio_note = (
        f"Se eligio `{selected_audio.name}` entre {len(all_audio)} archivo(s) aplicando tamano descendente y, "
        "en empate, fecha mas reciente."
    )
    logger.info("Audio seleccionado: %s", selected_audio)

    vc_runtime_present = (Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "vcruntime140.dll").exists()
    gpu_setup = ensure_gpu_libraries(project_root, logger) if not args.force_cpu else {"status": "skipped_force_cpu"}
    hotwords = read_hotwords(project_root / "glosario_nombres.txt")

    diagnostic = {
        "run_started_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "audio_selected": str(selected_audio),
        "audio_candidates": [str(path) for path in all_audio],
        "selection_note": selected_audio_note,
        "gpu_setup": gpu_setup,
        "vc_runtime_present": vc_runtime_present,
        "python": sys.version,
        "sample_only": args.sample_only,
        "force_cpu": args.force_cpu,
        "model_requested": args.model,
        "layout_requested": args.layout,
        "protocol_requested": args.protocol,
    }
    save_diagnostic(outputs_dir / "diagnostico.json", diagnostic)

    sample_segments, sample_meta = run_transcription(
        audio_path=selected_audio,
        model_name=args.model,
        force_cpu=args.force_cpu,
        sample_seconds=args.sample_seconds,
        outputs_dir=outputs_dir,
        logger=logger,
        hotwords=None,
        min_silence_ms=args.min_silence_ms,
        model_cache_dir=model_cache_dir,
    )
    sample_meta["model_name"] = args.model
    diagnostic["sample_validation"] = sample_meta
    (outputs_dir / "muestra_validacion.json").write_text(
        json.dumps(sample_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    save_diagnostic(outputs_dir / "diagnostico.json", diagnostic)

    if args.sample_only:
        sample_blocks = build_reading_blocks(sample_segments, protocol_mode=args.protocol)
        sample_text = (
            transcript_faithful_text(sample_segments)
            if args.layout == "fiel"
            else render_reading_text(sample_blocks, include_timestamps=False)
        )
        (outputs_dir / "muestra_transcripcion.txt").write_text(sample_text + "\n", encoding="utf-8")
        logger.info("Modo sample-only completado.")
        return 0

    full_force_cpu = args.force_cpu or sample_meta["attempt"]["device"] == "cpu"
    full_segments, full_meta = run_transcription(
        audio_path=selected_audio,
        model_name=args.model,
        force_cpu=full_force_cpu,
        sample_seconds=None,
        outputs_dir=outputs_dir,
        logger=logger,
        hotwords=hotwords,
        min_silence_ms=args.min_silence_ms,
        model_cache_dir=model_cache_dir,
    )
    full_meta["model_name"] = args.model
    diagnostic["full_run"] = full_meta
    save_diagnostic(outputs_dir / "diagnostico.json", diagnostic)

    reading_blocks = build_reading_blocks(full_segments, protocol_mode=args.protocol)
    faithful_text = transcript_faithful_text(full_segments)
    legible_text = render_reading_text(reading_blocks, include_timestamps=False)
    timestamps_text = render_reading_text(reading_blocks, include_timestamps=True)
    primary_text = faithful_text if args.layout == "fiel" else legible_text
    transcripcion_path = outputs_dir / "transcripcion.txt"
    transcripcion_fiel_path = outputs_dir / "transcripcion_fiel.txt"
    transcripcion_timestamps_path = outputs_dir / "transcripcion_con_timestamps.txt"
    segmentos_csv_path = outputs_dir / "segmentos.csv"
    subtitulos_path = outputs_dir / "subtitulos.srt"
    resumen_path = outputs_dir / "resumen.md"
    boletin_path = outputs_dir / "boletin_email.md"
    revision_path = outputs_dir / "revision_nombres_propios.md"
    glossary_path = project_root / "glosario_nombres.txt"

    transcripcion_path.write_text(primary_text + "\n", encoding="utf-8")
    transcripcion_fiel_path.write_text(faithful_text + "\n", encoding="utf-8")
    transcripcion_timestamps_path.write_text(timestamps_text + "\n", encoding="utf-8")
    write_segments_csv(full_segments, segmentos_csv_path)
    write_srt(full_segments, subtitulos_path)
    build_glossary(full_segments, glossary_path)

    refresh_hotwords = read_hotwords(glossary_path)
    if refresh_hotwords and not hotwords:
        logger.info("Se genero glosario_nombres.txt para reforzar hotwords en futuras corridas.")

    resumen_path.write_text(
        generate_editorial_summary_md(
            reading_blocks=reading_blocks,
            metadata=full_meta,
            audio_path=selected_audio,
            selected_audio_note=selected_audio_note,
        ),
        encoding="utf-8",
    )
    boletin_path.write_text(generate_editorial_email_md(reading_blocks), encoding="utf-8")
    revision_path.write_text(
        generate_revision_nombres_propios_md(extract_entity_catalog(reading_blocks)),
        encoding="utf-8",
    )

    required_outputs = [
        transcripcion_path,
        transcripcion_fiel_path,
        transcripcion_timestamps_path,
        segmentos_csv_path,
        subtitulos_path,
        resumen_path,
        boletin_path,
        revision_path,
    ]
    issues = validate_outputs(required_outputs)
    diagnostic["validation_issues"] = issues
    diagnostic["run_finished_at"] = datetime.now().isoformat()
    save_diagnostic(outputs_dir / "diagnostico.json", diagnostic)

    if issues:
        logger.error("La corrida termino con archivos faltantes o vacios: %s", issues)
        return 1

    logger.info("Pipeline completo. Archivos generados en %s", outputs_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
