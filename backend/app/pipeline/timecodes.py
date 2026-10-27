import math
import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from app.models import TranscriptSegment

STEM_LENGTH = 5
MIN_WORD_LENGTH = 3
MIN_EVIDENCE_STEMS = 3
EVIDENCE_MATCH_RATIO = 0.6
OVERLAP_MATCH_RATIO = 0.2
OVERLAP_MIN_STEMS = 2
WINDOW_SIZES = (1, 2)


@dataclass(frozen=True)
class Candidate:
    score: float
    size: int
    distance: float
    position: int


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold().replace("ё", "е"))


def stems(text: str) -> set[str]:
    return {word[:STEM_LENGTH] for word in words(text) if len(word) >= MIN_WORD_LENGTH}


def distance_to(hint: float | None, start: float) -> float:
    return abs(start - hint) if hint is not None else 0.0


def find_exact(
    segments: Sequence[TranscriptSegment], evidence: str, hint: float | None
) -> TranscriptSegment | None:
    needle = words(evidence)
    if len(needle) < 2:
        return None
    joined = " "
    offsets: list[int] = []
    owners: list[TranscriptSegment] = []
    for segment in segments:
        tokens = words(segment.text)
        if not tokens:
            continue
        offsets.append(len(joined))
        owners.append(segment)
        joined += " ".join(tokens) + " "
    pattern = " " + " ".join(needle) + " "
    found: list[TranscriptSegment] = []
    position = joined.find(pattern)
    while position != -1:
        found.append(owners[bisect_right(offsets, position + 1) - 1])
        position = joined.find(pattern, position + 1)
    if not found:
        return None
    return min(found, key=lambda segment: distance_to(hint, segment.start))


def best_window(
    segments: Sequence[TranscriptSegment],
    segment_stems: list[set[str]],
    query: set[str],
    weights: dict[str, float],
    min_ratio: float,
    min_matched: int,
    hint: float | None,
) -> TranscriptSegment | None:
    total = sum(weights[stem] for stem in query)
    if not query or total <= 0:
        return None
    candidates: list[Candidate] = []
    for size in WINDOW_SIZES:
        for position in range(len(segments) - size + 1):
            window = set().union(*segment_stems[position : position + size])
            matched = query & window
            if len(matched) < min_matched:
                continue
            score = sum(weights[stem] for stem in matched) / total
            if score >= min_ratio:
                candidates.append(
                    Candidate(
                        score,
                        size,
                        distance_to(hint, segments[position].start),
                        position,
                    )
                )
    if not candidates:
        return None
    best = min(candidates, key=lambda c: (-round(c.score, 6), c.size, c.distance, c.position))
    return segments[best.position]


def stem_weights(segment_stems: list[set[str]], query: set[str]) -> dict[str, float]:
    count = max(len(segment_stems), 1)
    weights: dict[str, float] = {}
    for stem in query:
        frequency = sum(1 for known in segment_stems if stem in known)
        weights[stem] = math.log(1 + count / (1 + frequency))
    return weights


def snap_to_start(segments: Sequence[TranscriptSegment], hint: float) -> float | None:
    if not segments:
        return None
    nearest = min(segments, key=lambda segment: abs(segment.start - hint))
    if hint == 0 and nearest.start != 0:
        return None
    return nearest.start


def locate_timestamp(
    segments: Sequence[TranscriptSegment],
    evidence: str,
    question: str,
    explanation: str,
    hint: float | None,
) -> float | None:
    if not segments:
        return None
    exact = find_exact(segments, evidence, hint)
    if exact is not None:
        return exact.start
    segment_stems = [stems(segment.text) for segment in segments]
    evidence_stems = stems(evidence)
    if len(evidence_stems) >= MIN_EVIDENCE_STEMS:
        weights = stem_weights(segment_stems, evidence_stems)
        match = best_window(
            segments,
            segment_stems,
            evidence_stems,
            weights,
            EVIDENCE_MATCH_RATIO,
            MIN_EVIDENCE_STEMS,
            hint,
        )
        if match is not None:
            return match.start
    query = stems(f"{explanation} {question}")
    weights = stem_weights(segment_stems, query)
    match = best_window(
        segments, segment_stems, query, weights, OVERLAP_MATCH_RATIO, OVERLAP_MIN_STEMS, hint
    )
    if match is not None:
        return match.start
    if hint is None:
        return None
    return snap_to_start(segments, hint)
