import customtkinter as ctk
from tkinter import filedialog, messagebox
import os
import queue
import threading
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image

from controller.simulation_mgr import OFDMSimulationManager

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Simulador LTE MIMO-OFDM")
        self.geometry("1120x820")

        self.manager = OFDMSimulationManager()
        self.worker_queue = queue.Queue()
        self.worker_thread = None
        self.worker_task = None
        self.worker_success_handler = None
        
        self.selected_image_path = None

        self.default_bw_idx = 4
        self.default_profile_idx = 1
        self.default_num_paths = 1
        self.mod_map = {"QPSK": 1, "16-QAM": 2, "64-QAM": 3}
        self.rank_mode_map = {"Rank 2": "rank2", "Rank máximo": "max"}

        self.setup_ui()

    def setup_ui(self):
        """Disposición de elementos visuales (Grid Layout)"""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(12, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LTE MIMO SIM", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.lbl_link = ctk.CTkLabel(self.sidebar_frame, text="Parámetros:", anchor="w")
        self.lbl_link.grid(row=1, column=0, padx=20, pady=(20, 0))

        self.option_mod = ctk.CTkOptionMenu(self.sidebar_frame, values=list(self.mod_map.keys()))
        self.option_mod.grid(row=2, column=0, padx=20, pady=5)
        self.option_mod.set("16-QAM")

        self.lbl_snr = ctk.CTkLabel(self.sidebar_frame, text="SNR: 15 dB")
        self.lbl_snr.grid(row=3, column=0, padx=20, pady=(18,0))
        self.slider_snr = ctk.CTkSlider(self.sidebar_frame, from_=0, to=30, number_of_steps=30, command=self.update_snr_label)
        self.slider_snr.grid(row=4, column=0, padx=20, pady=5)
        self.slider_snr.set(15)

        self.lbl_rank = ctk.CTkLabel(self.sidebar_frame, text="Rank comparación:", anchor="w")
        self.lbl_rank.grid(row=5, column=0, padx=20, pady=(18, 0))

        self.option_rank = ctk.CTkOptionMenu(self.sidebar_frame, values=list(self.rank_mode_map.keys()))
        self.option_rank.grid(row=6, column=0, padx=20, pady=5)
        self.option_rank.set("Rank 2")

        self.lbl_source = ctk.CTkLabel(self.sidebar_frame, text="Fuente de Datos:", anchor="w")
        self.lbl_source.grid(row=7, column=0, padx=20, pady=(24, 0))

        self.btn_select_file = ctk.CTkButton(self.sidebar_frame, text="Seleccionar Imagen...", 
                                             fg_color="#4B4B4B", hover_color="#5B5B5B", 
                                             command=self.select_file)
        self.btn_select_file.grid(row=8, column=0, padx=20, pady=5)

        self.lbl_filename = ctk.CTkLabel(self.sidebar_frame, text="[Ningún archivo]", font=("Arial", 11), text_color="gray")
        self.lbl_filename.grid(row=9, column=0, padx=20, pady=0)

        self.btn_run_mimo = ctk.CTkButton(self.sidebar_frame, text="PRUEBA MULTIANTENA",
                                          fg_color="#1f538d", hover_color="#14375e",
                                          command=self.action_plot_mimo)
        self.btn_run_mimo.grid(row=10, column=0, padx=20, pady=(28, 10))

        self.btn_run_ber = ctk.CTkButton(
            self.sidebar_frame,
            text="CURVAS BER",
            fg_color="transparent",
            border_width=2,
            command=self.action_plot_mimo_ber,
        )
        self.btn_run_ber.grid(row=11, column=0, padx=20, pady=8)


        self.tabview = ctk.CTkTabview(self, width=800)
        self.tabview.grid(row=0, column=1, padx=(20, 20), pady=(20, 20), sticky="nsew")
        
        self.tab_img = self.tabview.add("Imagen Original")
        self.tab_multi = self.tabview.add("Prueba Multiantena")
        self.tab_ber = self.tabview.add("BER MIMO")

        self.tab_img.grid_columnconfigure(0, weight=1)

        self.lbl_original_title = ctk.CTkLabel(self.tab_img, text="Imagen Original", font=("Arial", 16, "bold"))
        self.lbl_original_title.grid(row=0, column=0, pady=10)
        self.lbl_original_img = ctk.CTkLabel(
            self.tab_img,
            text="\n\n[Seleccione una imagen\npara comenzar]",
            font=("Arial", 14),
            text_color="gray",
        )
        self.lbl_original_img.grid(row=1, column=0, pady=8)

        self.lbl_status = ctk.CTkLabel(
            self.tab_img,
            text="Estado: selecciona imagen para la prueba visual o genera curvas BER/throughput",
            font=("Courier", 13),
            text_color="yellow",
            justify="center",
            wraplength=760,
        )
        self.lbl_status.grid(row=2, column=0, pady=20)

    def _has_running_worker(self):
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _set_busy_state(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (
            self.option_mod,
            self.option_rank,
            self.slider_snr,
            self.btn_select_file,
            self.btn_run_mimo,
            self.btn_run_ber,
        ):
            widget.configure(state=state)

    def _start_worker(self, task_name, status_text, target, args, on_success):
        if self._has_running_worker():
            self.lbl_status.configure(
                text="Ya hay una simulación en curso. Espera a que termine.",
                text_color="yellow",
            )
            return

        self._set_busy_state(True)
        self.worker_task = task_name
        self.worker_success_handler = on_success
        self.lbl_status.configure(text=status_text, text_color="yellow")

        def worker_target():
            try:
                result = target(*args)
                self.worker_queue.put(("success", task_name, result))
            except Exception as exc:
                self.worker_queue.put(("error", task_name, str(exc)))

        self.worker_thread = threading.Thread(
            target=worker_target,
            name=f"ofdm-{task_name}-worker",
            daemon=True,
        )
        self.worker_thread.start()
        self.after(100, self._poll_worker_queue)

    def _poll_worker_queue(self):
        while True:
            try:
                status, task_name, payload = self.worker_queue.get_nowait()
            except queue.Empty:
                if self._has_running_worker():
                    self.after(100, self._poll_worker_queue)
                else:
                    self._finish_worker()
                return

            if task_name == self.worker_task:
                break

        handler = self.worker_success_handler
        self._finish_worker()

        if status == "error":
            self.lbl_status.configure(text=f"Error: {payload}", text_color="red")
            messagebox.showerror("Error", payload)
            return

        try:
            handler(payload)
        except Exception as exc:
            self.lbl_status.configure(text="Error actualizando la interfaz", text_color="red")
            messagebox.showerror("Error", str(exc))

    def _finish_worker(self):
        self._set_busy_state(False)
        self.worker_thread = None
        self.worker_task = None
        self.worker_success_handler = None

    def update_snr_label(self, value):
        self.lbl_snr.configure(text=f"SNR: {int(value)} dB")

    def select_file(self):
        """Abre cuadro de diálogo para seleccionar imagen"""
        file_path = filedialog.askopenfilename(
            title="Seleccionar Imagen",
            filetypes=[("Archivos de Imagen", "*.jpg *.jpeg *.png *.bmp")]
        )
        
        if file_path:
            self.selected_image_path = file_path
            filename = os.path.basename(file_path)
            if len(filename) > 25:
                filename = filename[:22] + "..."
            self.lbl_filename.configure(text=filename, text_color="#30D760")
            self._show_original_preview(file_path)
            self.lbl_status.configure(
                text="Imagen cargada. Ejecuta PRUEBA MULTIANTENA o CURVAS BER.",
                text_color="white",
            )
            self.tabview.set("Imagen Original")

    def _show_original_preview(self, file_path):
        try:
            img_pil = Image.open(file_path).convert("L").resize((360, 360), Image.Resampling.NEAREST)
        except Exception as exc:
            messagebox.showerror("Error de Imagen", f"No se pudo cargar la imagen:\n{exc}")
            return

        self.tk_img_original = ctk.CTkImage(light_image=img_pil, dark_image=img_pil, size=(360, 360))
        self.lbl_original_img.configure(image=self.tk_img_original, text="")

    def action_plot_mimo(self):
        """Genera y muestra la comparacion visual MIMO con la imagen."""
        if not self.selected_image_path:
            messagebox.showwarning("Falta Imagen", "Selecciona una imagen para la prueba multiantena.")
            return

        bw_idx = self.default_bw_idx
        prof_idx = self.default_profile_idx
        mod_idx = self.mod_map[self.option_mod.get()]
        rank_mode = self.rank_mode_map[self.option_rank.get()]
        paths = self.default_num_paths

        self._start_worker(
            "mimo",
            "Generando prueba multiantena...",
            self.manager.calculate_mimo_visual_comparison,
            (self.selected_image_path, bw_idx, prof_idx, mod_idx, int(self.slider_snr.get()), paths, rank_mode),
            self._show_mimo_result,
        )

    def _show_mimo_result(self, result):
        self.embed_mimo_visual_grid(self.tab_multi, result)
        self.lbl_status.configure(text=result["summary"], text_color="white")
        self.tabview.set("Prueba Multiantena")

    def action_plot_mimo_ber(self):
        """Genera las curvas BER multiantena con bits aleatorios."""
        bw_idx = self.default_bw_idx
        prof_idx = self.default_profile_idx
        mod_idx = self.mod_map[self.option_mod.get()]
        rank_mode = self.rank_mode_map[self.option_rank.get()]
        paths = self.default_num_paths

        self._start_worker(
            "mimo-ber",
            "Calculando curvas BER multiantena...",
            self.manager.calculate_mimo_comparison,
            (self.selected_image_path, bw_idx, prof_idx, mod_idx, paths, rank_mode),
            self._show_mimo_ber_result,
        )

    def _show_mimo_ber_result(self, result):
        self.embed_mimo_ber_plot(self.tab_ber, result)
        self.lbl_status.configure(text=result["summary"], text_color="white")
        self.tabview.set("BER MIMO")

    def embed_mimo_visual_grid(self, parent_frame, result):
        """Muestra una grilla 2x3 con las imagenes reconstruidas por escenario."""
        for widget in parent_frame.winfo_children():
            widget.destroy()

        fig = Figure(figsize=(8, 5), dpi=100)
        fig.patch.set_facecolor('#2b2b2b')
        axes = fig.subplots(2, 3)

        for ax, item in zip(axes.flat, result["scenarios"]):
            ax.set_facecolor('#2b2b2b')
            ax.imshow(item["rx_image"], cmap="gray", vmin=0, vmax=255)
            ax.set_title(
                f"{item['label']}\nBER: {item['ber']:.2e} | Rank: {item['num_layers']}",
                color="white",
                fontsize=9,
            )
            ax.axis("off")

        fig.suptitle(
            f"{result['summary']}",
            color="white",
            fontsize=11,
            fontweight="bold",
        )
        fig.tight_layout(rect=(0, 0, 1, 0.92))

        canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _positive_log_floor(self, series):
        positives = []
        for item in series:
            values = np.asarray(item["y"], dtype=float)
            positives.append(values[values > 0])
        positives = [values for values in positives if len(values) > 0]
        if positives:
            return max(float(np.min(np.concatenate(positives))) * 0.1, 1e-9)
        return 1e-9

    def _style_plot_axis(self, ax, title, xlabel, ylabel, log_y=False, y_floor=1e-9):
        ax.set_title(title, color='white', fontsize=12)
        ax.set_xlabel(xlabel, color='white')
        ax.set_ylabel(ylabel, color='white')
        ax.tick_params(axis='x', colors='white')
        ax.tick_params(axis='y', colors='white')
        ax.grid(True, color='#444444', linestyle='--', alpha=0.65)
        if log_y:
            ax.set_yscale('log')
            ax.set_ylim(bottom=y_floor * 0.1, top=1.1)

    def _plot_series(self, ax, x_data, series, log_y=False, y_floor=1e-9, show_confidence=False):
        colors = ['#4E79A7', '#59A14F', '#F28E2B', '#76B7B2', '#B07AA1', '#E15759']
        for idx, item in enumerate(series):
            color = item.get("color") or colors[idx % len(colors)]
            linestyle = item.get("linestyle") or "-"
            marker = item.get("marker") or "o"
            y_data = np.asarray(item["y"], dtype=float)

            if log_y:
                y_data = np.maximum(y_data, y_floor)

            if show_confidence and "ci_lower" in item and "ci_upper" in item:
                y_lower = np.asarray(item["ci_lower"], dtype=float)
                y_upper = np.asarray(item["ci_upper"], dtype=float)
                if log_y:
                    y_lower = np.maximum(y_lower, y_floor)
                    y_upper = np.maximum(y_upper, y_floor)
                ax.fill_between(x_data, y_lower, y_upper, color=color, alpha=0.10, linewidth=0)

            ax.plot(
                x_data,
                y_data,
                marker=marker,
                color=color,
                linestyle=linestyle,
                linewidth=2,
                markersize=4.5,
                label=item["label"],
            )

    def _add_plot_footer(self, parent_frame, footer_text):
        if not footer_text:
            return
        footer = ctk.CTkLabel(
            parent_frame,
            text=footer_text,
            text_color="#D7E2F0",
            justify="left",
            wraplength=760,
            font=ctk.CTkFont(family="Courier", size=11),
        )
        footer.pack(fill="x", padx=14, pady=(0, 10))

    def embed_multi_plot(
        self,
        parent_frame,
        x_data,
        series,
        title,
        xlabel,
        ylabel,
        log_y=False,
        footer_text=None,
        show_confidence=False,
    ):
        """Incrusta multiples curvas."""
        for widget in parent_frame.winfo_children():
            widget.destroy()

        fig = Figure(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor('#2b2b2b')

        x_data = np.asarray(x_data, dtype=float)
        ax = fig.add_subplot(111)
        ax.set_facecolor('#2b2b2b')

        floor = self._positive_log_floor(series) if log_y else 1e-9
        self._plot_series(ax, x_data, series, log_y=log_y, y_floor=floor, show_confidence=show_confidence)
        self._style_plot_axis(ax, title, xlabel, ylabel, log_y=log_y, y_floor=floor)

        legend_kwargs = {"facecolor": '#2b2b2b', "edgecolor": '#555555'}
        if len(series) > 4:
            legend_kwargs.update({
                "loc": "upper center",
                "bbox_to_anchor": (0.5, 1.22),
                "ncol": 3,
                "fontsize": 8,
            })
            fig.subplots_adjust(top=0.78)
        legend = ax.legend(**legend_kwargs)
        for text in legend.get_texts():
            text.set_color('white')

        canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
        self._add_plot_footer(parent_frame, footer_text)

    def embed_mimo_ber_plot(self, parent_frame, ber_result):
        """Muestra solo la curva BER para los seis escenarios MIMO."""
        self.embed_multi_plot(
            parent_frame,
            ber_result["x"],
            ber_result["series"],
            "BER MIMO - IRC/MMSE vs SIC",
            "SNR (dB)",
            "Bit Error Rate (BER)",
            log_y=True,
            footer_text=ber_result["summary"],
        )
