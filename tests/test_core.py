import unittest

import numpy as np

from controller.simulation_mgr import OFDMSimulationManager
from core import channel, config, mimo_ops, ofdm_ops, utils


class CoreSimulationTests(unittest.TestCase):
    def test_lte_ofdm_params(self):
        n_fft, nc, cp_lengths, df = utils.get_ofdm_params(4, 1)
        self.assertEqual(n_fft, 1024)
        self.assertEqual(nc, 600)
        self.assertEqual(df, 15_000)
        self.assertEqual(cp_lengths, (80, 72, 72, 72, 72, 72, 72))

        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(5, 2)
        self.assertEqual(n_fft, 1536)
        self.assertEqual(nc, 900)
        self.assertEqual(cp_lengths, (384, 384, 384, 384, 384, 384))

    def test_lte_constellation_reference_points(self):
        self.assertTrue(
            np.allclose(
                utils.map_bits_to_symbols(np.array([0, 1]), 1)[0],
                (1 - 1j) / np.sqrt(2),
            )
        )
        self.assertTrue(
            np.allclose(
                utils.map_bits_to_symbols(np.array([0, 0, 0, 0]), 2)[0],
                (1 + 1j) / np.sqrt(10),
            )
        )
        self.assertTrue(
            np.allclose(
                utils.map_bits_to_symbols(np.array([1, 1, 1, 1]), 2)[0],
                (-3 - 3j) / np.sqrt(10),
            )
        )
        self.assertTrue(
            np.allclose(
                utils.map_bits_to_symbols(np.array([0, 0, 0, 0, 0, 0]), 3)[0],
                (3 + 3j) / np.sqrt(42),
            )
        )

    def test_modulation_roundtrip(self):
        rng = np.random.default_rng(1234)
        for mod_type in (1, 2, 3):
            bits = rng.integers(0, 2, 4096, dtype=np.uint8)
            symbols = utils.map_bits_to_symbols(bits, mod_type)
            recovered = utils.demap_symbols_to_bits(symbols, mod_type)[:len(bits)]
            self.assertTrue(np.array_equal(bits, recovered))

    def test_scrambling_roundtrip(self):
        bits = np.random.default_rng(7).integers(0, 2, 1024, dtype=np.uint8)
        scrambled = utils.apply_scrambling(bits)
        recovered = utils.apply_scrambling(scrambled)
        self.assertTrue(np.array_equal(bits, recovered))

    def test_cyclic_prefix_roundtrip(self):
        rng = np.random.default_rng(99)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)

        self.assertTrue(np.allclose(time_signal, no_cp))

    def test_ofdm_roundtrip_with_direct_channel(self):
        rng = np.random.default_rng(19)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)
        recovered, h_freq = ofdm_ops.demodulate_ofdm_with_channel(
            no_cp,
            n_fft,
            nc,
            h=np.array([1 + 0j], dtype=np.complex128),
        )

        recovered_bits = utils.demap_symbols_to_bits(recovered, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_bits))
        self.assertEqual(h_freq.shape, (nc,))
        self.assertEqual(num_blocks, int(np.ceil(len(symbols) / nc)))

    def test_rayleigh_profile_channel_is_discrete_and_average_normalized(self):
        rng = np.random.default_rng(123)
        n_fft, _, _, df = utils.get_ofdm_params(4, 1)
        h = channel.generate_rayleigh_channel(
            4,
            rng=rng,
            sample_rate_hz=n_fft * df,
            profile_name="ITU Pedestrian A",
        )

        self.assertGreater(len(h), 1)
        self.assertLessEqual(np.count_nonzero(np.abs(h) > 0), 4)

        info = channel.describe_rayleigh_paths(4, n_fft * df, "ITU Pedestrian A")
        self.assertEqual(info["profile_name"], "ITU Pedestrian A")
        self.assertEqual(info["active_paths"], 4)
        self.assertTrue(np.array_equal(info["sample_delays"], np.array([0, 2, 3, 6])))

        energies = [
            np.sum(
                np.abs(
                    channel.generate_rayleigh_channel(
                        4,
                        rng=rng,
                        sample_rate_hz=n_fft * df,
                        profile_name="ITU Pedestrian A",
                    )
                )
                ** 2
            )
            for _ in range(2000)
        ]
        self.assertAlmostEqual(float(np.mean(energies)), 1.0, delta=0.08)
        self.assertGreater(float(np.std(energies)), 0.2)

        _, _, cp_lengths, _ = utils.get_ofdm_params(4, 1)
        report = channel.cp_safety_report(4, cp_lengths, n_fft * df, "ITU Pedestrian A")
        self.assertFalse(report["isi_expected"])
        self.assertEqual(report["margin_samples"], 66)

    def test_didactic_cp_profile_stresses_normal_cp(self):
        n_fft, _, normal_cp, df = utils.get_ofdm_params(4, 1)
        _, _, extended_cp, _ = utils.get_ofdm_params(4, 2)
        sample_rate_hz = n_fft * df

        normal_report = channel.cp_safety_report(
            2, normal_cp, sample_rate_hz, "Didactico CP"
        )
        extended_report = channel.cp_safety_report(
            2, extended_cp, sample_rate_hz, "Didactico CP"
        )

        self.assertTrue(normal_report["isi_expected"])
        self.assertFalse(extended_report["isi_expected"])
        self.assertLess(normal_report["margin_samples"], 0)
        self.assertGreaterEqual(extended_report["margin_samples"], 0)

        h_a = channel.generate_rayleigh_channel(
            2,
            rng=np.random.default_rng(1),
            sample_rate_hz=sample_rate_hz,
            profile_name="Didactico CP",
        )
        h_b = channel.generate_rayleigh_channel(
            2,
            rng=np.random.default_rng(2),
            sample_rate_hz=sample_rate_hz,
            profile_name="Didactico CP",
        )
        self.assertTrue(np.array_equal(h_a, h_b))
        self.assertAlmostEqual(float(np.sum(np.abs(h_a) ** 2)), 1.0)

    def test_mimo_precoders_include_fixed_4x2_mapping(self):
        w_2x2 = ofdm_ops.mimo_precoder_matrix(2, 2, "identity")
        w_4x4 = ofdm_ops.mimo_precoder_matrix(4, 4, "identity")
        w_4x2 = ofdm_ops.mimo_precoder_matrix(4, 2, "tx_repeat")

        expected_4x2 = np.array(
            [
                [1, 0],
                [0, 1],
                [1, 0],
                [0, 1],
            ],
            dtype=np.complex128,
        ) / np.sqrt(2)

        self.assertTrue(np.allclose(w_2x2, np.eye(2)))
        self.assertTrue(np.allclose(w_4x4, np.eye(4)))
        self.assertTrue(np.allclose(w_4x2, expected_4x2))
        self.assertTrue(np.allclose(w_4x2.conj().T @ w_4x2, np.eye(2)))

        with self.assertRaises(ValueError):
            ofdm_ops.mimo_precoder_matrix(4, 2, "identity")

    def test_mimo_didactic_helpers_match_theory(self):
        h_physical = np.array(
            [
                [
                    [1 + 0j, 2 + 0j, 3 + 0j, 4 + 0j],
                    [0.5 + 0j, 1 + 0j, 1.5 + 0j, 2 + 0j],
                ]
            ],
            dtype=np.complex128,
        )
        w_4x2 = mimo_ops.mimo_precoder_matrix(4, 2, "tx_repeat")
        h_eff = mimo_ops.effective_mimo_channel(h_physical, w_4x2)
        expected = np.array(
            [
                [
                    [(1 + 3) / np.sqrt(2), (2 + 4) / np.sqrt(2)],
                    [(0.5 + 1.5) / np.sqrt(2), (1 + 2) / np.sqrt(2)],
                ]
            ],
            dtype=np.complex128,
        )
        self.assertTrue(np.allclose(h_eff, expected))

        order = mimo_ops.layer_order_by_channel_power(h_eff)
        self.assertTrue(np.array_equal(order, np.array([[1, 0]])))

        residual = np.array([[10 + 0j, 5 + 0j]], dtype=np.complex128)
        chosen_layer = np.array([1])
        decided_symbol = np.array([1 + 0j], dtype=np.complex128)
        cancelled = mimo_ops.cancel_detected_layer(
            residual,
            h_eff,
            chosen_layer,
            decided_symbol,
        )
        self.assertTrue(np.allclose(cancelled, residual - h_eff[:, :, 1]))

    def test_mimo_detector_zf_and_mmse_known_channel(self):
        h_matrix = np.array(
            [
                [1.0 + 0.2j, 0.25 - 0.1j],
                [-0.15 + 0.35j, 0.9 - 0.25j],
            ],
            dtype=np.complex128,
        )
        tx_layers = np.array([0.7 - 0.7j, -0.3 + 0.9j], dtype=np.complex128)
        y = h_matrix @ tx_layers

        zf = ofdm_ops.detect_mimo_symbols(y, h_matrix, detector="ZF")
        mmse = ofdm_ops.detect_mimo_symbols(
            y,
            h_matrix,
            detector="MMSE",
            noise_to_signal=0.0,
        )

        self.assertTrue(np.allclose(zf, tx_layers))
        self.assertTrue(np.allclose(mmse, tx_layers))

        h_4x4 = np.array(
            [
                [1.0 + 0.1j, 0.2 - 0.1j, -0.1 + 0.05j, 0.05 + 0.02j],
                [0.1 - 0.2j, 0.9 + 0.05j, 0.15 + 0.1j, -0.05 + 0.04j],
                [-0.05 + 0.1j, 0.18 - 0.04j, 1.1 - 0.1j, 0.12 + 0.08j],
                [0.03 + 0.05j, -0.08 + 0.02j, 0.16 - 0.12j, 0.95 + 0.2j],
            ],
            dtype=np.complex128,
        )
        tx_4x4 = np.array([0.7 - 0.7j, -0.3 + 0.9j, 0.1 + 0.3j, -0.9 - 0.1j])
        y_4x4 = h_4x4 @ tx_4x4

        zf_4x4 = ofdm_ops.detect_mimo_symbols(y_4x4, h_4x4, detector="ZF")
        mmse_4x4 = ofdm_ops.detect_mimo_symbols(y_4x4, h_4x4, detector="MMSE")
        self.assertTrue(np.allclose(zf_4x4, tx_4x4))
        self.assertTrue(np.allclose(mmse_4x4, tx_4x4))

        w_4x2 = ofdm_ops.mimo_precoder_matrix(4, 2, "tx_repeat")
        h_phys = np.array(
            [
                [1.0 + 0.1j, 0.2 - 0.1j, 0.4 + 0.3j, -0.1 + 0.2j],
                [-0.2 + 0.1j, 0.9 - 0.2j, 0.15 + 0.05j, 0.3 + 0.2j],
            ],
            dtype=np.complex128,
        )
        h_eff = h_phys @ w_4x2
        tx_4x2 = np.array([0.7 - 0.7j, -0.3 + 0.9j], dtype=np.complex128)
        y_4x2 = h_eff @ tx_4x2

        mmse_4x2 = ofdm_ops.detect_mimo_symbols(
            y_4x2,
            h_eff,
            detector="MMSE",
            noise_to_signal=0.0,
        )
        self.assertTrue(np.allclose(mmse_4x2, tx_4x2))

    def test_mimo_detector_mmse_sic_known_channel(self):
        h_matrix = np.array(
            [
                [1.0 + 0.2j, 0.25 - 0.1j],
                [-0.15 + 0.35j, 0.9 - 0.25j],
            ],
            dtype=np.complex128,
        )
        tx_layers = utils.map_bits_to_symbols(
            np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=np.uint8),
            2,
        )
        y = h_matrix @ tx_layers

        sic = ofdm_ops.detect_mimo_symbols(
            y,
            h_matrix,
            detector="MMSE-SIC",
            noise_to_signal=0.0,
            mod_type=2,
        )
        self.assertTrue(np.allclose(sic, tx_layers))

        h_4x4 = np.array(
            [
                [1.0 + 0.1j, 0.2 - 0.1j, -0.1 + 0.05j, 0.05 + 0.02j],
                [0.1 - 0.2j, 0.9 + 0.05j, 0.15 + 0.1j, -0.05 + 0.04j],
                [-0.05 + 0.1j, 0.18 - 0.04j, 1.1 - 0.1j, 0.12 + 0.08j],
                [0.03 + 0.05j, -0.08 + 0.02j, 0.16 - 0.12j, 0.95 + 0.2j],
            ],
            dtype=np.complex128,
        )
        tx_4x4 = utils.map_bits_to_symbols(
            np.array(
                [
                    0, 0, 0, 0,
                    0, 1, 0, 1,
                    1, 0, 1, 0,
                    1, 1, 1, 1,
                ],
                dtype=np.uint8,
            ),
            2,
        )
        y_4x4 = h_4x4 @ tx_4x4

        sic_4x4 = ofdm_ops.detect_mimo_symbols(
            y_4x4,
            h_4x4,
            detector="MMSE-SIC",
            noise_to_signal=0.0,
            mod_type=2,
        )
        self.assertTrue(np.allclose(sic_4x4, tx_4x4))

        with self.assertRaises(ValueError):
            ofdm_ops.detect_mimo_symbols(y_4x4, h_4x4, detector="MMSE-SIC")

    def test_mimo_channel_shape_and_reproducibility(self):
        n_fft, _, _, df = utils.get_ofdm_params(4, 1)
        sample_rate_hz = n_fft * df
        h_a = channel.generate_mimo_rayleigh_channel(
            n_tx=2,
            n_rx=2,
            num_taps=2,
            rng=np.random.default_rng(123),
            sample_rate_hz=sample_rate_hz,
        )
        h_b = channel.generate_mimo_rayleigh_channel(
            n_tx=2,
            n_rx=2,
            num_taps=2,
            rng=np.random.default_rng(123),
            sample_rate_hz=sample_rate_hz,
        )

        self.assertEqual(h_a.shape[:2], (2, 2))
        self.assertTrue(np.array_equal(h_a, h_b))
        self.assertGreater(np.count_nonzero(np.abs(h_a) > 0), 0)

        tx = np.ones((2, 128), dtype=np.complex128) / np.sqrt(2)
        rx, h_used = channel.apply_mimo_rayleigh(
            tx,
            40,
            h=h_a,
            rng=np.random.default_rng(5),
        )
        self.assertEqual(rx.shape, (2, 128))
        self.assertTrue(np.array_equal(h_used, h_a))

        h_4_a = channel.generate_mimo_rayleigh_channel(
            n_tx=4,
            n_rx=4,
            num_taps=2,
            rng=np.random.default_rng(456),
            sample_rate_hz=sample_rate_hz,
        )
        h_4_b = channel.generate_mimo_rayleigh_channel(
            n_tx=4,
            n_rx=4,
            num_taps=2,
            rng=np.random.default_rng(456),
            sample_rate_hz=sample_rate_hz,
        )
        self.assertEqual(h_4_a.shape[:2], (4, 4))
        self.assertTrue(np.array_equal(h_4_a, h_4_b))

        tx_4 = np.ones((4, 128), dtype=np.complex128) / 2
        rx_4, h_4_used = channel.apply_mimo_rayleigh(
            tx_4,
            40,
            h=h_4_a,
            rng=np.random.default_rng(5),
        )
        self.assertEqual(rx_4.shape, (4, 128))
        self.assertTrue(np.array_equal(h_4_used, h_4_a))

        h_4x2_a = channel.generate_mimo_rayleigh_channel(
            n_tx=4,
            n_rx=2,
            num_taps=2,
            rng=np.random.default_rng(789),
            sample_rate_hz=sample_rate_hz,
        )
        h_4x2_b = channel.generate_mimo_rayleigh_channel(
            n_tx=4,
            n_rx=2,
            num_taps=2,
            rng=np.random.default_rng(789),
            sample_rate_hz=sample_rate_hz,
        )
        self.assertEqual(h_4x2_a.shape[:2], (2, 4))
        self.assertTrue(np.array_equal(h_4x2_a, h_4x2_b))

        tx_4x2 = np.ones((4, 128), dtype=np.complex128) / 2
        rx_4x2, h_4x2_used = channel.apply_mimo_rayleigh(
            tx_4x2,
            40,
            h=h_4x2_a,
            rng=np.random.default_rng(5),
        )
        self.assertEqual(rx_4x2.shape, (2, 128))
        self.assertTrue(np.array_equal(h_4x2_used, h_4x2_a))

    def test_mimo_ofdm_roundtrip_with_direct_channel(self):
        rng = np.random.default_rng(41)
        bits = rng.integers(0, 2, 4096, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        tx_time, num_blocks = ofdm_ops.modulate_mimo_ofdm(
            symbols,
            n_fft,
            nc,
            n_tx=2,
        )
        tx_with_cp = []
        cp_used = None
        for tx_idx in range(2):
            with_cp, cp_single = ofdm_ops.add_cyclic_prefix(
                tx_time[tx_idx],
                num_blocks,
                n_fft,
                cp_lengths,
            )
            cp_used = cp_single if cp_used is None else cp_used
            tx_with_cp.append(with_cp)

        rx_no_cp = np.vstack(
            [
                ofdm_ops.remove_cyclic_prefix(tx_with_cp[rx_idx], n_fft, cp_used)
                for rx_idx in range(2)
            ]
        )
        h = np.eye(2, dtype=np.complex128)[:, :, None]
        recovered, h_freq = ofdm_ops.demodulate_mimo_ofdm_with_channel(
            rx_no_cp,
            n_fft,
            nc,
            h,
            n_tx=2,
            detector="ZF",
        )

        recovered_bits = utils.demap_symbols_to_bits(recovered, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_bits))
        self.assertEqual(h_freq.shape, (nc, 2, 2))

    def test_mimo_4x4_ofdm_roundtrip_with_direct_channel(self):
        rng = np.random.default_rng(42)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        tx_time, num_blocks = ofdm_ops.modulate_mimo_ofdm(
            symbols,
            n_fft,
            nc,
            n_tx=4,
        )
        tx_with_cp = []
        cp_used = None
        for tx_idx in range(4):
            with_cp, cp_single = ofdm_ops.add_cyclic_prefix(
                tx_time[tx_idx],
                num_blocks,
                n_fft,
                cp_lengths,
            )
            cp_used = cp_single if cp_used is None else cp_used
            tx_with_cp.append(with_cp)

        rx_no_cp = np.vstack(
            [
                ofdm_ops.remove_cyclic_prefix(tx_with_cp[rx_idx], n_fft, cp_used)
                for rx_idx in range(4)
            ]
        )
        h = np.eye(4, dtype=np.complex128)[:, :, None]
        recovered, h_freq = ofdm_ops.demodulate_mimo_ofdm_with_channel(
            rx_no_cp,
            n_fft,
            nc,
            h,
            n_tx=4,
            detector="ZF",
        )

        recovered_bits = utils.demap_symbols_to_bits(recovered, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_bits))
        self.assertEqual(h_freq.shape, (nc, 4, 4))

        recovered_sic, h_freq_sic = ofdm_ops.demodulate_mimo_ofdm_with_channel(
            rx_no_cp,
            n_fft,
            nc,
            h,
            n_tx=4,
            detector="MMSE-SIC",
            mod_type=2,
        )
        recovered_sic_bits = utils.demap_symbols_to_bits(recovered_sic, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_sic_bits))
        self.assertEqual(h_freq_sic.shape, (nc, 4, 4))

    def test_mimo_4x2_ofdm_roundtrip_with_precoder(self):
        rng = np.random.default_rng(43)
        bits = rng.integers(0, 2, 4096, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)
        w_4x2 = ofdm_ops.mimo_precoder_matrix(4, 2, "tx_repeat")

        tx_time, num_blocks = ofdm_ops.modulate_mimo_ofdm(
            symbols,
            n_fft,
            nc,
            n_tx=4,
            n_layers=2,
            precoder=w_4x2,
        )
        tx_with_cp = []
        cp_used = None
        for tx_idx in range(4):
            with_cp, cp_single = ofdm_ops.add_cyclic_prefix(
                tx_time[tx_idx],
                num_blocks,
                n_fft,
                cp_lengths,
            )
            cp_used = cp_single if cp_used is None else cp_used
            tx_with_cp.append(with_cp)

        tx_no_cp = np.vstack(
            [
                ofdm_ops.remove_cyclic_prefix(tx_with_cp[tx_idx], n_fft, cp_used)
                for tx_idx in range(4)
            ]
        )
        h_phys = w_4x2.conj().T
        rx_no_cp = h_phys @ tx_no_cp

        h = h_phys[:, :, None]
        recovered, h_freq = ofdm_ops.demodulate_mimo_ofdm_with_channel(
            rx_no_cp,
            n_fft,
            nc,
            h,
            n_tx=4,
            n_layers=2,
            precoder=w_4x2,
            detector="MMSE",
        )
        recovered_bits = utils.demap_symbols_to_bits(recovered, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_bits))
        self.assertEqual(h_freq.shape, (nc, 2, 4))

        recovered_sic, _ = ofdm_ops.demodulate_mimo_ofdm_with_channel(
            rx_no_cp,
            n_fft,
            nc,
            h,
            n_tx=4,
            n_layers=2,
            precoder=w_4x2,
            detector="MMSE-SIC",
            mod_type=2,
        )
        recovered_sic_bits = utils.demap_symbols_to_bits(recovered_sic, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_sic_bits))

    def test_manager_smoke(self):
        manager = OFDMSimulationManager()
        result = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            25,
            1,
            rng_seed=manager.mc_seed,
        )
        self.assertTrue(result["success"])
        self.assertLess(result["ber"], 1e-3)
        self.assertEqual(result["total_bits"], manager.img_size * manager.img_size * 8)
        self.assertEqual(result["num_symbols"], result["total_bits"] // 4)
        self.assertEqual(result["ofdm_blocks"], 209)
        self.assertEqual(result["mimo_mode_name"], "SISO 1x1")
        self.assertEqual(result["num_layers"], 1)
        self.assertAlmostEqual(result["gross_data_rate_mbps"], 33.6)
        self.assertIn("Bits:", result["info"])
        self.assertIn("Simbolos:", result["info"])
        self.assertIn("Modo: SISO 1x1", result["info"])
        self.assertIn("Bloques OFDM: 209", result["info"])
        self.assertIn("SC activas: 600", result["info"])

    def test_manager_mimo_transmission_smoke(self):
        manager = OFDMSimulationManager()
        manager.img_size = 16
        result = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            45,
            1,
            rng_seed=manager.mc_seed,
            mimo_mode=2,
            detector=2,
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertLess(result["ber"], 1e-2)
        self.assertEqual(result["mimo_mode_name"], "SM 2x2")
        self.assertEqual(result["detector"], "MMSE")
        self.assertEqual(result["num_layers"], 2)
        self.assertEqual(result["data_subcarriers_per_layer"], 600)
        self.assertEqual(result["throughput_factor"], 2.0)
        self.assertAlmostEqual(result["gross_data_rate_mbps"], 67.2)
        self.assertIn("Modo: SM 2x2", result["info"])
        self.assertIn("Detector: MMSE", result["info"])
        self.assertNotIn("T_OFDM:", result["info"])
        self.assertNotIn("T_LTE:", result["info"])

    def test_manager_mimo_4x2_transmission_smoke(self):
        manager = OFDMSimulationManager()
        manager.img_size = 16
        result = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            55,
            1,
            rng_seed=manager.mc_seed,
            mimo_mode=4,
            detector=2,
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertLess(result["ber"], 1e-2)
        self.assertEqual(result["mimo_mode_name"], "SM 4x2")
        self.assertEqual(result["detector"], "MMSE")
        self.assertEqual(result["n_tx"], 4)
        self.assertEqual(result["n_rx"], 2)
        self.assertEqual(result["num_layers"], 2)
        self.assertEqual(result["data_subcarriers_per_layer"], 600)
        self.assertAlmostEqual(result["throughput_factor"], 2.0)
        self.assertAlmostEqual(result["gross_data_rate_mbps"], 67.2)
        self.assertIn("Modo: SM 4x2", result["info"])
        self.assertIn("Antenas: 4x2", result["info"])

    def test_manager_mimo_4x4_transmission_smoke(self):
        manager = OFDMSimulationManager()
        manager.img_size = 16
        result = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            55,
            1,
            rng_seed=manager.mc_seed,
            mimo_mode=3,
            detector=2,
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertLess(result["ber"], 1e-2)
        self.assertEqual(result["mimo_mode_name"], "SM 4x4")
        self.assertEqual(result["detector"], "MMSE")
        self.assertEqual(result["n_tx"], 4)
        self.assertEqual(result["n_rx"], 4)
        self.assertEqual(result["num_layers"], 4)
        self.assertEqual(result["data_subcarriers_per_layer"], 600)
        self.assertEqual(result["throughput_factor"], 4.0)
        self.assertAlmostEqual(result["gross_data_rate_mbps"], 134.4)
        self.assertGreater(result["ideal_capacity_bpshz"], 0.0)
        self.assertIn("Modo: SM 4x4", result["info"])
        self.assertIn("Antenas: 4x4", result["info"])

    def test_manager_mimo_sic_transmission_smoke(self):
        manager = OFDMSimulationManager()
        manager.img_size = 16
        result = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            55,
            1,
            rng_seed=manager.mc_seed,
            mimo_mode=3,
            detector=3,
        )

        self.assertTrue(result["success"], result.get("error"))
        self.assertLess(result["ber"], 1e-2)
        self.assertEqual(result["mimo_mode_name"], "SM 4x4")
        self.assertEqual(result["detector"], "MMSE-SIC")
        self.assertIn("Detector: MMSE-SIC", result["info"])

    def test_manual_transmission_default_seed_is_reproducible(self):
        manager = OFDMSimulationManager()
        manager.img_size = 32

        first = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            15,
            2,
        )
        second = manager.run_image_transmission(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            15,
            2,
        )

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(first["rng_seed"], manager.image_tx_seed)
        self.assertEqual(second["rng_seed"], manager.image_tx_seed)
        self.assertEqual(first["ber"], second["ber"])
        self.assertTrue(np.array_equal(first["rx_image"], second["rx_image"]))

    def test_transmission_symbol_count_depends_on_modulation(self):
        manager = OFDMSimulationManager()
        manager.img_size = 16
        bits_per_symbol = {1: 2, 2: 4, 3: 6}
        _, nc, _, _ = utils.get_ofdm_params(4, 1)

        for mod_type, n_bits in bits_per_symbol.items():
            result = manager.run_image_transmission(
                "imagenes/cameraman.jpg",
                4,
                1,
                mod_type,
                30,
                1,
                rng_seed=manager.mc_seed,
            )
            expected_symbols = int(np.ceil(result["total_bits"] / n_bits))
            expected_blocks = int(np.ceil(expected_symbols / nc))
            self.assertTrue(result["success"])
            self.assertEqual(result["num_symbols"], expected_symbols)
            self.assertEqual(result["ofdm_blocks"], expected_blocks)

    def test_analysis_curves_return_expected_series(self):
        manager = OFDMSimulationManager()
        manager.img_size = 32
        manager.mc_min_runs = 2
        manager.mc_max_runs = 3
        manager.ber_random_bits = 8192
        expected_blocks = {"QPSK": 7, "16-QAM": 4, "64-QAM": 3}

        ber = manager.calculate_ber_curve(None, 4, 1, num_paths=1)
        self.assertEqual([item["label"] for item in ber["series"]], ["QPSK", "16-QAM", "64-QAM"])
        self.assertGreaterEqual(ber["run_min"], manager.mc_min_runs)
        self.assertLessEqual(ber["run_max"], manager.mc_max_runs)
        self.assertEqual(ber["blocks_by_modulation"], expected_blocks)
        self.assertEqual(ber["payload_bits"], 8192)
        self.assertIn("corridas/punto", ber["summary"])
        self.assertIn("bits aleatorios", ber["summary"])
        self.assertIn("bloques/corrida QPSK=7, 16-QAM=4, 64-QAM=3", ber["summary"])
        self.assertIn("BW: 10 MHz (600 SC)", ber["summary"])
        self.assertIn("CP: Normal", ber["summary"])
        self.assertIn(f"Canal: {channel.DEFAULT_RAYLEIGH_PROFILE}, caminos: 1", ber["summary"])
        for item in ber["series"]:
            self.assertEqual(len(ber["x"]), len(item["y"]))
            self.assertEqual(len(item["y"]), len(item["ci_lower"]))
            self.assertEqual(len(item["y"]), len(item["ci_upper"]))
            self.assertTrue(np.all(item["ci_lower"] <= item["y"]))
            self.assertTrue(np.all(item["y"] <= item["ci_upper"]))
            self.assertTrue(np.all(item["runs"] >= manager.mc_min_runs))

        mimo = manager.calculate_mimo_comparison(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            num_paths=1,
        )
        self.assertEqual(
            [item["label"] for item in mimo["series"]],
            [
                "2x2 MMSE",
                "4x2 MMSE",
                "4x4 MMSE",
                "2x2 SIC",
                "4x2 SIC",
                "4x4 SIC",
            ],
        )
        self.assertEqual(len({item["color"] for item in mimo["series"]}), 6)
        self.assertEqual([item["marker"] for item in mimo["series"][:3]], ["o", "o", "o"])
        self.assertEqual([item["marker"] for item in mimo["series"][3:]], ["s", "s", "s"])
        self.assertEqual(
            mimo["blocks_by_mode"],
            {
                "2x2 MMSE": 2,
                "4x2 MMSE": 2,
                "4x4 MMSE": 1,
                "2x2 SIC": 2,
                "4x2 SIC": 2,
                "4x4 SIC": 1,
            },
        )
        self.assertIn("Comparacion multiantena: 16-QAM, maximo de capas", mimo["summary"])
        self.assertIn("bits aleatorios 8192", mimo["summary"])
        self.assertIn("2x2 MMSE=2", mimo["summary"])
        self.assertIn("4x2 MMSE=2", mimo["summary"])
        self.assertIn("4x4 MMSE=1", mimo["summary"])
        self.assertNotIn("tiempo aprox", mimo["summary"])
        self.assertIn("capas 2x2 MMSE=2, 4x2 MMSE=2, 4x4 MMSE=4", mimo["summary"])
        self.assertIn("BW: 10 MHz (600 SC)", mimo["summary"])
        self.assertEqual(mimo["rank_mode"], "max")
        self.assertEqual(mimo["rank_label"], "maximo de capas")
        self.assertAlmostEqual(mimo["throughput_by_mode"]["4x4 MMSE"], 4.0)
        self.assertNotIn("airtime_ms_by_mode", mimo)
        self.assertEqual(mimo["modulation"], "16-QAM")
        self.assertTrue(np.array_equal(mimo["x"], np.array([5, 10, 15, 20, 25, 30], dtype=float)))
        for item in mimo["series"]:
            self.assertEqual(len(mimo["x"]), len(item["y"]))
            self.assertEqual(len(item["y"]), len(item["ci_lower"]))
            self.assertEqual(len(item["y"]), len(item["ci_upper"]))

        fair_mimo = manager.calculate_mimo_comparison(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            num_paths=1,
            rank_mode="rank2",
        )
        self.assertEqual(
            [item["label"] for item in fair_mimo["series"]],
            [
                "2x2 MMSE",
                "4x2 MMSE",
                "4x4 MMSE",
                "2x2 SIC",
                "4x2 SIC",
                "4x4 SIC",
            ],
        )
        self.assertEqual(fair_mimo["rank_mode"], "rank2")
        self.assertEqual(fair_mimo["rank_label"], "2 capas")
        self.assertEqual(fair_mimo["blocks_by_mode"]["4x4 MMSE"], 2)
        self.assertAlmostEqual(fair_mimo["throughput_by_mode"]["4x4 MMSE"], 2.0)
        self.assertNotIn("airtime_ms_by_mode", fair_mimo)

        visual = manager.calculate_mimo_visual_comparison(
            "imagenes/cameraman.jpg",
            4,
            1,
            2,
            30,
            num_paths=1,
        )
        self.assertEqual(
            [item["label"] for item in visual["scenarios"]],
            [
                "2x2 MMSE",
                "4x2 MMSE",
                "4x4 MMSE",
                "2x2 SIC",
                "4x2 SIC",
                "4x4 SIC",
            ],
        )
        for item in visual["scenarios"]:
            self.assertTrue(item["success"])
            self.assertNotIn("tx_time_ms", item)
            self.assertNotIn("lte_time_ms", item)
            self.assertNotIn("sim_runtime_ms", item)
            self.assertEqual(item["rx_image"].shape, (manager.img_size, manager.img_size))


if __name__ == "__main__":
    unittest.main()
