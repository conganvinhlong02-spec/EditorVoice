"""Small audio helpers used by the dependency-light Quick Studio app."""

from __future__ import annotations

import os
import wave

import numpy as np


MIN_SPEECH_SPEED = 0.75
MAX_SPEECH_SPEED = 1.25


def pcm_wav_duration(path: str | os.PathLike[str]) -> float:
    """Return the duration of a non-empty PCM WAV file.

    Quick Studio stores browser-generated recordings in its local history.  Use
    the standard-library WAV parser instead of trusting the upload's extension
    or client-reported duration, so corrupt/non-audio payloads never enter the
    history directory.
    """
    try:
        with wave.open(os.fspath(path), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            channel_count = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            compression = wav_file.getcomptype()
    except (EOFError, OSError, wave.Error) as exc:
        raise ValueError("invalid WAV file") from exc

    if (
        compression != "NONE"
        or frame_rate <= 0
        or frame_count <= 0
        or channel_count not in (1, 2)
        or sample_width not in (1, 2, 3, 4)
    ):
        raise ValueError("WAV file must contain mono or stereo PCM audio")
    return frame_count / frame_rate


def master_for_podcast(audio: np.ndarray, sample_rate: int = 48_000) -> np.ndarray:
    """Apply a transparent, speech-safe final master for Studio Podcast renders.

    This deliberately avoids reverb, artificial bass, and aggressive compression:
    those effects tend to make synthesized speech metallic.  It removes inaudible
    DC/very-low-frequency rumble, sets a consistent speech level, protects peaks,
    and adds short edge fades so exported WAV files start and end cleanly.
    """
    values = np.asarray(audio, dtype=np.float32).reshape(-1).copy()
    if values.size == 0:
        return values

    # One-pole 45 Hz high-pass filter.  It is gentle enough to preserve vocal
    # body while suppressing low-frequency movement that is perceived as rumble.
    pole = float(np.exp(-2.0 * np.pi * 45.0 / sample_rate))
    filtered = np.empty_like(values)
    previous_input = 0.0
    previous_output = 0.0
    for index, sample in enumerate(values):
        output = sample - previous_input + pole * previous_output
        filtered[index] = output
        previous_input = float(sample)
        previous_output = float(output)

    # Normalize conservatively towards a podcast-friendly level (about -19 dB
    # RMS), never boosting more than 3.5 dB.  Peak protection is applied after.
    rms = float(np.sqrt(np.mean(np.square(filtered), dtype=np.float64)))
    if rms > 1e-5:
        gain = min(1.5, max(0.72, 0.112 / rms))
        filtered *= gain
    peak = float(np.max(np.abs(filtered)))
    if peak > 0.94:
        filtered *= 0.94 / peak

    fade_samples = min(max(1, int(sample_rate * 0.008)), filtered.size // 2)
    if fade_samples:
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        filtered[:fade_samples] *= fade
        filtered[-fade_samples:] *= fade[::-1]
    return np.clip(filtered, -1.0, 1.0).astype(np.float32, copy=False)


def time_stretch(audio: np.ndarray, speed: float, sample_rate: int = 48_000) -> np.ndarray:
    """Change duration while keeping speech pitch approximately unchanged.

    This compact WSOLA-style overlap/add implementation keeps Quick Studio's
    installation lightweight and is tuned for the modest range exposed by the
    UI.
    """
    speed = float(speed)
    if not MIN_SPEECH_SPEED <= speed <= MAX_SPEECH_SPEED:
        raise ValueError(
            f"speech speed must be between {MIN_SPEECH_SPEED} and {MAX_SPEECH_SPEED}"
        )

    values = np.asarray(audio, dtype=np.float32).reshape(-1)
    if values.size == 0 or abs(speed - 1.0) < 1e-3:
        return values.copy()

    target_length = max(1, int(round(values.size / speed)))
    if float(np.max(np.abs(values))) < 1e-6:
        return np.zeros(target_length, dtype=np.float32)

    # A 42.7 ms Hann window gives speech enough periodic context while the
    # 10.7 ms synthesis hop keeps joins smooth at 48 kHz.
    window_size = min(2_048, values.size)
    if window_size < 512 or target_length <= window_size:
        positions = np.linspace(0, values.size - 1, target_length, dtype=np.float64)
        return np.interp(positions, np.arange(values.size), values).astype(np.float32)

    synthesis_hop = max(128, int(round(sample_rate * 0.0107)))
    synthesis_hop = min(synthesis_hop, window_size // 2)
    search_radius = min(int(round(sample_rate * 0.0053)), window_size // 4)
    search_step = max(4, int(round(sample_rate / 3_000)))
    similarity_size = min(512, window_size - synthesis_hop)
    # Avoid exact zeroes at the two boundaries so the first and last samples
    # remain represented after overlap/add normalization.
    window = np.hanning(window_size + 2)[1:-1].astype(np.float32)

    output = np.zeros(target_length, dtype=np.float32)
    weights = np.zeros(target_length, dtype=np.float32)

    output[:window_size] += values[:window_size] * window
    weights[:window_size] += window

    input_position = 0
    max_input_position = max(0, values.size - window_size)
    max_output_position = target_length - window_size
    similarity_offsets = np.arange(similarity_size)

    # Map synthesis positions across the complete source instead of repeatedly
    # adding a relative analysis hop. Relative matching can keep selecting an
    # earlier, equally periodic speech cycle and eventually omit the sentence
    # ending. The absolute mapping below always anchors the final frame to the
    # final input frame, so no words are cut off.
    output_positions = list(range(synthesis_hop, max_output_position, synthesis_hop))
    output_positions.append(max_output_position)
    for output_position in output_positions:
        is_last = output_position == max_output_position
        predicted = int(round(output_position * max_input_position / max_output_position))
        if is_last:
            candidates = np.array([max_input_position], dtype=np.int64)
        else:
            candidate_start = max(input_position + 1, predicted - search_radius)
            candidate_end = min(max_input_position - 1, predicted + search_radius)
            if candidate_start > candidate_end:
                candidate_start = candidate_end = min(max_input_position, max(input_position + 1, predicted))

            candidates = np.arange(candidate_start, candidate_end + 1, search_step)
            if candidates.size == 0 or candidates[-1] != candidate_end:
                candidates = np.append(candidates, candidate_end)

        overlap_weight = weights[output_position : output_position + similarity_size]
        reference = output[output_position : output_position + similarity_size] / np.maximum(
            overlap_weight, 1e-6
        )
        reference_norm = float(np.linalg.norm(reference))
        if candidates.size > 1 and reference_norm > 1e-6:
            segments = values[candidates[:, None] + similarity_offsets]
            norms = np.linalg.norm(segments, axis=1) * reference_norm
            scores = np.divide(
                segments @ reference,
                norms,
                out=np.full(candidates.size, -1.0, dtype=np.float32),
                where=norms > 1e-6,
            )
            # Prefer the timing prediction when several periodic cycles have
            # almost identical correlation; this prevents cumulative drift.
            scores -= 0.08 * np.abs(candidates - predicted) / max(search_radius, 1)
            input_position = int(candidates[int(np.argmax(scores))])
        else:
            input_position = int(candidates[np.argmin(np.abs(candidates - predicted))])

        output[output_position : output_position + window_size] += (
            values[input_position : input_position + window_size] * window
        )
        weights[output_position : output_position + window_size] += window

    stretched = np.divide(
        output,
        weights,
        out=np.zeros(target_length, dtype=np.float32),
        where=weights > 1e-5,
    )
    return np.clip(stretched, -1.0, 1.0).astype(np.float32, copy=False)
