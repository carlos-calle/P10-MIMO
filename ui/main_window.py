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
from core import channel, utils

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Simulador LTE OFDM")
        self.geometry("1100x750")

        self.manager = OFDMSimulationManager()
        self.worker_queue = queue.Queue()
        self.worker_thread = None
        self.worker_task = None
        self.worker_success_handler = None
        
        self.selected_image_path = None
        
        self.bw_map = {"1.4 MHz": 1, "3 MHz": 2, "5 MHz": 3, "10 MHz": 4, "15 MHz": 5, "20 MHz": 6}
        self.cp_map = {"Normal (4.7µs)": 1, "Extendido (16.6µs)": 2}
        self.mod_map = {"QPSK": 1, "16-QAM": 2, "64-QAM": 3}

        self.setup_ui()

    def setup_ui(self):
        """Disposición de elementos visuales (Grid Layout)"""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(17, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="LTE SIMULATOR", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.lbl_phys = ctk.CTkLabel(self.sidebar_frame, text="Parámetros Físicos:", anchor="w")
        self.lbl_phys.grid(row=1, column=0, padx=20, pady=(10, 0))
        
        self.option_bw = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=list(self.bw_map.keys()),
            command=self.update_channel_info,
        )
        self.option_bw.grid(row=2, column=0, padx=20, pady=5)
        self.option_bw.set("10 MHz")

        self.option_cp = ctk.CTkOptionMenu(
            self.sidebar_frame,
            values=list(self.cp_map.keys()),
            command=self.update_channel_info,
        )
        self.option_cp.grid(row=3, column=0, padx=20, pady=5)
        self.option_cp.set("Normal (4.7µs)")

        self.lbl_link = ctk.CTkLabel(self.sidebar_frame, text="Enlace y Canal:", anchor="w")
        self.lbl_link.grid(row=4, column=0, padx=20, pady=(20, 0))

        self.option_mod = ctk.CTkOptionMenu(self.sidebar_frame, values=list(self.mod_map.keys()))
        self.option_mod.grid(row=5, column=0, padx=20, pady=5)
        self.option_mod.set("16-QAM")

        self.lbl_snr = ctk.CTkLabel(self.sidebar_frame, text="SNR: 15 dB")
        self.lbl_snr.grid(row=6, column=0, padx=20, pady=(10,0))
        self.slider_snr = ctk.CTkSlider(self.sidebar_frame, from_=0, to=40, number_of_steps=40, command=self.update_snr_label)
        self.slider_snr.grid(row=7, column=0, padx=20, pady=5)
        self.slider_snr.set(15)

        self.lbl_paths = ctk.CTkLabel(self.sidebar_frame, text="Caminos (Multipath): 1")
        self.lbl_paths.grid(row=8, column=0, padx=20, pady=(10,0))
        max_paths = len(channel.get_rayleigh_profile()["delays_s"])
        self.slider_paths = ctk.CTkSlider(
            self.sidebar_frame,
            from_=1,
            to=max_paths,
            number_of_steps=max_paths - 1,
            command=self.update_paths_label,
        )
        self.slider_paths.grid(row=9, column=0, padx=20, pady=5)
        self.slider_paths.set(1)

        self.lbl_channel_info = ctk.CTkLabel(
            self.sidebar_frame,
            text="",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(family="Courier", size=10),
            text_color="#B8C7D9",
        )
        self.lbl_channel_info.grid(row=10, column=0, padx=20, pady=(0, 5), sticky="ew")

        self.lbl_source = ctk.CTkLabel(self.sidebar_frame, text="Fuente de Datos:", anchor="w")
        self.lbl_source.grid(row=11, column=0, padx=20, pady=(20, 0))

        self.btn_select_file = ctk.CTkButton(self.sidebar_frame, text="Seleccionar Imagen...", 
                                             fg_color="#4B4B4B", hover_color="#5B5B5B", 
                                             command=self.select_file)
        self.btn_select_file.grid(row=12, column=0, padx=20, pady=5)

        self.lbl_filename = ctk.CTkLabel(self.sidebar_frame, text="[Ningún archivo]", font=("Arial", 11), text_color="gray")
        self.lbl_filename.grid(row=13, column=0, padx=20, pady=0)

        self.btn_run_img = ctk.CTkButton(self.sidebar_frame, text="TRANSMITIR IMAGEN", 
                                         fg_color="#1f538d", hover_color="#14375e",
                                         command=self.action_run_image)
        self.btn_run_img.grid(row=14, column=0, padx=20, pady=(20, 10))

        self.btn_run_ber = ctk.CTkButton(self.sidebar_frame, text="GENERAR CURVA BER", 
                                         fg_color="transparent", border_width=2, 
                                         command=self.action_plot_ber)
        self.btn_run_ber.grid(row=15, column=0, padx=20, pady=10)

        self.btn_run_papr = ctk.CTkButton(self.sidebar_frame, text="ANALIZAR PAPR", 
                                          fg_color="transparent", border_width=2, 
                                          command=self.action_plot_papr)
        self.btn_run_papr.grid(row=16, column=0, padx=20, pady=10)

        self.update_channel_info()


        self.tabview = ctk.CTkTabview(self, width=800)
        self.tabview.grid(row=0, column=1, padx=(20, 20), pady=(20, 20), sticky="nsew")
        
        self.tab_img = self.tabview.add("Visualización Imagen")
        self.tab_ber = self.tabview.add("Análisis BER")
        self.tab_papr = self.tabview.add("Análisis PAPR")

        self.tab_img.grid_columnconfigure(0, weight=1)
        self.tab_img.grid_columnconfigure(1, weight=1)
        
        self.lbl_tx_title = ctk.CTkLabel(self.tab_img, text="Imagen Transmitida", font=("Arial", 16, "bold"))
        self.lbl_tx_title.grid(row=0, column=0, pady=10)
        self.lbl_tx_img = ctk.CTkLabel(self.tab_img, text="\n\n[Seleccione una imagen\npara comenzar]", font=("Arial", 14), text_color="gray")
        self.lbl_tx_img.grid(row=1, column=0)

        self.lbl_rx_title = ctk.CTkLabel(self.tab_img, text="Imagen Recibida", font=("Arial", 16, "bold"))
        self.lbl_rx_title.grid(row=0, column=1, pady=10)
        self.lbl_rx_img = ctk.CTkLabel(self.tab_img, text="\n\n[Esperando simulación...]", font=("Arial", 14), text_color="gray")
        self.lbl_rx_img.grid(row=1, column=1)

        self.lbl_status = ctk.CTkLabel(self.tab_img, text="Estado: Esperando configuración", font=("Courier", 14), text_color="yellow")
        self.lbl_status.grid(row=2, column=0, columnspan=2, pady=20)

    def _has_running_worker(self):
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _set_busy_state(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (
            self.option_bw,
            self.option_cp,
            self.option_mod,
            self.slider_snr,
            self.slider_paths,
            self.btn_select_file,
            self.btn_run_img,
            self.btn_run_ber,
            self.btn_run_papr,
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

    def update_paths_label(self, value):
        self.lbl_paths.configure(text=f"Caminos (Multipath): {int(value)}")
        self.update_channel_info()

    def update_channel_info(self, _=None):
        if not hasattr(self, "lbl_channel_info"):
            return

        bw_idx = self.bw_map[self.option_bw.get()]
        cp_idx = self.cp_map[self.option_cp.get()]
        n_fft, _, _, df = utils.get_ofdm_params(bw_idx, cp_idx)
        sample_rate_hz = n_fft * df
        paths = int(self.slider_paths.get())
        info = channel.describe_rayleigh_paths(paths, sample_rate_hz)
        _, _, cp_lengths, _ = utils.get_ofdm_params(bw_idx, cp_idx)
        cp_report = channel.cp_safety_report(paths, cp_lengths, sample_rate_hz)

        delays_us = info["delays_s"] * 1e6
        gains_db = info["gains_db"]
        samples = info["sample_delays"]
        cp_label = (
            f"CP: {cp_report['min_cp_samples']} n, ret: {cp_report['max_delay_samples']} n"
            if not cp_report["isi_expected"]
            else f"ISI: ret {cp_report['max_delay_samples']} > CP {cp_report['min_cp_samples']}"
        )
        lines = [
            f"Perfil: {info['profile_name']}",
            f"Caminos activos: {info['active_paths']}/{info['max_profile_paths']}",
            cp_label,
            "i   us     dB   n",
        ]
        for idx, (delay_us, gain_db, sample_delay) in enumerate(
            zip(delays_us, gains_db, samples), start=1
        ):
            lines.append(f"{idx:<2} {delay_us:>5.2f} {gain_db:>6.1f} {sample_delay:>3}")

        self.lbl_channel_info.configure(text="\n".join(lines))

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
            self.lbl_status.configure(text="Imagen cargada. Lista para transmitir.", text_color="white")

    def action_run_image(self):
        """Ejecuta la simulación de imagen"""
        if not self.selected_image_path:
            messagebox.showwarning("Falta Imagen", "Por favor selecciona una imagen primero usando el botón 'Seleccionar Imagen'.")
            return

        bw_idx = self.bw_map[self.option_bw.get()]
        prof_idx = self.cp_map[self.option_cp.get()]
        mod_idx = self.mod_map[self.option_mod.get()]
        snr = int(self.slider_snr.get())
        paths = int(self.slider_paths.get())

        self._start_worker(
            "image",
            "Procesando OFDM...",
            self.manager.run_image_transmission,
            (self.selected_image_path, bw_idx, prof_idx, mod_idx, snr, paths),
            self._show_image_result,
        )

    def _show_image_result(self, result):
        if result["success"]:
            img_tx_pil = Image.fromarray(result["tx_image"]).resize((300, 300), Image.Resampling.NEAREST)
            img_rx_pil = Image.fromarray(result["rx_image"]).resize((300, 300), Image.Resampling.NEAREST)

            self.tk_img_tx = ctk.CTkImage(light_image=img_tx_pil, dark_image=img_tx_pil, size=(300, 300))
            self.tk_img_rx = ctk.CTkImage(light_image=img_rx_pil, dark_image=img_rx_pil, size=(300, 300))

            self.lbl_tx_img.configure(image=self.tk_img_tx, text="")
            self.lbl_rx_img.configure(image=self.tk_img_rx, text="")
            self.lbl_status.configure(text=result["info"], text_color="#30D760")
            self.tabview.set("Visualización Imagen")
        else:
            self.lbl_status.configure(text=f"Error: {result.get('error')}", text_color="red")
            messagebox.showerror("Error de Simulación", f"Ocurrió un error al procesar la imagen:\n{result.get('error')}")

    def action_plot_ber(self):
        """Genera y muestra gráfica BER con la IMAGEN"""
        if not self.selected_image_path:
            messagebox.showwarning("Falta Imagen", "Selecciona una imagen para analizar su BER.")
            return

        bw_idx = self.bw_map[self.option_bw.get()]
        prof_idx = self.cp_map[self.option_cp.get()]
        paths = int(self.slider_paths.get())

        self._start_worker(
            "ber",
            "Calculando BER Monte Carlo de la imagen...",
            self.manager.calculate_ber_curve,
            (self.selected_image_path, bw_idx, prof_idx, None, paths),
            self._show_ber_result,
        )

    def _show_ber_result(self, result):
        self.embed_multi_plot(
            self.tab_ber,
            result["x"],
            result["series"],
            "BER vs SNR - Monte Carlo con Imagen",
            "SNR (dB)",
            "Bit Error Rate (BER)",
            log_y=True,
        )
        self.lbl_status.configure(text=result["summary"], text_color="white")
        self.tabview.set("Análisis BER")

    def action_plot_papr(self):
        """Genera y muestra gráfica PAPR con la IMAGEN"""
        if not self.selected_image_path:
            messagebox.showwarning("Falta Imagen", "Selecciona una imagen para analizar su PAPR.")
            return

        bw_idx = self.bw_map[self.option_bw.get()]
        prof_idx = self.cp_map[self.option_cp.get()]

        self._start_worker(
            "papr",
            "Calculando PAPR de la imagen para 3 modulaciones...",
            self.manager.calculate_papr_distribution,
            (self.selected_image_path, bw_idx, prof_idx),
            self._show_papr_result,
        )

    def _show_papr_result(self, result):
        self.embed_multi_plot(
            self.tab_papr,
            result["x"],
            result["series"],
            "CCDF de PAPR - Imagen Cargada",
            "Umbral de Potencia (dB)",
            "Probabilidad (PAPR > Umbral)",
            log_y=True,
        )
        self.lbl_status.configure(text=result["summary"], text_color="white")
        self.tabview.set("Análisis PAPR")

    def embed_multi_plot(self, parent_frame, x_data, series, title, xlabel, ylabel, log_y=False):
        """Incrusta multiples curvas con bandas de confianza."""
        for widget in parent_frame.winfo_children():
            widget.destroy()

        fig = Figure(figsize=(6, 4), dpi=100)
        fig.patch.set_facecolor('#2b2b2b')

        x_data = np.asarray(x_data, dtype=float)
        colors = ['#30D760', '#4DA3FF', '#FFB000']
        ax = fig.add_subplot(111)
        ax.set_facecolor('#2b2b2b')

        floor = 1e-9
        if log_y:
            positives = []
            for item in series:
                for key in ("y", "ci_lower", "ci_upper"):
                    values = np.asarray(item.get(key, item["y"]), dtype=float)
                    positives.append(values[values > 0])
            positives = [values for values in positives if len(values) > 0]
            if positives:
                floor = max(float(np.min(np.concatenate(positives))) * 0.1, 1e-9)

        for idx, item in enumerate(series):
            color = colors[idx % len(colors)]
            y_data = np.asarray(item["y"], dtype=float)
            y_lower = np.asarray(item.get("ci_lower", item["y"]), dtype=float)
            y_upper = np.asarray(item.get("ci_upper", item["y"]), dtype=float)

            if log_y:
                y_data = np.maximum(y_data, floor)
                y_lower = np.maximum(y_lower, floor)
                y_upper = np.maximum(y_upper, floor)

            ax.fill_between(x_data, y_lower, y_upper, color=color, alpha=0.14, linewidth=0)
            ax.plot(x_data, y_data, marker='o', color=color, linewidth=2, label=item["label"])

        ax.set_title(title, color='white', fontsize=12)
        ax.set_xlabel(xlabel, color='white')
        ax.set_ylabel(ylabel, color='white')
        ax.tick_params(axis='x', colors='white')
        ax.tick_params(axis='y', colors='white')
        ax.grid(True, color='#444444', linestyle='--')

        if log_y:
            ax.set_yscale('log')
            ax.set_ylim(bottom=floor * 0.1, top=1.1)

        legend = ax.legend(facecolor='#2b2b2b', edgecolor='#555555')
        for text in legend.get_texts():
            text.set_color('white')

        canvas = FigureCanvasTkAgg(fig, master=parent_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)
