from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from .service import (
    RunOptions,
    ensure_audio_workspace,
    get_active_job,
    get_project_root,
    get_job_registry,
    list_audio_candidates,
    list_output_runs,
    load_output_run,
    open_path_in_explorer,
    read_text_output,
    run_job,
    save_uploaded_audio,
)


class WebJobRunner:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sirena-web")
        self.futures: list[Future] = []

    def prune(self) -> None:
        self.futures = [future for future in self.futures if not future.done()]

    def submit(self, options: RunOptions) -> None:
        self.prune()
        if get_active_job(self.project_root):
            raise RuntimeError("Ya hay una corrida activa. Espera a que termine antes de lanzar otra.")
        self.futures.append(self.executor.submit(run_job, options, self.project_root, "web"))


@st.cache_resource
def get_runner(project_root_str: str) -> WebJobRunner:
    return WebJobRunner(Path(project_root_str))


def _format_audio_label(item: dict) -> str:
    size_mb = item["size_bytes"] / (1024 * 1024)
    return f"{item['name']} | {item['source']} | {size_mb:.1f} MB"


def _format_run_label(item: dict) -> str:
    finished = item.get("finished_at") or item.get("started_at") or "sin fecha"
    return f"{item['audio_name']} | {item['status']} | {finished}"


def _preview_block(title: str, path: str, *, height: int = 280) -> None:
    file_path = Path(path)
    if not file_path.exists():
        st.info(f"No existe `{file_path.name}` para esta corrida.")
        return
    content = read_text_output(file_path)
    st.caption(str(file_path))
    st.download_button(
        label=f"Descargar {file_path.name}",
        data=content,
        file_name=file_path.name,
        mime="text/plain",
        key=f"download-{title}-{file_path.name}",
    )
    st.text_area(title, content, height=height, key=f"text-{title}-{file_path.name}")


