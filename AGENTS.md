# AGENTS

Este repositorio esta preparado para que agentes de codigo y resumen trabajen sobre transcripciones sin exponer datos sensibles.

## Principios

- No versionar audios reales, transcripciones, caches ni logs.
- Tratar cualquier contenido de reuniones como material sensible.
- Preservar `run_transcripcion.bat` como entrypoint estable para uso diario en Windows.
- Usar `audio/` como bandeja oficial de entrada para audios nuevos.

## Mapa del repo

- `pipeline_transcripcion.py`: wrapper de compatibilidad que carga el paquete nuevo.
- `src/sirena/cli.py`: CLI y orquestacion principal.
- `src/sirena/service.py`: capa compartida entre CLI, app web y futuros agentes.
- `src/sirena/core.py`: logica de transcripcion, render, resumen y exportacion.
- `src/sirena/paths.py`: resolucion de audio y rutas de salida por corrida.
- `src/sirena/webapp.py`: interfaz web local en Streamlit.
- `sirena_web.py`: launcher de la app web local.
- `docs/output-contract.md`: contrato de artefactos generados.

## Comandos utiles

```bat
run_transcripcion.bat --help
run_transcripcion.bat --audio .\audio\audio_nuevo.mpeg
run_transcripcion.bat --audio .\audio\audio_nuevo.mpeg --sample-only
run_transcripcion.bat --audio .\audio\audio_nuevo.mpeg --editorial-only
run_sirena_web.bat
```

## Convenciones

- Cada audio debe escribir en `salidas/<audio-slug>/`.
- `audio/` es la carpeta oficial para audios pendientes o fuente original local.
- La app web guarda uploads en `audio/`.
- La raiz del repo debe quedar reservada para codigo, documentacion y launchers.
- `diagnostico.json` es la fuente de verdad de la corrida.
- `segmentos.csv` es el artefacto base para regenerar productos editoriales.
- `glosario_nombres.txt` es por audio, no global.
- El registro liviano de jobs vive en `.sirena_state/`.

## Higiene de entradas

- Si el usuario pide transcribir un audio que esta en la raiz, crear `audio/` si no existe y mover solo ese archivo a `audio/` antes de ejecutar el CLI.
- No mover en bloque otros audios de la raiz; la limpieza automatica se limita al audio solicitado por el usuario.
- Nunca sobrescribir un archivo existente en `audio/`. Si ya existe un archivo con el mismo nombre, detenerse y preguntar al usuario.
- Despues de mover el audio solicitado, ejecutar la transcripcion con la ruta nueva:

```bat
run_transcripcion.bat --audio .\audio\nombre-del-audio.ext
```

- `salidas/<audio-slug>/` sigue siendo la carpeta oficial para resultados por corrida.
- Los audios historicos que sigan en la raiz pueden moverse manualmente a `audio/` cuando ya no haya dudas, sin cambiar sus salidas existentes en `salidas/`.

## Ruta recomendada para agentes

- Para ejecutar transcripciones desde Codex, seguir usando el CLI con `run_transcripcion.bat`.
- Si el audio solicitado ya esta en `audio/`, transcribirlo desde ahi sin moverlo.
- Si el audio solicitado esta en la raiz, moverlo primero segun la regla de higiene de entradas y usar la ruta `.\audio\<archivo>`.
- La app web no reemplaza esa ruta; solo comparte la misma capa de servicio.

## Si un agente va a resumir

- Priorizar `resumen.md` y `boletin_email.md` para lectura rapida.
- Si hay dudas de fidelidad, revisar `transcripcion_fiel.txt` y `transcripcion_con_timestamps.txt`.
- Si aparecen nombres dudosos, consultar `revision_nombres_propios.md`.
