import numpy as np
import unittest

from apps.quick_studio_audio import master_for_podcast, time_stretch


class QuickStudioAudioTests(unittest.TestCase):
    sample_rate = 48_000

    def setUp(self):
        timeline = np.arange(self.sample_rate, dtype=np.float32) / self.sample_rate
        self.audio = np.sin(2 * np.pi * 220 * timeline).astype(np.float32) * 0.2

    def test_time_stretch_changes_duration(self):
        for speed in (0.75, 0.9, 1.0, 1.1, 1.25):
            with self.subTest(speed=speed):
                stretched = time_stretch(self.audio, speed, self.sample_rate)
                self.assertEqual(len(stretched), round(len(self.audio) / speed))
                self.assertEqual(stretched.dtype, np.float32)
                self.assertTrue(np.isfinite(stretched).all())

    def test_time_stretch_preserves_pitch(self):
        stretched = time_stretch(self.audio, 1.25, self.sample_rate)
        spectrum = np.abs(np.fft.rfft(stretched * np.hanning(len(stretched))))
        dominant_hz = np.fft.rfftfreq(len(stretched), 1 / self.sample_rate)[
            int(np.argmax(spectrum))
        ]
        self.assertAlmostEqual(dominant_hz, 220, delta=4)

    def test_fast_speed_keeps_the_sentence_ending(self):
        timeline = np.arange(self.sample_rate, dtype=np.float32) / self.sample_rate
        audio = np.sin(2 * np.pi * 220 * timeline).astype(np.float32) * 0.2
        tail_size = 4_800
        audio[-tail_size:] = (
            np.sin(2 * np.pi * 880 * timeline[-tail_size:]).astype(np.float32) * 0.2
        )

        stretched = time_stretch(audio, 1.25, self.sample_rate)
        ending = stretched[-2_000:]
        spectrum = np.abs(np.fft.rfft(ending * np.hanning(len(ending))))
        dominant_hz = np.fft.rfftfreq(len(ending), 1 / self.sample_rate)[
            int(np.argmax(spectrum))
        ]
        self.assertAlmostEqual(dominant_hz, 880, delta=25)

    def test_fast_speed_keeps_all_sections_in_order(self):
        section_size = self.sample_rate // 2
        timeline = np.arange(section_size, dtype=np.float32) / self.sample_rate
        frequencies = (220, 330, 440, 550)
        audio = np.concatenate(
            [
                np.sin(2 * np.pi * frequency * timeline).astype(np.float32) * 0.2
                for frequency in frequencies
            ]
        )

        stretched = time_stretch(audio, 1.25, self.sample_rate)
        for index, expected_hz in enumerate(frequencies):
            center = round(len(stretched) * ((index + 0.5) / len(frequencies)))
            section = stretched[center - 1_500 : center + 1_500]
            spectrum = np.abs(np.fft.rfft(section * np.hanning(len(section))))
            dominant_hz = np.fft.rfftfreq(len(section), 1 / self.sample_rate)[
                int(np.argmax(spectrum))
            ]
            with self.subTest(section=index):
                self.assertAlmostEqual(dominant_hz, expected_hz, delta=12)

    def test_time_stretch_rejects_out_of_range_speed(self):
        with self.assertRaises(ValueError):
            time_stretch(np.ones(1_000, dtype=np.float32), 1.5)

    def test_podcast_master_is_finite_and_peak_safe(self):
        audio = self.audio.copy()
        audio[0] = 0.8
        audio[-1] = -0.8
        mastered = master_for_podcast(audio, self.sample_rate)
        self.assertEqual(mastered.dtype, np.float32)
        self.assertEqual(len(mastered), len(audio))
        self.assertTrue(np.isfinite(mastered).all())
        self.assertLessEqual(float(np.max(np.abs(mastered))), 0.9401)
        self.assertAlmostEqual(float(mastered[0]), 0.0, places=6)
        self.assertAlmostEqual(float(mastered[-1]), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
