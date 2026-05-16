from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import core
from .paths import AUDIO_EXTENSIONS, build_output_dir, find_audio_candidates, project_root_from, resolve_audio_selection


STATE_DIRNAME = ".sirena_state"
REGISTRY_FILENAME = "jobs.json"


@dataclass
class RunOptions:
    audio: str | None = None
    sample_only: bool = False
    editorial_only: bool = False
    force_cpu: bool = False
    model: str = "turbo"
    layout: str = "legible"
    protocol: str = "compact"
    sample_seconds: int = 480
    min_silence_ms: int = 500


def now_iso() -> str:
    return datetime.now().isoformat()


def get_project_root() -> Path:
    return project_root_from(__file__)


def ensure_audio_workspace(project_root: Path | None = None) -> Path:
    root = project_root or get_project_root()
    audio_dir = root / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    return audio_dir


def ensure_state_workspace(project_root: Path | None = None) -> Path:
    root = project_root or get_project_root()
    state_dir = root / STATE_DIRNAME
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def registry_path(project_root: Path | None = None) -> Path:
    return ensure_state_workspace(project_root) / REGISTRY_FILENAME


def build_output_paths(outputs_dir: Path) -> dict[str, Path]:
    return {
        "diagnostico": outputs_dir / "diagnostico.json",
        "ejecucion": outputs_dir / "ejecucion.log",
        "muestra_validacion": outputs_dir / "muestra_validacion.json",
        "muestra_transcripcion": outputs_dir / "muestra_transcripcion.txt",
        "transcripcion": outputs_dir / "transcripcion.txt",
        "transcripcion_fiel": outputs_dir / "transcripcion_fiel.txt",
        "transcripcion_con_timestamps": outputs_dir / "transcripcion_con_timestamps.txt",
        "segmentos_csv": outputs_dir / "segmentos.csv",
        "subtitulos": outputs_dir / "subtitulos.srt",
        "resumen": outputs_dir / "resumen.md",
        "boletin": outputs_dir / "boletin_email.md",
        "revision_nombres": outputs_dir / "revision_nombres_propios.md",
        "glosario": outputs_dir / "glosario_nombres.txt",
    }


def attach_output_manifest(diagnostic: dict[str, Any], outputs: dict[str, Path]) -> None:
    diagnostic["outputs_generated"] = {name: str(path) for name, path in outputs.items()}


def serialize_output_paths(outputs: dict[str, Path]) -> dict[str, str]:
    return {name: str(path) for name, path in outputs.items()}


def load_diagnostic(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _default_registry() -> dict[str, Any]:
    return {"active_job": None, "jobs": []}


def _pid_is_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_registry(project_root: Path | None = None) -> dict[str, Any]:
    path = registry_path(project_root)
    if not path.exists():
        return _default_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_registry()
    if not isinstance(payload, dict):
        return _default_registry()
    payload.setdefault("active_job", None)
    payload.setdefault("jobs", [])
    active_job = payload.get("active_job")
    if isinstance(active_job, dict) and not _pid_is_running(active_job.get("pid")):
        stale_id = active_job.get("id")
        for job in payload.get("jobs", []):
            if job.get("id") == stale_id and job.get("status") == "running":
                job["status"] = "stale"
                job["finished_at"] = now_iso()
                job["error_message"] = "El proceso previo ya no esta activo."
        payload["active_job"] = None
        _save_registry(payload, project_root)
    return payload


def _save_registry(payload: dict[str, Any], project_root: Path | None = None) -> None:
    path = registry_path(project_root)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_job_registry(project_root: Path | None = None) -> dict[str, Any]:
    return _load_registry(project_root)


def get_active_job(project_root: Path | None = None) -> dict[str, Any] | None:
    payload = _load_registry(project_root)
    active_job = payload.get("active_job")
    return active_job if isinstance(active_job, dict) else None


def _register_job_start(project_root: Path, job_record: dict[str, Any]) -> None:
    payload = _load_registry(project_root)
    active_job = payload.get("active_job")
    if isinstance(active_job, dict):
        audio_name = Path(active_job.get("audio_selected", "")).name or "desconocido"
        raise RuntimeError(f"Ya hay una corrida en ejecucion para `{audio_name}`.")
    payload["active_job"] = job_record
    jobs = [job for job in payload.get("jobs", []) if job.get("id") != job_record["id"]]
    jobs.append(job_record)
    payload["jobs"] = jobs[-50:]
    _save_registry(payload, project_root)


def _register_job_finish(project_root: Path, job_id: str, updates: dict[str, Any]) -> None:
    payload = _load_registry(project_root)
    if isinstance(payload.get("active_job"), dict) and payload["active_job"].get("id") == job_id:
        payload["active_job"] = None
    jobs = payload.get("jobs", [])
    target: dict[str, Any] | None = None
    for job in reversed(jobs):
        if job.get("id") == job_id:
            target = job
            break
    if target is None:
        target = {"id": job_id}
        jobs.append(target)
    target.update(updates)
    payload["jobs"] = jobs[-50:]
    _save_registry(payload, project_root)


def list_audio_candidates(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = project_root or get_project_root()
    ensure_audio_workspace(root)
    candidates = sorted(
        find_audio_candidates(root),
        key=lambda path: (path.stat().st_size, path.stat().st_mtime),
        reverse=True,
    )
    audio_dir = ensure_audio_workspace(root)
    items: list[dict[str, Any]] = []
    for path in candidates:
        output_dir = build_output_dir(root, path)
        source = "audio/" if path.parent.resolve() == audio_dir.resolve() else "raiz"
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "directory": str(path.parent),
                "source": source,
                "size_bytes": path.stat().st_size,
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
                "output_directory": str(output_dir),
            }
        )
    return items


