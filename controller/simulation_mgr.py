import numpy as np

from core import channel, config, ofdm_ops, utils


def _wilson_interval(errors, total, z=1.96):
    if total <= 0:
        return 0.0, 0.0

    p_hat = errors / total
    z2 = z * z
    denom = 1 + z2 / total
    center = (p_hat + z2 / (2 * total)) / denom
    margin = z * np.sqrt((p_hat * (1 - p_hat) + z2 / (4 * total)) / total) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _mean_interval(values, z=1.96):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return 0.0, 0.0
    if len(values) == 1:
        return float(values[0]), float(values[0])

    mean = float(np.mean(values))
    sem = float(np.std(values, ddof=1) / np.sqrt(len(values)))
    return max(0.0, mean - z * sem), min(1.0, mean + z * sem)


def _combined_interval(values, successes, total, z=1.96):
    wilson_low, wilson_high = _wilson_interval(successes, total, z)
    mean_low, mean_high = _mean_interval(values, z)
    return min(wilson_low, mean_low), max(wilson_high, mean_high)


class OFDMSimulationManager:
    """
    Recibe parametros de la GUI, coordina los calculos matematicos del Core
    y devuelve resultados limpios para visualizar.
    """

    def __init__(self):
        self.img_size = 250
        self.mc_min_runs = 5
        self.mc_max_runs = 25
        self.mc_confidence_z = 1.96
        self.mc_abs_ci_target = 2e-4
        self.mc_rel_ci_target = 0.25
        self.mc_seed = 2024
        self.image_tx_seed = 2024
        self.ber_random_bits = 60_000

    def _mimo_config(self, mimo_mode):
        try:
            return config.MIMO_MODES[mimo_mode]
        except KeyError as exc:
            raise ValueError("Modo MIMO no soportado") from exc

    def _detector_name(self, detector):
        try:
            return config.MIMO_DETECTORS[detector]
        except KeyError as exc:
            raise ValueError("Detector MIMO no soportado") from exc

    def _mode_precoder(self, mode_cfg):
        return ofdm_ops.mimo_precoder_matrix(
            mode_cfg["n_tx"],
            mode_cfg["layers"],
            mode_cfg.get("precoder", "identity"),
        )

    def _normalize_rank_mode(self, rank_mode):
        value = "max" if rank_mode is None else str(rank_mode).strip().lower()
        value = value.replace("á", "a").replace(" ", "_").replace("-", "_")
        if value in ("2", "r2", "rank2", "rank_2"):
            return "rank2", "Rank 2"
        if value in ("max", "maximum", "rank_max", "rank_maximo", "maximo"):
            return "max", "Rank maximo"
        raise ValueError("Modo de rank no soportado")

    def _mimo_comparison_scenarios(self, rank_mode="max"):
        normalized_rank, _ = self._normalize_rank_mode(rank_mode)
        if normalized_rank == "rank2":
            return [
                {"label": "2x2 R2 IRC/MMSE", "mode": 2, "detector": 2, "color": "#4E79A7", "linestyle": "-", "marker": "o"},
                {"label": "4x2 R2 IRC/MMSE", "mode": 4, "detector": 2, "color": "#59A14F", "linestyle": "-", "marker": "o"},
                {"label": "4x4 R2 IRC/MMSE", "mode": 5, "detector": 2, "color": "#F28E2B", "linestyle": "-", "marker": "o"},
                {"label": "2x2 R2 SIC", "mode": 2, "detector": 3, "color": "#76B7B2", "linestyle": "--", "marker": "s"},
                {"label": "4x2 R2 SIC", "mode": 4, "detector": 3, "color": "#B07AA1", "linestyle": "--", "marker": "s"},
                {"label": "4x4 R2 SIC", "mode": 5, "detector": 3, "color": "#E15759", "linestyle": "--", "marker": "s"},
            ]

        return [
            {"label": "2x2 R2 IRC/MMSE", "mode": 2, "detector": 2, "color": "#4E79A7", "linestyle": "-", "marker": "o"},
            {"label": "4x2 R2 IRC/MMSE", "mode": 4, "detector": 2, "color": "#59A14F", "linestyle": "-", "marker": "o"},
            {"label": "4x4 R4 IRC/MMSE", "mode": 3, "detector": 2, "color": "#F28E2B", "linestyle": "-", "marker": "o"},
            {"label": "2x2 R2 SIC", "mode": 2, "detector": 3, "color": "#76B7B2", "linestyle": "--", "marker": "s"},
            {"label": "4x2 R2 SIC", "mode": 4, "detector": 3, "color": "#B07AA1", "linestyle": "--", "marker": "s"},
            {"label": "4x4 R4 SIC", "mode": 3, "detector": 3, "color": "#E15759", "linestyle": "--", "marker": "s"},
        ]

    def _active_channel_frequency_response(self, h, n_fft, nc):
        return ofdm_ops.channel_frequency_response(h, n_fft, nc)

    def _channel_metrics(self, h, tx_plan, snr_db):
        h_freq = self._active_channel_frequency_response(
            h,
            tx_plan["n_fft"],
            tx_plan["nc"],
        )
        snr_linear = 10 ** (snr_db / 10)

        if tx_plan["num_layers"] == 1:
            gain = np.abs(h_freq) ** 2
            capacity = float(np.mean(np.log2(1.0 + snr_linear * gain)))
            return {
                "condition_mean": 1.0,
                "condition_median": 1.0,
                "capacity_bpshz": capacity,
            }

        precoder = tx_plan.get("precoder_matrix")
        if precoder is not None:
            h_freq = np.einsum("krt,tl->krl", h_freq, precoder)

        singular_values = np.linalg.svd(h_freq, compute_uv=False)
        min_sv = np.maximum(singular_values[:, -1], 1e-12)
        conditions = singular_values[:, 0] / min_sv
        conditions = conditions[np.isfinite(conditions)]
        if len(conditions) == 0:
            condition_mean = float("inf")
            condition_median = float("inf")
        else:
            condition_mean = float(np.mean(conditions))
            condition_median = float(np.median(conditions))

        power_split_snr = snr_linear / tx_plan["num_layers"]
        capacity = float(np.mean(np.sum(np.log2(1.0 + power_split_snr * singular_values**2), axis=1)))
        return {
            "condition_mean": condition_mean,
            "condition_median": condition_median,
            "capacity_bpshz": capacity,
        }

    def _selected_config_summary(
        self,
        bw_idx,
        profile_idx,
        num_paths=None,
        mimo_mode=None,
        detector=None,
    ):
        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        bw_name = config.LTE_BANDWIDTHS[bw_idx]["name"]
        cp_name = config.LTE_PROFILES[profile_idx]["name"]
        parts = [f"BW: {bw_name} ({nc} SC)", f"CP: {cp_name}"]
        if num_paths is not None:
            parts.append(f"Canal: {channel.DEFAULT_RAYLEIGH_PROFILE}, caminos: {num_paths}")
        if mimo_mode is not None:
            mode_cfg = self._mimo_config(mimo_mode)
            parts.append(f"Modo: {mode_cfg['name']}")
            if mode_cfg["layers"] > 1 and detector is not None:
                parts.append(f"Detector: {self._detector_name(detector)}")
        return " | ".join(parts)

    def _data_subcarriers_per_layer(self, nc, mimo_mode):
        return int(nc)

    def _throughput_factor(self, nc, mimo_mode):
        mode_cfg = self._mimo_config(mimo_mode)
        return float(mode_cfg["layers"])

    def _random_ber_bits(self, seed_offset=0):
        rng = np.random.default_rng(self.mc_seed + 50_000 + int(seed_offset))
        return rng.integers(0, 2, self.ber_random_bits, dtype=np.uint8)

    def _ofdm_block_count(self, total_bits, bw_idx, profile_idx, mod_type, mimo_mode=1):
        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        mode_cfg = self._mimo_config(mimo_mode)
        data_subcarriers = self._data_subcarriers_per_layer(nc, mimo_mode)
        symbols_per_block = data_subcarriers * mode_cfg["layers"]
        num_symbols = int(np.ceil(total_bits / config.MODULATION_BITS[mod_type]))
        return int(np.ceil(num_symbols / symbols_per_block)) if symbols_per_block else 0

    def _blocks_by_modulation(self, total_bits, bw_idx, profile_idx, mimo_mode=1):
        return {
            config.MODULATION_NAMES[mod_type]: self._ofdm_block_count(
                total_bits,
                bw_idx,
                profile_idx,
                mod_type,
                mimo_mode,
            )
            for mod_type in (1, 2, 3)
        }

    def _format_blocks_by_label(self, blocks_by_label):
        return ", ".join(f"{label}={blocks}" for label, blocks in blocks_by_label.items())

    def _prepare_tx_signal(
        self,
        tx_bits_raw,
        bw_idx,
        profile_idx,
        mod_type,
        scramble_seed,
        mimo_mode=1,
    ):
        n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
        mode_cfg = self._mimo_config(mimo_mode)
        precoder_matrix = self._mode_precoder(mode_cfg)
        tx_bits = utils.apply_scrambling(tx_bits_raw, seed=scramble_seed)
        tx_syms = utils.map_bits_to_symbols(tx_bits, mod_type)

        if mode_cfg["layers"] == 1:
            ofdm_sig, n_blks = ofdm_ops.modulate_ofdm(
                tx_syms,
                n_fft,
                nc,
            )
            tx_cp, cp_used = ofdm_ops.add_cyclic_prefix(ofdm_sig, n_blks, n_fft, cp_lengths)
            tx_scale = 1.0
        else:
            ofdm_sig, n_blks = ofdm_ops.modulate_mimo_ofdm(
                tx_syms,
                n_fft,
                nc,
                n_tx=mode_cfg["n_tx"],
                n_layers=mode_cfg["layers"],
                precoder=precoder_matrix,
            )
            tx_cp_rows = []
            cp_used = None
            for tx_idx in range(mode_cfg["n_tx"]):
                tx_cp_single, cp_single = ofdm_ops.add_cyclic_prefix(
                    ofdm_sig[tx_idx],
                    n_blks,
                    n_fft,
                    cp_lengths,
                )
                if cp_used is None:
                    cp_used = cp_single
                elif not np.array_equal(cp_used, cp_single):
                    raise ValueError("Las antenas MIMO deben usar el mismo patron de CP")
                tx_cp_rows.append(tx_cp_single)
            tx_scale = 1 / np.sqrt(mode_cfg["layers"])
            tx_cp = np.vstack(tx_cp_rows) * tx_scale

        return {
            "tx_cp": tx_cp,
            "cp_used": cp_used,
            "n_fft": n_fft,
            "nc": nc,
            "sample_rate_hz": n_fft * df,
            "num_blocks": n_blks,
            "num_symbols": len(tx_syms),
            "num_layers": mode_cfg["layers"],
            "n_tx": mode_cfg["n_tx"],
            "n_rx": mode_cfg["n_rx"],
            "precoder": mode_cfg.get("precoder", "identity"),
            "precoder_matrix": precoder_matrix,
            "tx_scale": tx_scale,
            "data_subcarriers_per_layer": self._data_subcarriers_per_layer(nc, mimo_mode),
            "throughput_factor": self._throughput_factor(nc, mimo_mode),
        }

    def _receive_bits(
        self,
        rx_cp,
        tx_plan,
        mod_type,
        valid_len,
        scramble_seed,
        h,
        noise_to_signal,
        mimo_mode=1,
        detector=2,
    ):
        mode_cfg = self._mimo_config(mimo_mode)
        n_fft = tx_plan["n_fft"]
        nc = tx_plan["nc"]
        cp_used = tx_plan["cp_used"]

        if mode_cfg["layers"] == 1:
            rx_no_cp = ofdm_ops.remove_cyclic_prefix(rx_cp, n_fft, cp_used)
            rx_eq, _ = ofdm_ops.demodulate_ofdm_with_channel(
                rx_no_cp,
                n_fft,
                nc,
                h,
                noise_to_signal=noise_to_signal,
                channel_scale=tx_plan["tx_scale"],
            )
        else:
            rx_cp = np.asarray(rx_cp, dtype=np.complex128)
            rx_no_cp = np.vstack(
                [
                    ofdm_ops.remove_cyclic_prefix(rx_cp[rx_idx], n_fft, cp_used)
                    for rx_idx in range(rx_cp.shape[0])
                ]
            )
            rx_eq, _ = ofdm_ops.demodulate_mimo_ofdm_with_channel(
                rx_no_cp,
                n_fft,
                nc,
                h,
                n_tx=mode_cfg["n_tx"],
                n_layers=mode_cfg["layers"],
                precoder=tx_plan["precoder_matrix"],
                detector=self._detector_name(detector),
                noise_to_signal=noise_to_signal,
                mod_type=mod_type,
                channel_scale=tx_plan["tx_scale"],
            )

        rx_bits_scrambled = utils.demap_symbols_to_bits(rx_eq, mod_type)
        rx_bits_scrambled = rx_bits_scrambled[:valid_len]
        rx_bits = utils.apply_scrambling(rx_bits_scrambled, seed=scramble_seed)
        if len(rx_bits) < valid_len:
            rx_bits = np.pad(rx_bits, (0, valid_len - len(rx_bits)))
        return rx_bits[:valid_len]

    def _apply_channel(self, tx_plan, snr_db, num_paths, rng, h=None):
        if tx_plan["num_layers"] == 1:
            return channel.apply_rayleigh(
                tx_plan["tx_cp"],
                snr_db,
                num_taps=num_paths,
                h=h,
                sample_rate_hz=tx_plan["sample_rate_hz"],
                rng=rng,
            )
        return channel.apply_mimo_rayleigh(
            tx_plan["tx_cp"],
            snr_db,
            num_taps=num_paths,
            h=h,
            sample_rate_hz=tx_plan["sample_rate_hz"],
            rng=rng,
            n_rx=tx_plan["n_rx"],
        )

    def _generate_channel_for_plan(self, tx_plan, num_paths, rng):
        if tx_plan["num_layers"] == 1:
            return channel.generate_rayleigh_channel(
                num_paths,
                rng=rng,
                sample_rate_hz=tx_plan["sample_rate_hz"],
            )
        return channel.generate_mimo_rayleigh_channel(
            n_tx=tx_plan["n_tx"],
            n_rx=tx_plan["n_rx"],
            num_taps=num_paths,
            rng=rng,
            sample_rate_hz=tx_plan["sample_rate_hz"],
        )

    def run_image_transmission(
        self,
        image_path,
        bw_idx,
        profile_idx,
        mod_type,
        snr_db,
        num_paths,
        rng_seed=None,
        mimo_mode=config.DEFAULT_MIMO_MODE,
        detector=config.DEFAULT_MIMO_DETECTOR,
    ):
        """Ejecuta la cadena completa: Tx -> Canal -> Rx."""
        try:
            n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
            sample_rate_hz = n_fft * df
            channel_report = channel.cp_safety_report(num_paths, cp_lengths, sample_rate_hz)

            img_size = self.img_size
            tx_bits_raw, tx_img_matrix = utils.image_to_bits(image_path, img_size)
            valid_len = len(tx_bits_raw)
            tx_plan = self._prepare_tx_signal(
                tx_bits_raw,
                bw_idx,
                profile_idx,
                mod_type,
                self.image_tx_seed,
                mimo_mode,
            )

            rng_seed_used = self.image_tx_seed if rng_seed is None else rng_seed
            rng = np.random.default_rng(rng_seed_used)
            rx_signal_cp, h_used = self._apply_channel(tx_plan, snr_db, num_paths, rng)
            channel_metrics = self._channel_metrics(h_used, tx_plan, snr_db)
            rx_bits = self._receive_bits(
                rx_signal_cp,
                tx_plan,
                mod_type,
                valid_len,
                self.image_tx_seed,
                h=h_used,
                noise_to_signal=10 ** (-snr_db / 10),
                mimo_mode=mimo_mode,
                detector=detector,
            )

            bit_errors = int(np.sum(tx_bits_raw != rx_bits))
            ber = bit_errors / valid_len
            rx_img_matrix = utils.bits_to_image(rx_bits, img_size)
            mode_cfg = self._mimo_config(mimo_mode)
            detector_label = self._detector_name(detector) if mode_cfg["layers"] > 1 else "N/A"

            return {
                "success": True,
                "tx_image": tx_img_matrix,
                "rx_image": rx_img_matrix,
                "ber": ber,
                "snr": snr_db,
                "total_bits": valid_len,
                "num_symbols": tx_plan["num_symbols"],
                "ofdm_blocks": tx_plan["num_blocks"],
                "channel_report": channel_report,
                "rng_seed": rng_seed_used,
                "mimo_mode": mimo_mode,
                "mimo_mode_name": mode_cfg["name"],
                "detector": detector_label,
                "n_tx": tx_plan["n_tx"],
                "n_rx": tx_plan["n_rx"],
                "num_layers": tx_plan["num_layers"],
                "data_subcarriers_per_layer": tx_plan["data_subcarriers_per_layer"],
                "throughput_factor": tx_plan["throughput_factor"],
                "channel_condition_mean": channel_metrics["condition_mean"],
                "channel_condition_median": channel_metrics["condition_median"],
                "ideal_capacity_bpshz": channel_metrics["capacity_bpshz"],
                "info": (
                    f"BER: {ber:.5f} | Modo: {mode_cfg['name']} | Detector: {detector_label} | "
                    f"Antenas: {tx_plan['n_tx']}x{tx_plan['n_rx']} | Capas: {tx_plan['num_layers']} | "
                    f"Factor: {tx_plan['throughput_factor']:.2f}x | CSI perfecta | "
                    f"Cond media/med: {channel_metrics['condition_mean']:.2f}/"
                    f"{channel_metrics['condition_median']:.2f} | Cap: "
                    f"{channel_metrics['capacity_bpshz']:.2f} bps/Hz | "
                    f"Bits: {valid_len} | Simbolos: {tx_plan['num_symbols']} | "
                    f"Bloques OFDM: {tx_plan['num_blocks']} | Datos/capa: "
                    f"{tx_plan['data_subcarriers_per_layer']} SC | SC activas: {nc}"
                ),
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
            }

    def _is_ci_sufficient(self, estimate, lower, upper):
        half_width = (upper - lower) / 2
        target = max(self.mc_abs_ci_target, abs(estimate) * self.mc_rel_ci_target)
        return half_width <= target

    def _calculate_ber_series(
        self,
        tx_bits_raw,
        bw_idx,
        profile_idx,
        mod_type,
        num_paths,
        snr_range,
        mimo_mode=1,
        detector=2,
        series_label=None,
        series_color=None,
        series_linestyle="-",
        series_marker="o",
        min_runs=None,
        max_runs=None,
    ):
        min_runs = self.mc_min_runs if min_runs is None else int(min_runs)
        max_runs = self.mc_max_runs if max_runs is None else int(max_runs)
        n_points = len(snr_range)
        bit_errors = np.zeros(n_points, dtype=np.int64)
        total_bits = np.zeros(n_points, dtype=np.int64)
        run_counts = np.zeros(n_points, dtype=np.int64)
        run_ber_values = [[] for _ in range(n_points)]
        active = np.ones(n_points, dtype=bool)
        valid_len = len(tx_bits_raw)

        for run_idx in range(max_runs):
            scramble_seed = self.mc_seed + run_idx
            rng = np.random.default_rng(self.mc_seed * 10 + run_idx)
            tx_plan = self._prepare_tx_signal(
                tx_bits_raw,
                bw_idx,
                profile_idx,
                mod_type,
                scramble_seed,
                mimo_mode,
            )
            h_run = self._generate_channel_for_plan(tx_plan, num_paths, rng)

            for idx, snr in enumerate(snr_range):
                if not active[idx]:
                    continue

                rx_cp, h = self._apply_channel(tx_plan, snr, num_paths, rng, h=h_run)
                rx_bits = self._receive_bits(
                    rx_cp,
                    tx_plan,
                    mod_type,
                    valid_len,
                    scramble_seed,
                    h=h,
                    noise_to_signal=10 ** (-snr / 10),
                    mimo_mode=mimo_mode,
                    detector=detector,
                )
                errors = int(np.sum(tx_bits_raw != rx_bits[:valid_len]))
                run_ber = errors / valid_len

                bit_errors[idx] += errors
                total_bits[idx] += valid_len
                run_counts[idx] += 1
                run_ber_values[idx].append(run_ber)

            if run_idx + 1 >= min_runs:
                for idx in range(n_points):
                    if not active[idx]:
                        continue
                    estimate = bit_errors[idx] / total_bits[idx]
                    lower, upper = _combined_interval(
                        run_ber_values[idx],
                        bit_errors[idx],
                        total_bits[idx],
                        self.mc_confidence_z,
                    )
                    active[idx] = not self._is_ci_sufficient(estimate, lower, upper)

            if not np.any(active):
                break

        ber_values = np.divide(
            bit_errors,
            total_bits,
            out=np.zeros_like(bit_errors, dtype=float),
            where=total_bits > 0,
        )
        ci_lower = np.zeros(n_points)
        ci_upper = np.zeros(n_points)
        for idx in range(n_points):
            ci_lower[idx], ci_upper[idx] = _combined_interval(
                run_ber_values[idx],
                bit_errors[idx],
                total_bits[idx],
                self.mc_confidence_z,
            )

        return {
            "label": series_label or config.MODULATION_NAMES[mod_type],
            "mod_type": mod_type,
            "mimo_mode": mimo_mode,
            "detector": self._detector_name(detector),
            "throughput_factor": self._throughput_factor(tx_plan["nc"], mimo_mode),
            "color": series_color,
            "linestyle": series_linestyle,
            "marker": series_marker,
            "y": ber_values,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "runs": run_counts,
            "total_bits": total_bits,
        }

    def calculate_ber_curve(
        self,
        image_path,
        bw_idx,
        profile_idx,
        mod_type=None,
        num_paths=1,
        mimo_mode=config.DEFAULT_MIMO_MODE,
        detector=config.DEFAULT_MIMO_DETECTOR,
    ):
        """
        Calcula BER vs SNR para QPSK, 16-QAM y 64-QAM con bits aleatorios.

        La opcion de modulacion de la GUI se ignora intencionalmente: esta
        curva siempre compara las tres modulaciones bajo el modo MIMO activo.
        """
        snr_range = np.linspace(0, 30, 10)

        series = [
            self._calculate_ber_series(
                self._random_ber_bits(current_mod),
                bw_idx,
                profile_idx,
                current_mod,
                num_paths,
                snr_range,
                mimo_mode=mimo_mode,
                detector=detector,
            )
            for current_mod in (1, 2, 3)
        ]

        all_runs = np.concatenate([item["runs"] for item in series])
        min_runs = int(np.min(all_runs))
        max_runs = int(np.max(all_runs))
        config_summary = self._selected_config_summary(
            bw_idx,
            profile_idx,
            num_paths,
            mimo_mode=mimo_mode,
            detector=detector,
        )
        blocks_by_modulation = self._blocks_by_modulation(
            self.ber_random_bits,
            bw_idx,
            profile_idx,
            mimo_mode,
        )
        block_summary = self._format_blocks_by_label(blocks_by_modulation)
        mode_cfg = self._mimo_config(mimo_mode)
        detector_label = self._detector_name(detector) if mode_cfg["layers"] > 1 else "N/A"
        return {
            "x": snr_range,
            "series": series,
            "payload_bits": self.ber_random_bits,
            "confidence": 0.95,
            "run_min": min_runs,
            "run_max": max_runs,
            "blocks_by_modulation": blocks_by_modulation,
            "config_summary": config_summary,
            "summary": (
                f"BER Monte Carlo: bits aleatorios, 3 modulaciones, modo {mode_cfg['name']}, "
                f"detector {detector_label}, corridas/punto {min_runs}-{max_runs}, "
                f"bloques/corrida {block_summary}, IC 95% | {config_summary}"
            ),
        }

    def calculate_mimo_comparison(
        self,
        image_path,
        bw_idx,
        profile_idx,
        mod_type,
        num_paths=1,
        rank_mode="max",
    ):
        """Compara arreglos 2x2, 4x2 y 4x4 con IRC/MMSE y SIC."""
        normalized_rank, rank_label = self._normalize_rank_mode(rank_mode)
        snr_range = np.array([5, 10, 15, 20, 25, 30], dtype=float)
        tx_bits_raw = self._random_ber_bits(100 + mod_type)
        scenarios = self._mimo_comparison_scenarios(normalized_rank)
        min_runs_target = min(self.mc_min_runs, 3)
        max_runs_target = max(min_runs_target, min(self.mc_max_runs, 8))
        series = [
            self._calculate_ber_series(
                tx_bits_raw,
                bw_idx,
                profile_idx,
                mod_type,
                num_paths,
                snr_range,
                mimo_mode=scenario["mode"],
                detector=scenario["detector"],
                series_label=scenario["label"],
                series_color=scenario["color"],
                series_linestyle=scenario["linestyle"],
                series_marker=scenario["marker"],
                min_runs=min_runs_target,
                max_runs=max_runs_target,
            )
            for scenario in scenarios
        ]

        all_runs = np.concatenate([item["runs"] for item in series])
        min_runs = int(np.min(all_runs))
        max_runs = int(np.max(all_runs))
        blocks_by_mode = {
            scenario["label"]: self._ofdm_block_count(
                len(tx_bits_raw),
                bw_idx,
                profile_idx,
                mod_type,
                scenario["mode"],
            )
            for scenario in scenarios
        }
        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        throughput_by_mode = {
            scenario["label"]: self._throughput_factor(nc, scenario["mode"])
            for scenario in scenarios
        }
        block_summary = self._format_blocks_by_label(blocks_by_mode)
        throughput_summary = self._format_blocks_by_label(
            {label: f"{factor:.2f}x" for label, factor in throughput_by_mode.items()}
        )
        config_summary = self._selected_config_summary(bw_idx, profile_idx, num_paths)
        mod_name = config.MODULATION_NAMES[mod_type]
        return {
            "x": snr_range,
            "series": series,
            "payload_bits": len(tx_bits_raw),
            "mod_type": mod_type,
            "modulation": mod_name,
            "rank_mode": normalized_rank,
            "rank_label": rank_label,
            "confidence": 0.95,
            "run_min": min_runs,
            "run_max": max_runs,
            "blocks_by_mode": blocks_by_mode,
            "throughput_by_mode": throughput_by_mode,
            "config_summary": config_summary,
            "summary": (
                f"Comparacion multiantena: {mod_name}, {rank_label}, "
                f"bits aleatorios {len(tx_bits_raw)}, "
                f"corridas/punto {min_runs}-{max_runs}, bloques/corrida {block_summary}, "
                f"capas {throughput_summary} | {config_summary}"
            ),
        }

    def calculate_mimo_visual_comparison(
        self,
        image_path,
        bw_idx,
        profile_idx,
        mod_type,
        snr_db,
        num_paths=1,
        rank_mode="max",
    ):
        """Transmite la imagen una vez por cada escenario multiantena."""
        normalized_rank, rank_label = self._normalize_rank_mode(rank_mode)
        scenarios = self._mimo_comparison_scenarios(normalized_rank)
        results = []
        for scenario in scenarios:
            result = self.run_image_transmission(
                image_path,
                bw_idx,
                profile_idx,
                mod_type,
                snr_db,
                num_paths,
                rng_seed=self.image_tx_seed,
                mimo_mode=scenario["mode"],
                detector=scenario["detector"],
            )
            if not result.get("success"):
                raise RuntimeError(f"{scenario['label']}: {result.get('error')}")
            result["label"] = scenario["label"]
            result["color"] = scenario["color"]
            result["linestyle"] = scenario["linestyle"]
            results.append(result)

        mod_name = config.MODULATION_NAMES[mod_type]
        return {
            "scenarios": results,
            "snr": snr_db,
            "modulation": mod_name,
            "rank_mode": normalized_rank,
            "rank_label": rank_label,
            "summary": (
                f"Prueba multiantena: {mod_name}, {rank_label}, SNR {snr_db} dB, "
                "2x2/4x2/4x4 con IRC/MMSE y SIC"
            ),
        }

    def calculate_mimo_analysis(
        self,
        image_path,
        bw_idx,
        profile_idx,
        mod_type,
        snr_db,
        num_paths=1,
        rank_mode="max",
    ):
        """Devuelve grilla visual y curvas BER multiantena en una sola tarea."""
        visual = self.calculate_mimo_visual_comparison(
            image_path,
            bw_idx,
            profile_idx,
            mod_type,
            snr_db,
            num_paths,
            rank_mode,
        )
        ber = self.calculate_mimo_comparison(
            image_path,
            bw_idx,
            profile_idx,
            mod_type,
            num_paths,
            rank_mode,
        )
        return {
            "visual": visual,
            "ber": ber,
            "summary": f"{visual['summary']} | {ber['summary']}",
        }
