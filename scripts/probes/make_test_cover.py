"""一次性工具：生成封面校准用测试 PNG（纯标准库 zlib，无 PIL 依赖）。

用法：python scripts/probes/make_test_cover.py [输出路径] [宽] [高]
默认输出 .scratch/selector-calibration/test_cover.png（1920x1080，满足头条封面建议分辨率）。
"""

import struct
import sys
import zlib
from pathlib import Path

W = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
H = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".scratch/selector-calibration/test_cover.png")


def chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def main() -> None:
    rows = bytearray()
    for y in range(H):
        rows.append(0)  # filter: None
        for x in range(W):
            # 简单渐变条纹，肉眼可辨的测试图
            v = ((x // 40) + (y // 40)) % 2
            rows.extend((30 + 100 * v, 60 + 80 * (1 - v), 120 + 60 * v))
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(png)
    print(f"written: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
