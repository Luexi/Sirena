# Output Contract

Cada corrida de Sirena produce una carpeta aislada en `salidas/<audio-slug>/`.

## Artefactos principales

- `transcripcion.txt`: salida principal legible.
- `transcripcion_fiel.txt`: transcripcion mas cercana al orden y segmentacion del modelo.
- `transcripcion_con_timestamps.txt`: salida legible con marcas de tiempo.
- `segmentos.csv`: dataset de segmentos reutilizable para regenerar productos editoriales.
- `subtitulos.srt`: subtitulos listos para reproductor o revision externa.

## Artefactos editoriales

- `resumen.md`: resumen de alto nivel con temas, nombres e indicios de pendientes.
- `boletin_email.md`: formato sugerido para correo, boletin o actualizacion interna.
- `revision_nombres_propios.md`: revision de entidades detectadas.
- `glosario_nombres.txt`: hotwords persistentes para retrabajar el mismo audio.

## Artefactos operativos

- `diagnostico.json`: manifest de la corrida, con audio usado, modelo, device, idioma, flags y rutas.
- `ejecucion.log`: traza operativa.
- `muestra_validacion.json`: metadata de la muestra inicial.
- `muestra_transcripcion.txt`: solo existe en modo `--sample-only`.

## Estado local de la app

- `.sirena_state/jobs.json`: registro local ligero de jobs para la app web y para evitar corridas concurrentes.
- `audio/`: carpeta de trabajo recomendada para audios subidos desde la interfaz web.

## Insumos recomendados para agentes

- Primera lectura: `resumen.md`
- Version reenviable: `boletin_email.md`
- Verificacion puntual: `transcripcion_con_timestamps.txt`
- Reproceso estructurado: `segmentos.csv`
