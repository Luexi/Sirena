from __future__ import annotations

import argparse
from .service import RunOptions, run_job


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


def main() -> int:
    args = parse_args()
    result = run_job(
        RunOptions(
            audio=args.audio,
            sample_only=args.sample_only,
            editorial_only=args.editorial_only,
            force_cpu=args.force_cpu,
            model=args.model,
            layout=args.layout,
            protocol=args.protocol,
            sample_seconds=args.sample_seconds,
            min_silence_ms=args.min_silence_ms,
        ),
        source="cli",
    )
    if not result["ok"]:
        error_message = result.get("error_message")
        if error_message:
            print(error_message)
        return 1
    return 0