def list_output_runs(project_root: Path | None = None) -> list[dict[str, Any]]:
    root = project_root or get_project_root()
    outputs_root = root / "salidas"
    active_job = get_active_job(root)
    if not outputs_root.exists():
        return []
    items: list[dict[str, Any]] = []
    for output_dir in outputs_root.iterdir():
        if not output_dir.is_dir():
            continue
        outputs = build_output_paths(output_dir)
        diagnostic = load_diagnostic(outputs["diagnostico"])
        status = "unknown"
        if diagnostic:
            if diagnostic.get("validation_issues"):
                status = "completed_with_issues"
            elif diagnostic.get("editorial_only"):
                status = "editorial_only"
            elif diagnostic.get("sample_only"):
                status = "sample_only"
            else:
                status = "completed"
        if active_job and active_job.get("output_directory") == str(output_dir):
            status = "running"
        started_at = diagnostic.get("run_started_at")
        finished_at = diagnostic.get("run_finished_at") or diagnostic.get("last_editorial_regeneration_at")
        audio_selected = diagnostic.get("audio_selected", "")
        items.append(
            {
                "slug": output_dir.name,
                "output_directory": str(output_dir),
                "audio_selected": audio_selected,
                "audio_name": Path(audio_selected).name if audio_selected else output_dir.name,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "diagnostic_path": str(outputs["diagnostico"]),
            }
        )
    items.sort(
        key=lambda item: (
            item.get("finished_at") or "",
            item.get("started_at") or "",
            item.get("slug") or "",
        ),
        reverse=True,
    )
    return items


def load_output_run(output_dir: str | Path) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir).resolve()
    outputs = build_output_paths(resolved_output_dir)
    return {
        "output_directory": str(resolved_output_dir),
        "paths": serialize_output_paths(outputs),
        "diagnostic": load_diagnostic(outputs["diagnostico"]),
        "existing_files": [name for name, path in outputs.items() if path.exists()],
    }


def read_text_output(path: str | Path) -> str:
    resolved_path = Path(path)
    if not resolved_path.exists():
        return ""
    return resolved_path.read_text(encoding="utf-8")


def open_path_in_explorer(path: str | Path) -> bool:
    resolved_path = Path(path).resolve()
    if os.name != "nt" or not resolved_path.exists():
        return False
    os.startfile(str(resolved_path))
    return True


def _unique_upload_path(audio_dir: Path, original_name: str) -> Path:
    safe_name = Path(original_name).name or "audio_subido"
    candidate = audio_dir / safe_name
    if candidate.suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(f"Extension no compatible para audio: {candidate.suffix}")
    if not candidate.exists():
        return candidate
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return candidate.with_name(f"{candidate.stem}_{stamp}{candidate.suffix}")


