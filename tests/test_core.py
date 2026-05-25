import unittest

import numpy as np

from controller.simulation_mgr import OFDMSimulationManager
from core import channel, ofdm_ops, utils


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

    def test_ofdm_roundtrip_with_variable_cp(self):
        rng = np.random.default_rng(99)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)
        recovered = ofdm_ops.demodulate_ofdm(no_cp, n_fft, nc)[:len(symbols)]

        self.assertTrue(np.allclose(symbols, recovered))

    def test_ofdm_roundtrip_with_pilot_channel_estimation(self):
        rng = np.random.default_rng(19)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)
        recovered, h_est = ofdm_ops.demodulate_ofdm_with_pilots(no_cp, n_fft, nc)

        self.assertTrue(np.allclose(symbols, recovered[:len(symbols)]))
        self.assertEqual(h_est.shape, (num_blocks, nc))
        self.assertEqual(int(np.sum(ofdm_ops.pilot_subcarrier_mask(nc))), nc // 6)

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

    def test_pilot_grid_is_deterministic_and_not_constant(self):
        pilots_a = ofdm_ops.pilot_symbol_grid(8, 12)
        pilots_b = ofdm_ops.pilot_symbol_grid(8, 12)

        self.assertTrue(np.array_equal(pilots_a, pilots_b))
        self.assertTrue(np.allclose(np.abs(pilots_a), 1.0))
        self.assertGreater(len(np.unique(pilots_a)), 1)

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
        self.assertEqual(len(result["time_plot"]["series"]), 2)
        self.assertEqual(len(result["frequency_plot"]["series"]), 2)
        self.assertGreater(len(result["time_plot"]["x"]), 0)
        self.assertGreater(len(result["frequency_plot"]["x"]), 0)
        self.assertLessEqual(len(result["frequency_plot"]["x"]), manager.spectrum_plot_points)

    def test_analysis_curves_return_expected_series(self):
        manager = OFDMSimulationManager()
        manager.img_size = 32
        manager.mc_min_runs = 2
        manager.mc_max_runs = 3

        ber = manager.calculate_ber_curve("imagenes/cameraman.jpg", 4, 1, num_paths=1)
        self.assertEqual([item["label"] for item in ber["series"]], ["QPSK", "16-QAM", "64-QAM"])
        for item in ber["series"]:
            self.assertEqual(len(ber["x"]), len(item["y"]))
            self.assertEqual(len(item["y"]), len(item["ci_lower"]))
            self.assertEqual(len(item["y"]), len(item["ci_upper"]))
            self.assertTrue(np.all(item["ci_lower"] <= item["y"]))
            self.assertTrue(np.all(item["y"] <= item["ci_upper"]))
            self.assertTrue(np.all(item["runs"] >= manager.mc_min_runs))

        papr = manager.calculate_papr_distribution("imagenes/cameraman.jpg", 4, 1)
        self.assertEqual([item["label"] for item in papr["series"]], ["QPSK", "16-QAM", "64-QAM"])
        for item in papr["series"]:
            self.assertEqual(len(papr["x"]), len(item["y"]))
            self.assertGreater(item["total_blocks"], 0)
        self.assertEqual(papr["oversampling"], manager.papr_oversampling)


if __name__ == "__main__":
    unittest.main()
