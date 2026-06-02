import unittest

import numpy as np

from controller.simulation_mgr import OFDMSimulationManager
from core import channel, config, ofdm_ops, utils


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

    def test_cyclic_prefix_roundtrip_with_pilots(self):
        rng = np.random.default_rng(99)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)

        self.assertTrue(np.allclose(time_signal, no_cp))

    def test_ofdm_roundtrip_with_pilot_channel_estimation(self):
        rng = np.random.default_rng(19)
        bits = rng.integers(0, 2, 8192, dtype=np.uint8)
        symbols = utils.map_bits_to_symbols(bits, 2)
        n_fft, nc, cp_lengths, _ = utils.get_ofdm_params(4, 1)

        time_signal, num_blocks = ofdm_ops.modulate_ofdm_with_pilots(symbols, n_fft, nc)
        with_cp, cp_used = ofdm_ops.add_cyclic_prefix(time_signal, num_blocks, n_fft, cp_lengths)
        no_cp = ofdm_ops.remove_cyclic_prefix(with_cp, n_fft, cp_used)
        recovered, h_est = ofdm_ops.demodulate_ofdm_with_pilots(
            no_cp,
            n_fft,
            nc,
            max_channel_taps=1,
        )

        recovered_bits = utils.demap_symbols_to_bits(recovered, 2)[:len(bits)]
        self.assertTrue(np.array_equal(bits, recovered_bits))
        self.assertEqual(h_est.shape, (num_blocks, nc))
        self.assertEqual(
            int(np.sum(ofdm_ops.pilot_subcarrier_mask(nc))),
            nc // config.PILOT_SPACING_SC,
        )

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

    def test_pilot_grid_is_deterministic_and_not_constant(self):
        pilots_a = ofdm_ops.pilot_symbol_grid(8, 12)
        pilots_b = ofdm_ops.pilot_symbol_grid(8, 12)

        self.assertTrue(np.array_equal(pilots_a, pilots_b))
        self.assertTrue(np.allclose(np.abs(pilots_a), 1.0))
        self.assertGreater(len(np.unique(pilots_a)), 1)

    def test_pilot_masks_are_staggered(self):
        _, nc, _, _ = utils.get_ofdm_params(4, 1)
        first = ofdm_ops.pilot_subcarrier_mask(nc, block_idx=0)
        second = ofdm_ops.pilot_subcarrier_mask(nc, block_idx=1)

        self.assertEqual(int(np.sum(first)), nc // config.PILOT_SPACING_SC)
        self.assertEqual(int(np.sum(second)), nc // config.PILOT_SPACING_SC)
        self.assertFalse(np.array_equal(first, second))
        self.assertTrue(first[0])
        self.assertTrue(second[config.PILOT_STAGGER_OFFSET_SC])

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
        self.assertEqual(result["ofdm_blocks"], 250)
        self.assertNotIn("Modo:", result["info"])
        self.assertIn("Bits:", result["info"])
        self.assertIn("Símbolos:", result["info"])
        self.assertIn("Bloques OFDM: 250", result["info"])
        self.assertIn("SC activas: 600", result["info"])

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
        data_subcarriers = int(np.sum(~ofdm_ops.pilot_subcarrier_mask(nc)))

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
            expected_blocks = int(np.ceil(expected_symbols / data_subcarriers))
            self.assertTrue(result["success"])
            self.assertEqual(result["num_symbols"], expected_symbols)
            self.assertEqual(result["ofdm_blocks"], expected_blocks)

    def test_analysis_curves_return_expected_series(self):
        manager = OFDMSimulationManager()
        manager.img_size = 32
        manager.mc_min_runs = 2
        manager.mc_max_runs = 3
        expected_blocks = {"QPSK": 9, "16-QAM": 5, "64-QAM": 3}

        ber = manager.calculate_ber_curve("imagenes/cameraman.jpg", 4, 1, num_paths=1)
        self.assertEqual([item["label"] for item in ber["series"]], ["QPSK", "16-QAM", "64-QAM"])
        self.assertGreaterEqual(ber["run_min"], manager.mc_min_runs)
        self.assertLessEqual(ber["run_max"], manager.mc_max_runs)
        self.assertEqual(ber["blocks_by_modulation"], expected_blocks)
        self.assertIn("corridas/punto", ber["summary"])
        self.assertIn("bloques/corrida QPSK=9, 16-QAM=5, 64-QAM=3", ber["summary"])
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

        papr = manager.calculate_papr_distribution("imagenes/cameraman.jpg", 4, 1)
        self.assertEqual([item["label"] for item in papr["series"]], ["QPSK", "16-QAM", "64-QAM"])
        self.assertEqual(papr["blocks_by_modulation"], expected_blocks)
        self.assertIn("bloques OFDM QPSK=9, 16-QAM=5, 64-QAM=3", papr["summary"])
        self.assertIn("BW: 10 MHz (600 SC)", papr["summary"])
        self.assertIn("CP/canal: no aplican", papr["summary"])
        for item in papr["series"]:
            self.assertEqual(len(papr["x"]), len(item["y"]))
            self.assertGreater(item["total_blocks"], 0)
        self.assertEqual(papr["oversampling"], manager.papr_oversampling)


if __name__ == "__main__":
    unittest.main()