def render_app() -> None:
    project_root = get_project_root()
    audio_dir = ensure_audio_workspace(project_root)
    runner = get_runner(str(project_root))

    st.set_page_config(page_title="Sirena", page_icon="S", layout="wide")
    st.title("Sirena")
    st.caption("App web local para transcripcion, resumen editorial y trabajo combinado con agentes.")

    sidebar = st.sidebar
    sidebar.subheader("Estado")
    active_job = get_active_job(project_root)
    if active_job:
        sidebar.warning(
            f"Hay una corrida activa:\n\n`{Path(active_job.get('audio_selected', '')).name or 'desconocido'}`\n\n"
            f"Tipo: `{active_job.get('kind', 'transcription')}`"
        )
    else:
        sidebar.success("No hay corridas activas.")
    if sidebar.button("Refrescar panel"):
        st.rerun()

    uploaded_audio = st.file_uploader(
        "Sube un audio nuevo",
        type=[ext.lstrip(".") for ext in sorted({".mp3", ".mpeg", ".m4a", ".mp4", ".wav", ".flac", ".ogg", ".aac", ".webm"})],
        help="El archivo se guardara en la carpeta ./audio/ para que tambien quede disponible por CLI y por agentes.",
    )
    if uploaded_audio is not None:
        if st.button("Guardar audio en ./audio/", disabled=active_job is not None):
            saved_path = save_uploaded_audio(uploaded_audio.name, uploaded_audio.getvalue(), project_root)
            st.success(f"Audio guardado en {saved_path}")
            st.rerun()

    st.markdown(f"**Carpeta de trabajo de audios:** `{audio_dir}`")

    audio_candidates = list_audio_candidates(project_root)
    audio_map = {_format_audio_label(item): item for item in audio_candidates}

    st.subheader("Correr pipeline")
    if not audio_map:
        st.info("No hay audios detectados. Puedes subir uno aqui o dejarlo en la raiz del proyecto o en ./audio/.")
    else:
        selected_label = st.selectbox("Selecciona un audio", options=list(audio_map.keys()))
        selected_audio = audio_map[selected_label]

        with st.expander("Opciones avanzadas", expanded=False):
            model = st.selectbox("Modelo", options=["turbo", "large-v3"], index=0)
            force_cpu = st.checkbox("Forzar CPU", value=False)
            layout = st.selectbox("Layout", options=["legible", "fiel", "ambas"], index=0)
            protocol = st.selectbox("Protocolo", options=["compact", "keep", "separate"], index=0)
            sample_seconds = st.number_input("Segundos de muestra", min_value=60, max_value=3600, value=480, step=30)
            min_silence_ms = st.number_input("Minimo de silencio VAD (ms)", min_value=100, max_value=3000, value=500, step=100)

        base_options = RunOptions(
            audio=selected_audio["path"],
            force_cpu=force_cpu,
            model=model,
            layout=layout,
            protocol=protocol,
            sample_seconds=int(sample_seconds),
            min_silence_ms=int(min_silence_ms),
        )

        controls = st.columns(3)
        if controls[0].button("Transcripcion completa", disabled=active_job is not None, use_container_width=True):
            try:
                runner.submit(base_options)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.success("Corrida enviada. Usa el boton de refrescar para ver el estado.")
        if controls[1].button("Validar muestra", disabled=active_job is not None, use_container_width=True):
            sample_options = RunOptions(**asdict(base_options))
            sample_options.sample_only = True
            try:
                runner.submit(sample_options)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.success("Validacion de muestra enviada.")
        if controls[2].button("Regenerar editorial", disabled=active_job is not None, use_container_width=True):
            editorial_options = RunOptions(**asdict(base_options))
            editorial_options.editorial_only = True
            editorial_options.sample_only = False
            try:
                runner.submit(editorial_options)
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.success("Regeneracion editorial enviada.")

        st.caption(
            "La app y el CLI comparten la misma logica. Puedes seguir usando `run_transcripcion.bat --audio ...` desde Codex."
        )

    st.subheader("Historial de corridas")
    registry = get_job_registry(project_root)
    recent_jobs = registry.get("jobs", [])[-5:]
    if recent_jobs:
        with st.expander("Ultimos jobs del registro", expanded=False):
            for job in reversed(recent_jobs):
                st.write(
                    f"- `{job.get('status', 'unknown')}` | `{job.get('kind', 'transcription')}` | "
                    f"`{Path(job.get('audio_selected', '')).name or job.get('audio_argument', 'sin audio')}`"
                )

    output_runs = list_output_runs(project_root)
    if not output_runs:
        st.info("Todavia no hay corridas disponibles en `salidas/`.")
        return

    run_map = {_format_run_label(item): item for item in output_runs}
    selected_run_label = st.selectbox("Selecciona una corrida", options=list(run_map.keys()))
    selected_run = run_map[selected_run_label]
    run_details = load_output_run(selected_run["output_directory"])

    action_cols = st.columns(2)
    if action_cols[0].button("Abrir carpeta del resultado", use_container_width=True):
        if open_path_in_explorer(run_details["output_directory"]):
            st.success("Se abrio la carpeta en el explorador.")
        else:
            st.error("No se pudo abrir la carpeta desde esta plataforma.")
    if action_cols[1].button("Abrir carpeta de audios", use_container_width=True):
        if open_path_in_explorer(audio_dir):
            st.success("Se abrio la carpeta de audios.")
        else:
            st.error("No se pudo abrir la carpeta desde esta plataforma.")

    st.json(run_details["diagnostic"])

    tabs = st.tabs(["Resumen", "Boletin", "Transcripcion", "Timestamps", "Diagnostico y archivos"])
    with tabs[0]:
        _preview_block("Resumen", run_details["paths"]["resumen"])
    with tabs[1]:
        _preview_block("Boletin", run_details["paths"]["boletin"])
    with tabs[2]:
        _preview_block("Transcripcion", run_details["paths"]["transcripcion"], height=360)
    with tabs[3]:
        _preview_block("Transcripcion con timestamps", run_details["paths"]["transcripcion_con_timestamps"], height=360)
    with tabs[4]:
        st.write("Archivos detectados:")
        for name, path in run_details["paths"].items():
            exists = "si" if Path(path).exists() else "no"
            st.write(f"- `{name}` -> `{path}` | existe: `{exists}`")
