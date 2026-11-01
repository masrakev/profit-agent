"""An owner's voice clip: the format the transcription endpoint accepts, and the product's limits.

Accepted: RIFF/WAVE, mono, 16-bit integer PCM at 16 or 24 kHz, the only input of Muse Voice
Transcribe's file endpoint (other recordings are converted first, e.g. `ffmpeg -i in.m4a -ac 1
-ar 24000 -c:a pcm_s16le -map_metadata -1 out.wav`). Limits: two minutes, and `MAX_BYTES`, two
minutes at 24 kHz with room for the header. A clip is checked before anything is called, so a
refused clip costs nothing.
"""

from app.agent.llm.errors import InvalidRequestError
from app.agent.llm.transcribe import WavInfo, inspect_wav

MAX_SECONDS = 120
MAX_BYTES = 6 * 1024 * 1024
ACCEPTED = "a WAV file: mono, 16-bit PCM, 16 or 24 kHz"


class ClipRejected(Exception):  # noqa: N818 - a refusal, with its HTTP status
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def check_clip(audio: bytes) -> WavInfo:
    if not audio:
        raise ClipRejected(422, "empty_audio", "the recording is empty")
    if len(audio) > MAX_BYTES:
        raise ClipRejected(413, "audio_too_large", f"a recording of at most {MAX_BYTES} bytes")
    try:
        info = inspect_wav(audio)
    except InvalidRequestError as exc:
        if exc.code == "audio_too_long":
            raise ClipRejected(
                422, "audio_too_long", f"a recording of at most {MAX_SECONDS} seconds"
            ) from exc
        raise ClipRejected(415, "unsupported_audio", f"{ACCEPTED} ({exc})") from exc
    if info.duration_ms > MAX_SECONDS * 1000:
        raise ClipRejected(422, "audio_too_long", f"a recording of at most {MAX_SECONDS} seconds")
    return info
