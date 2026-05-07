# Sirena

Sirena es un pipeline local para transcribir reuniones largas en espanol y dejarlas listas para revision humana, reenvio como boletin o resumen posterior con agentes como Codex o Gemini.

El proyecto esta pensado para uso personal y para operar en Windows sin depender de servicios externos para la transcripcion. La prioridad es privacidad, reproducibilidad y velocidad de uso diario.

## Privacidad

- No subas audios reales, transcripciones ni salidas a GitHub.
- El repositorio esta preparado para versionar codigo y documentacion, no datos sensibles.
- La carpeta `salidas/` y los archivos de audio quedan ignorados por `.gitignore`.

## Estructura

```text
.
|-- pipeline_transcripcion.py
|-- run_transcripcion.bat
|-- requirements.txt
|-- README.md
|-- AGENTS.md
|-- docs/
|   `-- output-contract.md
`-- src/
    `-- sirena/
        |-- __init__.py
        |-- __main__.py
        |-- cli.py
        |-- core.py
        `-- paths.py
```

## Instalacion

Sirena usa Python 3.11.

```bat
run_transcripcion.bat --help
```

El `.bat` crea `.venv/`, actualiza `pip`, instala dependencias y ejecuta el pipeline.

## Uso rapido

### Transcribir un audio especifico

```bat
run_transcripcion.bat --audio .\audio_nuevo.mpeg
```

### Validar solo una muestra

```bat
run_transcripcion.bat --audio .\audio_nuevo.mpeg --sample-only
```

### Forzar CPU

```bat
run_transcripcion.bat --audio .\audio_nuevo.mpeg --force-cpu
```

### Regenerar resumen editorial sin retranscribir

```bat
run_transcripcion.bat --audio .\audio_nuevo.mpeg --editorial-only
```

### Compatibilidad con el flujo anterior

Si no pasas `--audio`, Sirena intenta detectar automaticamente un archivo compatible en `.\audio\` y luego en la raiz del proyecto.

## Salidas por audio

Cada audio se procesa en su propia carpeta:

```text
salidas/<audio-slug>/
```

Por ejemplo:

```text
salidas/audio-nuevo/
```

Archivos generados:

- `transcripcion.txt`: version principal de lectura.
- `transcripcion_fiel.txt`: version cercana a la segmentacion original.
- `transcripcion_con_timestamps.txt`: lectura con marcas de tiempo compactas.
- `segmentos.csv`: segmentos crudos para reprocesamiento o analisis.
- `subtitulos.srt`: subtitulos exportables.
- `resumen.md`: resumen editorial para consumo rapido.
- `boletin_email.md`: borrador de boletin o actualizacion por correo.
- `revision_nombres_propios.md`: catalogo de nombres, instituciones y siglas para correccion manual.
- `glosario_nombres.txt`: hotwords por audio para futuras corridas del mismo caso.
- `muestra_validacion.json`: metadata de la corrida de validacion.
- `muestra_transcripcion.txt`: salida de la muestra si usas `--sample-only`.
- `diagnostico.json`: manifest de la corrida, parametros, dispositivo usado y rutas generadas.
- `ejecucion.log`: log detallado de esa corrida.

## Flujo recomendado

1. Corre una primera vez con `--audio`.
2. Revisa `revision_nombres_propios.md` y `glosario_nombres.txt`.
3. Si necesitas una segunda pasada del mismo audio, vuelve a ejecutar el comando para reutilizar hotwords.
4. Usa `resumen.md` o `boletin_email.md` como base para reenviar o alimentar a otros agentes.

## GPU y fallback

- El pipeline intenta usar GPU NVIDIA con librerias locales en `.local_gpu_libs/`.
- Si la GPU falla por DLLs o compatibilidad, cambia automaticamente a CPU.
- El resultado real de la corrida queda registrado en `diagnostico.json`.

## Preparacion para GitHub

El remoto objetivo es:

```text
https://github.com/Luexi/Sirena
```

Comandos esperados:

```bat
git remote add origin https://github.com/Luexi/Sirena.git
git add .
git commit -m "Initial Sirena project structure"
git push -u origin main
```

Antes de empujar, valida que `git status` no incluya audios, caches ni contenido de `salidas/`.
