from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import core
from .paths import build_output_dir, project_root_from, resolve_audio_selection


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sirena: pipeline local para transcribir reuniones en espanol.")
    parser.add_argument("--audio", help="Ruta al archivo de audio a procesar. Si no se indica, se usa autodeteccion.")
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


def attach_output_manifest(diagnostic: dict, outputs: dict[str, Path]) -> None:
    diagnostic["outputs_generated"] = {name: str(path) for name, path in outputs.items()}


def main() -> int:
    args = parse_args()
    project_root = project_root_from(__file__)
    model_cache_dir = project_root / ".cache_models"
    selected_audio, all_audio, selected_audio_note = resolve_audio_selection(project_root, args.audio)
    outputs_dir = build_output_dir(project_root, selected_audio)
    output_paths = build_output_paths(outputs_dir)
    logger = core.setup_logging(outputs_dir)
    logger.info("Iniciando pipeline local de transcripcion.")
    logger.info("Audio seleccionado: %s", selected_audio)
    logger.info("Directorio de salida: %s", outputs_dir)

    if args.editorial_only:
        segments = core.load_segments_from_csv(output_paths["segmentos_csv"])
        metadata = core.load_existing_metadata(outputs_dir)
        diagnostic: dict = {}
        if output_paths["diagnostico"].exists():
            try:
                diagnostic = json.loads(output_paths["diagnostico"].read_text(encoding="utf-8"))
            except Exception:
                diagnostic = {}
        metadata["segment_count"] = len(segments)
        metadata["audio_selected"] = str(selected_audio)
        metadata["selection_note"] = selected_audio_note
        reading_blocks = core.build_reading_blocks(segments, protocol_mode=args.protocol)
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
                "audio_source_mode": "explicit" if args.audio else "autodetect",
                "layout_requested": args.layout,
                "protocol_requested": args.protocol,
                "segment_count": len(segments),
                "editorial_only": True,
                "last_editorial_regeneration_at": datetime.now().isoformat(),
            }
        )
        diagnostic["run_finished_at"] = datetime.now().isoformat()
        attach_output_manifest(diagnostic, output_paths)
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)
        if issues:
            logger.error("La regeneracion editorial termino con archivos faltantes o vacios: %s", issues)
            return 1
        logger.info("Regeneracion editorial completada en %s", outputs_dir)
        return 0

    vc_runtime_present = (Path(os.environ.get("WINDIR", "C:\\Windows")) / "System32" / "vcruntime140.dll").exists()
    gpu_setup = core.ensure_gpu_libraries(project_root, logger) if not args.force_cpu else {"status": "skipped_force_cpu"}
    hotwords = core.read_hotwords(output_paths["glosario"])

    diagnostic = {
        "run_started_at": datetime.now().isoformat(),
        "project_root": str(project_root),
        "output_directory": str(outputs_dir),
        "audio_selected": str(selected_audio),
        "audio_candidates": [str(path) for path in all_audio],
        "selection_note": selected_audio_note,
        "audio_source_mode": "explicit" if args.audio else "autodetect",
        "gpu_setup": gpu_setup,
        "vc_runtime_present": vc_runtime_present,
        "python": sys.version,
        "sample_only": args.sample_only,
        "force_cpu": args.force_cpu,
        "model_requested": args.model,
        "layout_requested": args.layout,
        "protocol_requested": args.protocol,
    }
    attach_output_manifest(diagnostic, output_paths)
    core.save_diagnostic(output_paths["diagnostico"], diagnostic)

    sample_segments, sample_meta = core.run_transcription(
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
    output_paths["muestra_validacion"].write_text(
        json.dumps(sample_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    core.save_diagnostic(output_paths["diagnostico"], diagnostic)

    if args.sample_only:
        sample_blocks = core.build_reading_blocks(sample_segments, protocol_mode=args.protocol)
        sample_text = (
            core.transcript_faithful_text(sample_segments)
            if args.layout == "fiel"
            else core.render_reading_text(sample_blocks, include_timestamps=False)
        )
        output_paths["muestra_transcripcion"].write_text(sample_text + "\n", encoding="utf-8")
        diagnostic["run_finished_at"] = datetime.now().isoformat()
        core.save_diagnostic(output_paths["diagnostico"], diagnostic)
        logger.info("Modo sample-only completado.")
        return 0

    full_force_cpu = args.force_cpu or sample_meta["attempt"]["device"] == "cpu"
    full_segments, full_meta = core.run_transcription(
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
    core.save_diagnostic(output_paths["diagnostico"], diagnostic)

    reading_blocks = core.build_reading_blocks(full_segments, protocol_mode=args.protocol)
    faithful_text = core.transcript_faithful_text(full_segments)
    legible_text = core.render_reading_text(reading_blocks, include_timestamps=False)
    timestamps_text = core.render_reading_text(reading_blocks, include_timestamps=True)
    primary_text = faithful_text if args.layout == "fiel" else legible_text

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
    diagnostic["run_finished_at"] = datetime.now().isoformat()
    attach_output_manifest(diagnostic, output_paths)
    core.save_diagnostic(output_paths["diagnostico"], diagnostic)

    if issues:
        logger.error("La corrida termino con archivos faltantes o vacios: %s", issues)
        return 1

    logger.info("Pipeline completo. Archivos generados en %s", outputs_dir)
    return 0