def save_uploaded_audio(filename: str, data: bytes, project_root: Path | None = None) -> Path:
    audio_dir = ensure_audio_workspace(project_root)
    destination = _unique_upload_path(audio_dir, filename)
    destination.write_bytes(data)
    return destination


def _job_kind(options: RunOptions) -> str:
    if options.editorial_only:
        return "editorial_only"
    if options.sample_only:
        return "sample_only"
    return "transcription"


def regenerate_editorial(options: RunOptions, project_root: Path | None = None, source: str = "cli") -> dict[str, Any]:
    request = RunOptions(**asdict(options))
    request.editorial_only = True
    request.sample_only = False
    return run_job(request, project_root=project_root, source=source)


def run_job(options: RunOptions, project_root: Path | None = None, source: str = "cli") -> dict[str, Any]:
    root = project_root or get_project_root()
    ensure_audio_workspace(root)
    job_id = uuid.uuid4().hex
    selected_audio: Path | None = None
    outputs_dir: Path | None = None
    output_paths: dict[str, Path] = {}
    logger = None
    try:
        selected_audio, all_audio, selected_audio_note = resolve_audio_selection(root, options.audio)
        outputs_dir = build_output_dir(root, selected_audio)
        output_paths = build_output_paths(outputs_dir)
        job_record = {
            "id": job_id,
            "pid": os.getpid(),
            "source": source,
            "status": "running",
            "kind": _job_kind(options),
            "requested_at": now_iso(),
            "started_at": now_iso(),
            "audio_argument": options.audio,
            "audio_selected": str(selected_audio),
            "audio_candidates": [str(path) for path in all_audio],
            "output_directory": str(outputs_dir),
            "options": asdict(options),
        }
        _register_job_start(root, job_record)
        logger = core.setup_logging(outputs_dir)
        logger.info("Iniciando pipeline local de transcripcion.")
        logger.info("Fuente de ejecucion: %s", source)
        logger.info("Audio seleccionado: %s", selected_audio)
        logger.info("Directorio de salida: %s", outputs_dir)

        if options.editorial_only:
            segments = core.load_segments_from_csv(output_paths["segmentos_csv"])
            metadata = core.load_existing_metadata(outputs_dir)
            diagnostic = load_diagnostic(output_paths["diagnostico"])
            metadata["segment_count"] = len(segments)
            metadata["audio_selected"] = str(selected_audio)
            metadata["selection_note"] = selected_audio_note
            reading_blocks = core.build_reading_blocks(segments, protocol_mode=options.protocol)
            output_paths["resumen"].write_text(
                core.generate_editorial_summary_md(
                    reading_blocks=reading_blocks,
                    metadata=metadata,
                    audio_path=selected_audio,
                    selected_audio_note=selected_audio_note,
                ),
                encoding="utf-8",
            )
            output_paths["boletin"].write_text(core.generate_editorial_email_md(reading_blocks), encoding="utf-8")
            output_paths["revision_nombres"].write_text(
                core.generate_revision_nombres_propios_md(core.extract_entity_catalog(reading_blocks)),
                encoding="utf-8",
            )
            issues = core.validate_outputs(
                [output_paths["resumen"], output_paths["boletin"], output_paths["revision_nombres"]]
            )
            diagnostic.update(
                {
                    "audio_selected": str(selected_audio),
                    "audio_candidates": [str(path) for path in all_audio],
                    "selection_note": selected_audio_note,
                    "audio_source_mode": "explicit" if options.audio else "autodetect",
                    "layout_requested": options.layout,
                    "protocol_requested": options.protocol,
                    "segment_count": len(segments),
                    "editorial_only": True,
                    "last_editorial_regeneration_at": now_iso(),
                }
            )
            diagnostic["run_finished_at"] = now_iso()
            attach_output_manifest(diagnostic, output_paths)
            core.save_diagnostic(output_paths["diagnostico"], diagnostic)
            if issues:
                logger.error("La regeneracion editorial termino con archivos faltantes o vacios: %s", issues)
                result = {
                    "ok": False,
                    "status": "completed_with_issues",
                    "error_message": "; ".join(issues),
                }
            else:
                logger.info("Regeneracion editorial completada en %s", outputs_dir)
                result = {"ok": True, "status": "completed"}
            payload = load_diagnostic(output_paths["diagnostico"])
            result.update(
                {
                    "job_id": job_id,
                    "audio_selected": str(selected_audio),
                    "output_directory": str(outputs_dir),
                    "diagnostic": payload,
                    "diagnostic_path": str(output_paths["diagnostico"]),
                    "outputs": serialize_output_paths(output_paths),
                }
            )
            _register_job_finish(
                root,
                job_id,
                {
                    "status": result["status"],
                    "finished_at": now_iso(),
                    "audio_selected": str(selected_audio),
                    "output_directory": str(outputs_dir),
                    "diagnostic_path": str(output_paths["diagnostico"]),
                    "error_message": result.get("error_message", ""),
                },
            )
            return result

        vc_runtime_present = (Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "vcruntime140.dll").exists()
        gpu_setup = core.ensure_gpu_libraries(root, logger) if not options.force_cpu else {"status": "skipped_force_cpu"}
        hotwords = core.read_hotwords(output_paths["glosario"])

        diagnostic = {
            "run_started_at": now_iso(),
            "project_root": str(root),
            "output_directory": str(outputs_dir),
            "audio_selected": str(selected_audio),
            "audio_candidates": [str(path) for path in all_audio],
            "selection_note": selected_audio_note,
            "audio_source_mode": "explicit" if options.audio else "autodetect",
            "execution_source": source,
            "gpu_setup": gpu_setup,
            "vc_runtime_present": vc_runtime_present,
            "python": os.sys.version,
            "sample_only": options.sample_only,
            "force_cpu": options.force_cpu,
            "model_requested": options.model,
            "layout_requested": options.layout,
            "protocol_requested": options.protocol,
        }
        attach_output_manifest(diagnostic, output_paths)
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)

        sample_segments, sample_meta = core.run_transcription(
            audio_path=selected_audio,
            model_name=options.model,
            force_cpu=options.force_cpu,
            sample_seconds=options.sample_seconds,
            outputs_dir=outputs_dir,
            logger=logger,
            hotwords=None,
            min_silence_ms=options.min_silence_ms,
            model_cache_dir=root / ".cache_models",
        )
        sample_meta["model_name"] = options.model
        diagnostic["sample_validation"] = sample_meta
        output_paths["muestra_validacion"].write_text(
            json.dumps(sample_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)

        if options.sample_only:
            sample_blocks = core.build_reading_blocks(sample_segments, protocol_mode=options.protocol)
            sample_text = (
                core.transcript_faithful_text(sample_segments)
                if options.layout == "fiel"
                else core.render_reading_text(sample_blocks, include_timestamps=False)
            )
            output_paths["muestra_transcripcion"].write_text(sample_text + "\n", encoding="utf-8")
            diagnostic["run_finished_at"] = now_iso()
            core.save_diagnostic(output_paths["diagnostico"], diagnostic)
            logger.info("Modo sample-only completado.")
            result = {
                "ok": True,
                "status": "completed",
                "job_id": job_id,
                "audio_selected": str(selected_audio),
                "output_directory": str(outputs_dir),
                "diagnostic": load_diagnostic(output_paths["diagnostico"]),
                "diagnostic_path": str(output_paths["diagnostico"]),
                "outputs": serialize_output_paths(output_paths),
            }
            _register_job_finish(
                root,
                job_id,
                {
                    "status": "completed",
                    "finished_at": now_iso(),
                    "audio_selected": str(selected_audio),
                    "output_directory": str(outputs_dir),
                    "diagnostic_path": str(output_paths["diagnostico"]),
                },
            )
            return result

        full_force_cpu = options.force_cpu or sample_meta["attempt"]["device"] == "cpu"
        full_segments, full_meta = core.run_transcription(
            audio_path=selected_audio,
            model_name=options.model,
            force_cpu=full_force_cpu,
            sample_seconds=None,
            outputs_dir=outputs_dir,
            logger=logger,
            hotwords=hotwords,
            min_silence_ms=options.min_silence_ms,
            model_cache_dir=root / ".cache_models",
        )
        full_meta["model_name"] = options.model
        diagnostic["full_run"] = full_meta
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)

        reading_blocks = core.build_reading_blocks(full_segments, protocol_mode=options.protocol)
        faithful_text = core.transcript_faithful_text(full_segments)
        legible_text = core.render_reading_text(reading_blocks, include_timestamps=False)
        timestamps_text = core.render_reading_text(reading_blocks, include_timestamps=True)
        primary_text = faithful_text if options.layout == "fiel" else legible_text

        output_paths["transcripcion"].write_text(primary_text + "\n", encoding="utf-8")
        output_paths["transcripcion_fiel"].write_text(faithful_text + "\n", encoding="utf-8")
        output_paths["transcripcion_con_timestamps"].write_text(timestamps_text + "\n", encoding="utf-8")
        core.write_segments_csv(full_segments, output_paths["segmentos_csv"])
        core.write_srt(full_segments, output_paths["subtitulos"])
        core.build_glossary(full_segments, output_paths["glosario"])

        refresh_hotwords = core.read_hotwords(output_paths["glosario"])
        if refresh_hotwords and not hotwords:
            logger.info("Se genero glosario_nombres.txt para reforzar hotwords en futuras corridas.")

        output_paths["resumen"].write_text(
            core.generate_editorial_summary_md(
                reading_blocks=reading_blocks,
                metadata=full_meta,
                audio_path=selected_audio,
                selected_audio_note=selected_audio_note,
            ),
            encoding="utf-8",
        )
        output_paths["boletin"].write_text(core.generate_editorial_email_md(reading_blocks), encoding="utf-8")
        output_paths["revision_nombres"].write_text(
            core.generate_revision_nombres_propios_md(core.extract_entity_catalog(reading_blocks)),
            encoding="utf-8",
        )

        required_outputs = [
            output_paths["transcripcion"],
            output_paths["transcripcion_fiel"],
            output_paths["transcripcion_con_timestamps"],
            output_paths["segmentos_csv"],
            output_paths["subtitulos"],
            output_paths["resumen"],
            output_paths["boletin"],
            output_paths["revision_nombres"],
            output_paths["glosario"],
        ]
        issues = core.validate_outputs(required_outputs)
        diagnostic["validation_issues"] = issues
        diagnostic["run_finished_at"] = now_iso()
        attach_output_manifest(diagnostic, output_paths)
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)

        result = {
            "ok": not issues,
            "status": "completed" if not issues else "completed_with_issues",
            "job_id": job_id,
            "audio_selected": str(selected_audio),
            "output_directory": str(outputs_dir),
            "diagnostic": load_diagnostic(output_paths["diagnostico"]),
            "diagnostic_path": str(output_paths["diagnostico"]),
            "outputs": serialize_output_paths(output_paths),
        }
        if issues:
            result["error_message"] = "; ".join(issues)
            logger.error("La corrida termino con archivos faltantes o vacios: %s", issues)
        else:
            logger.info("Pipeline completo. Archivos generados en %s", outputs_dir)
        _register_job_finish(
            root,
            job_id,
            {
                "status": result["status"],
                "finished_at": now_iso(),
                "audio_selected": str(selected_audio),
                "output_directory": str(outputs_dir),
                "diagnostic_path": str(output_paths["diagnostico"]),
                "error_message": result.get("error_message", ""),
            },
        )
        return result
    except Exception as exc:
        if logger:
            logger.exception("La corrida termino con error.")
        result = {
            "ok": False,
            "status": "error",
            "job_id": job_id,
            "audio_selected": str(selected_audio) if selected_audio else "",
            "output_directory": str(outputs_dir) if outputs_dir else "",
            "diagnostic": load_diagnostic(output_paths["diagnostico"]) if output_paths else {},
            "diagnostic_path": str(output_paths["diagnostico"]) if output_paths else "",
            "outputs": serialize_output_paths(output_paths) if output_paths else {},
            "error_message": str(exc),
        }
        if outputs_dir:
            _register_job_finish(
                root,
                job_id,
                {
                    "status": "error",
                    "finished_at": now_iso(),
                    "audio_selected": str(selected_audio) if selected_audio else "",
                    "output_directory": str(outputs_dir),
                    "diagnostic_path": str(output_paths["diagnostico"]) if output_paths else "",
                    "error_message": str(exc),
                },
            )
        return result
