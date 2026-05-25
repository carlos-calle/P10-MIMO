import numpy as np

from core import config, utils, ofdm_ops, channel


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
    Recibe parámetros de la GUI, coordina los cálculos matemáticos del Core
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
        self.papr_oversampling = 4

    def _selected_config_summary(self, bw_idx, profile_idx, num_paths=None):
        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        bw_name = config.LTE_BANDWIDTHS[bw_idx]["name"]
        cp_name = config.LTE_PROFILES[profile_idx]["name"]
        parts = [f"BW: {bw_name} ({nc} SC)", f"CP: {cp_name}"]
        if num_paths is not None:
            parts.append(f"Canal: {channel.DEFAULT_RAYLEIGH_PROFILE}, caminos: {num_paths}")
        return " | ".join(parts)

    def _ofdm_block_count(self, total_bits, bw_idx, profile_idx, mod_type):
        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        data_subcarriers = int(np.sum(~ofdm_ops.pilot_subcarrier_mask(nc)))
        num_symbols = int(np.ceil(total_bits / config.MODULATION_BITS[mod_type]))
        return int(np.ceil(num_symbols / data_subcarriers)) if data_subcarriers else 0

    def _blocks_by_modulation(self, total_bits, bw_idx, profile_idx):
        return {
            config.MODULATION_NAMES[mod_type]: self._ofdm_block_count(
                total_bits,
                bw_idx,
                profile_idx,
                mod_type,
            )
            for mod_type in (1, 2, 3)
        }

    def _format_blocks_by_modulation(self, blocks_by_modulation):
        return ", ".join(
            f"{label}={blocks}" for label, blocks in blocks_by_modulation.items()
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
    ):
        """
        Ejecuta la cadena completa: Tx -> Canal -> Rx
        """
        try:
            n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
            sample_rate_hz = n_fft * df
            channel_report = channel.cp_safety_report(num_paths, cp_lengths, sample_rate_hz)
            
            img_size = self.img_size
            tx_bits_raw, tx_img_matrix = utils.image_to_bits(image_path, img_size)
            
            tx_bits = utils.apply_scrambling(tx_bits_raw)
            tx_symbols = utils.map_bits_to_symbols(tx_bits, mod_type)
            total_bits = len(tx_bits_raw)
            num_symbols = len(tx_symbols)
            ofdm_time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(tx_symbols, n_fft, nc)
            tx_signal_cp, cp_used = ofdm_ops.add_cyclic_prefix(ofdm_time_signal, num_blocks, n_fft, cp_lengths)
            
            rng = np.random.default_rng(rng_seed)
            rx_signal_cp, _ = channel.apply_rayleigh(
                tx_signal_cp,
                snr_db,
                num_taps=num_paths,
                sample_rate_hz=sample_rate_hz,
                rng=rng,
            )
            
            rx_signal_no_cp = ofdm_ops.remove_cyclic_prefix(rx_signal_cp, n_fft, cp_used)
            rx_symbols_equalized, _ = ofdm_ops.demodulate_ofdm_with_pilots(rx_signal_no_cp, n_fft, nc)
            rx_bits_scrambled = utils.demap_symbols_to_bits(rx_symbols_equalized, mod_type)
            
            valid_len = len(tx_bits_raw)
            rx_bits_scrambled = rx_bits_scrambled[:valid_len]
            rx_bits = utils.apply_scrambling(rx_bits_scrambled)
            
            bit_errors = np.sum(tx_bits_raw != rx_bits)
            ber = bit_errors / valid_len
            rx_img_matrix = utils.bits_to_image(rx_bits, img_size)
            
            return {
                "success": True,
                "tx_image": tx_img_matrix,
                "rx_image": rx_img_matrix,
                "ber": ber,
                "snr": snr_db,
                "total_bits": total_bits,
                "num_symbols": num_symbols,
                "ofdm_blocks": num_blocks,
                "channel_report": channel_report,
                "info": f"BER: {ber:.5f} | Bits: {total_bits} | Símbolos: {num_symbols} | Bloques OFDM: {num_blocks} | SC activas: {nc}"
            }

        except Exception as exc:
            return {
                "success": False,
                "error": str(exc)
            }

    def _prepare_tx_signal(self, tx_bits_raw, bw_idx, profile_idx, mod_type, scramble_seed):
        n_fft, nc, cp_lengths, df = utils.get_ofdm_params(bw_idx, profile_idx)
        tx_bits = utils.apply_scrambling(tx_bits_raw, seed=scramble_seed)
        tx_syms = utils.map_bits_to_symbols(tx_bits, mod_type)
        ofdm_sig, n_blks = ofdm_ops.modulate_ofdm_with_pilots(tx_syms, n_fft, nc)
        tx_cp, cp_used = ofdm_ops.add_cyclic_prefix(ofdm_sig, n_blks, n_fft, cp_lengths)
        return tx_cp, cp_used, n_fft, nc, n_fft * df

    def _receive_bits(self, rx_cp, n_fft, nc, cp_used, mod_type, valid_len, scramble_seed):
        rx_no_cp = ofdm_ops.remove_cyclic_prefix(rx_cp, n_fft, cp_used)
        rx_eq, _ = ofdm_ops.demodulate_ofdm_with_pilots(rx_no_cp, n_fft, nc)
        rx_bits_scrambled = utils.demap_symbols_to_bits(rx_eq, mod_type)[:valid_len]
        return utils.apply_scrambling(rx_bits_scrambled, seed=scramble_seed)

    def _is_ci_sufficient(self, estimate, lower, upper):
        half_width = (upper - lower) / 2
        target = max(self.mc_abs_ci_target, abs(estimate) * self.mc_rel_ci_target)
        return half_width <= target

    def _calculate_ber_series(self, tx_bits_raw, bw_idx, profile_idx, mod_type, num_paths, snr_range):
        n_points = len(snr_range)
        bit_errors = np.zeros(n_points, dtype=np.int64)
        total_bits = np.zeros(n_points, dtype=np.int64)
        run_counts = np.zeros(n_points, dtype=np.int64)
        run_ber_values = [[] for _ in range(n_points)]
        active = np.ones(n_points, dtype=bool)
        valid_len = len(tx_bits_raw)
        
        for run_idx in range(self.mc_max_runs):
            scramble_seed = self.mc_seed + run_idx
            rng = np.random.default_rng(self.mc_seed * 10 + run_idx)
            tx_cp, cp_used, n_fft, nc, sample_rate_hz = self._prepare_tx_signal(
                tx_bits_raw, bw_idx, profile_idx, mod_type, scramble_seed
            )
            h_run = channel.generate_rayleigh_channel(
                num_paths,
                rng=rng,
                sample_rate_hz=sample_rate_hz,
            )

            for idx, snr in enumerate(snr_range):
                if not active[idx]:
                    continue

                rx_cp, h = channel.apply_rayleigh(tx_cp, snr, h=h_run, rng=rng)
                rx_bits = self._receive_bits(rx_cp, n_fft, nc, cp_used, mod_type, valid_len, scramble_seed)
                errors = int(np.sum(tx_bits_raw != rx_bits[:valid_len]))
                run_ber = errors / valid_len

                bit_errors[idx] += errors
                total_bits[idx] += valid_len
                run_counts[idx] += 1
                run_ber_values[idx].append(run_ber)

            if run_idx + 1 >= self.mc_min_runs:
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

        ber_values = np.divide(bit_errors, total_bits, out=np.zeros_like(bit_errors, dtype=float), where=total_bits > 0)
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
            "label": config.MODULATION_NAMES[mod_type],
            "mod_type": mod_type,
            "y": ber_values,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "runs": run_counts,
            "total_bits": total_bits,
        }

    def calculate_ber_curve(self, image_path, bw_idx, profile_idx, mod_type=None, num_paths=1):
        """
        Calcula BER vs SNR para QPSK, 16-QAM y 64-QAM con Monte Carlo.

        La opcion de modulacion de la GUI se ignora intencionalmente: esta
        curva siempre compara las tres modulaciones usando la imagen cargada.
        """
        snr_range = np.linspace(0, 30, 10)
        tx_bits_raw, _ = utils.image_to_bits(image_path, self.img_size)

        series = [
            self._calculate_ber_series(tx_bits_raw, bw_idx, profile_idx, current_mod, num_paths, snr_range)
            for current_mod in (1, 2, 3)
        ]

        all_runs = np.concatenate([item["runs"] for item in series])
        min_runs = int(np.min(all_runs))
        max_runs = int(np.max(all_runs))
        config_summary = self._selected_config_summary(bw_idx, profile_idx, num_paths)
        blocks_by_modulation = self._blocks_by_modulation(len(tx_bits_raw), bw_idx, profile_idx)
        block_summary = self._format_blocks_by_modulation(blocks_by_modulation)
        return {
            "x": snr_range,
            "series": series,
            "confidence": 0.95,
            "run_min": min_runs,
            "run_max": max_runs,
            "blocks_by_modulation": blocks_by_modulation,
            "config_summary": config_summary,
            "summary": f"BER Monte Carlo: 3 modulaciones, corridas/punto {min_runs}-{max_runs}, bloques/corrida {block_summary}, IC 95% | {config_summary}",
        }

    def _calculate_papr_values(self, symbols, n_fft, nc):
        symbols = np.asarray(symbols, dtype=np.complex128)
        num_symbols = len(symbols)
        pilot_mask = ofdm_ops.pilot_subcarrier_mask(nc)
        data_mask = ~pilot_mask
        data_per_block = int(np.sum(data_mask))
        num_blocks = int(np.ceil(num_symbols / data_per_block)) if num_symbols else 0
        if num_blocks == 0:
            return np.array([], dtype=float)

        padded = np.zeros(num_blocks * data_per_block, dtype=np.complex128)
        padded[:num_symbols] = symbols
        data_grid = padded.reshape(num_blocks, data_per_block)

        active_grid = np.zeros((num_blocks, nc), dtype=np.complex128)
        active_grid[:, pilot_mask] = ofdm_ops.pilot_symbol_grid(num_blocks, int(np.sum(pilot_mask)))
        active_grid[:, data_mask] = data_grid

        os_fft = n_fft * self.papr_oversampling
        freq_grid = np.zeros((num_blocks, os_fft), dtype=np.complex128)
        freq_grid[:, ofdm_ops.active_subcarrier_indices(os_fft, nc)] = active_grid
        time_grid = np.fft.ifft(freq_grid, axis=1) * np.sqrt(os_fft)

        power = np.abs(time_grid) ** 2
        avg_pwr = np.mean(power, axis=1)
        valid = avg_pwr > 0
        return 10 * np.log10(np.max(power[valid], axis=1) / avg_pwr[valid])

    def _calculate_papr_series(self, tx_bits_raw, bw_idx, profile_idx, mod_type, thresholds=None):
        n_fft, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        tx_bits = utils.apply_scrambling(tx_bits_raw, seed=self.mc_seed)
        syms = utils.map_bits_to_symbols(tx_bits, mod_type)
        papr_values = self._calculate_papr_values(syms, n_fft, nc)

        if thresholds is None:
            return {
                "label": config.MODULATION_NAMES[mod_type],
                "mod_type": mod_type,
                "total_blocks": len(papr_values),
                "papr_values": papr_values,
            }

        exceed_counts = np.sum(papr_values[:, None] > thresholds[None, :], axis=0)
        ccdf = exceed_counts / len(papr_values)

        return {
            "label": config.MODULATION_NAMES[mod_type],
            "mod_type": mod_type,
            "y": ccdf,
            "total_blocks": len(papr_values),
            "papr_values": papr_values,
        }

    def calculate_papr_distribution(self, image_path, bw_idx, profile_idx, mod_type=None):
        """
        Calcula la CCDF empirica del PAPR para QPSK, 16-QAM y 64-QAM.
        """
        tx_bits_raw, _ = utils.image_to_bits(image_path, self.img_size)
        series = [
            self._calculate_papr_series(tx_bits_raw, bw_idx, profile_idx, current_mod)
            for current_mod in (1, 2, 3)
        ]
        max_papr = max(float(np.max(item["papr_values"])) for item in series if item["total_blocks"] > 0)
        thresholds = np.linspace(0, max(12, np.ceil(max_papr) + 1), 120)

        for item in series:
            papr_values = item["papr_values"]
            exceed_counts = np.sum(papr_values[:, None] > thresholds[None, :], axis=0)
            item["y"] = exceed_counts / len(papr_values)

        _, nc, _, _ = utils.get_ofdm_params(bw_idx, profile_idx)
        bw_name = config.LTE_BANDWIDTHS[bw_idx]["name"]
        config_summary = f"BW: {bw_name} ({nc} SC) | CP/canal: no aplican"
        blocks_by_modulation = {item["label"]: item["total_blocks"] for item in series}
        block_summary = self._format_blocks_by_modulation(blocks_by_modulation)
        return {
            "x": thresholds,
            "series": series,
            "oversampling": self.papr_oversampling,
            "blocks_by_modulation": blocks_by_modulation,
            "config_summary": config_summary,
            "summary": f"PAPR empirico: 3 modulaciones, L={self.papr_oversampling}, bloques OFDM {block_summary} | {config_summary}",
        }
