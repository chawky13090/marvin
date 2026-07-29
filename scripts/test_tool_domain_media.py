"""Régressions du domaine Média et de sa façade tools.py."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from tool_domains import media as media_domain


async def _run() -> None:
    media_domain.configure(resolve_path=lambda path: f"resolved:{path}")

    assert "path" in (await media_domain.video_info({}))["error"]
    with patch.object(
        media_domain.video_manager,
        "get_media_info",
        return_value={"duration": 12, "codec": "h264"},
    ) as info:
        result = await media_domain.video_info({"path": "clip.mp4"})
    assert result == {"success": True, "duration": 12, "codec": "h264"}
    info.assert_called_once_with("resolved:clip.mp4")

    with patch.object(
        media_domain.video_manager,
        "video_trim",
        return_value={"success": True, "path": "out.mp4"},
    ) as trim:
        result = await media_domain.video_trim(
            {
                "path": "clip.mp4",
                "start": "1.5",
                "end": "4",
                "output_path": "out.mp4",
            }
        )
    assert result["success"] is True
    trim.assert_called_once_with(
        "resolved:clip.mp4",
        start=1.5,
        end=4.0,
        duration=None,
        output_path="resolved:out.mp4",
    )

    with patch.object(
        media_domain.video_manager,
        "screen_record_gif",
        return_value={"success": True},
    ) as record:
        await media_domain.screen_record_gif(
            {"duration": 99, "fps": 12, "region": [1, 2, 300, 200]}
        )
    record.assert_called_once_with(
        duration=20,
        fps=12,
        region=[1, 2, 300, 200],
        output_path=None,
    )

    with patch.object(
        media_domain.video_manager,
        "audio_merge",
        return_value={"success": True},
    ) as merge:
        await media_domain.audio_merge(
            {"paths": "a.wav, b.wav\nc.wav", "format": "wav"}
        )
    merge.assert_called_once_with(
        ["resolved:a.wav", "resolved:b.wav", "resolved:c.wav"],
        fmt="wav",
        output_path=None,
    )

    assert "au moins 2" in (
        await media_domain.audio_merge({"paths": ["single.wav"]})
    )["error"]
    assert "path" in (await media_domain.audio_volume({}))["error"]


def main() -> int:
    asyncio.run(_run())
    import tools

    expected = {
        "video_info": media_domain.video_info,
        "video_to_gif": media_domain.video_to_gif,
        "gif_to_video": media_domain.gif_to_video,
        "video_trim": media_domain.video_trim,
        "video_compress": media_domain.video_compress,
        "video_resize": media_domain.video_resize,
        "video_extract_frames": media_domain.video_extract_frames,
        "video_speed": media_domain.video_speed,
        "video_watermark": media_domain.video_watermark,
        "gif_optimize": media_domain.gif_optimize,
        "screen_record_gif": media_domain.screen_record_gif,
        "audio_info": media_domain.audio_info,
        "audio_extract": media_domain.audio_extract,
        "audio_convert": media_domain.audio_convert,
        "audio_trim": media_domain.audio_trim,
        "audio_merge": media_domain.audio_merge,
        "audio_volume": media_domain.audio_volume,
    }
    for name, function in expected.items():
        assert tools.TOOLS_REGISTRY[name] is function, name
        assert any(spec["function"]["name"] == name for spec in tools.TOOLS_SPEC), name
    assert len(tools.TOOLS_REGISTRY) == len(tools.TOOLS_SPEC) == 346
    print("Tool Domain Media OK - vidéo, GIF, audio, chemins et façade 346/346.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
