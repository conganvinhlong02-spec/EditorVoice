"""Torch-free audio helpers for the ONNX speaker encoder.

This is the NumPy equivalent of the small ``torchaudio.compliance.kaldi``
front-end that the original extractor used. Keeping it here makes fresh voice
enrolment work in the minimal ONNX installation without pulling in PyTorch.
"""
from __future__ import annotations

import numpy as np
import soxr


def high_quality_resample(x, orig_sr, target_sr):
    values = np.asarray(x, dtype=np.float32).reshape(-1)
    if int(orig_sr) == int(target_sr):
        return values
    return np.asarray(
        soxr.resample(values, int(orig_sr), int(target_sr), quality="HQ"),
        dtype=np.float32,
    )


def _mel_scale(freq_hz: np.ndarray | float) -> np.ndarray:
    return 1127.0 * np.log1p(np.asarray(freq_hz, dtype=np.float64) / 700.0)


def _mel_filterbank(sample_rate: int, fft_size: int, n_mels: int) -> np.ndarray:
    """Return Kaldi-style triangular mel filters (20 Hz to Nyquist)."""
    frequencies = np.arange(fft_size // 2 + 1, dtype=np.float64) * sample_rate / fft_size
    mel_edges = np.linspace(_mel_scale(20.0), _mel_scale(sample_rate / 2.0), n_mels + 2)
    mel_frequencies = _mel_scale(frequencies)
    filters = np.zeros((n_mels, frequencies.size), dtype=np.float32)
    for index in range(n_mels):
        left, center, right = mel_edges[index : index + 3]
        up = (mel_frequencies - left) / max(center - left, np.finfo(np.float64).eps)
        down = (right - mel_frequencies) / max(right - center, np.finfo(np.float64).eps)
        filters[index] = np.maximum(0.0, np.minimum(up, down)).astype(np.float32)
    return filters


def extract_fbank(
    waveform,
    *,
    sample_rate: int,
    n_mels: int,
    dither: float = 0.0,
    mean_norm: bool = False,
) -> np.ndarray:
    """Extract log-mel features matching Kaldi fbank's common defaults."""
    values = np.asarray(waveform, dtype=np.float32)
    if values.ndim == 2:
        values = values[0]
    elif values.ndim != 1:
        raise ValueError(f"FBank expects a 1D or 2D waveform, got shape {values.shape}.")

    frame_length = int(round(float(sample_rate) * 0.025))
    frame_shift = int(round(float(sample_rate) * 0.010))
    if values.size < frame_length:
        values = np.pad(values, (0, frame_length - values.size))
    frame_count = 1 + (values.size - frame_length) // frame_shift
    starts = np.arange(frame_count)[:, None] * frame_shift
    offsets = np.arange(frame_length)[None, :]
    frames = np.asarray(values[starts + offsets], dtype=np.float32)

    if dither:
        frames += np.random.normal(0.0, float(dither), frames.shape).astype(np.float32)
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= 0.97 * frames[:, :-1]
    frames[:, 0] *= 1.0 - 0.97

    # Kaldi's default "povey" window is Hann raised to 0.85.
    window = np.power(np.hanning(frame_length), 0.85).astype(np.float32)
    frames *= window[None, :]
    fft_size = 1 << (frame_length - 1).bit_length()
    spectrum = np.fft.rfft(frames, n=fft_size, axis=1)
    power = (spectrum.real * spectrum.real + spectrum.imag * spectrum.imag).astype(np.float32)
    filters = _mel_filterbank(int(sample_rate), fft_size, int(n_mels))
    features = np.log(np.maximum(power @ filters.T, np.finfo(np.float32).eps)).astype(np.float32)
    if mean_norm:
        features -= features.mean(axis=0, keepdims=True)
    return features
