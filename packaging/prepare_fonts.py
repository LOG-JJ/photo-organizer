"""OFL Noto Sans KR를 앱 전용 정적 글꼴로 준비합니다. 배포본에서는 실행하지 않습니다."""
from pathlib import Path
import argparse
import hashlib
import urllib.request

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    if not args.source.exists():
        args.source.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf", args.source)
    destination = Path(__file__).resolve().parents[1] / "assets" / "fonts"
    destination.mkdir(exist_ok=True)
    for weight, style in ((400, "Regular"), (500, "Medium"), (700, "Bold")):
        source = TTFont(args.source)
        font = instantiateVariableFont(source, {"wght": weight}, inplace=True, updateFontNames=True)
        family = "Photo Organizer UI Medium" if weight == 500 else "Photo Organizer UI"
        subfamily = "Bold" if weight == 700 else "Regular"
        names = {1: family, 2: subfamily, 3: f"PhotoOrganizerUI-{style}-1.0", 4: f"{family} {subfamily}",
                 6: f"PhotoOrganizerUI-{style}", 16: family, 17: subfamily, 21: family, 22: subfamily}
        for record in font["name"].names:
            if record.nameID in names:
                record.string = names[record.nameID].encode(record.getEncoding())
        for name_id, value in names.items():
            font["name"].setName(value, name_id, 3, 1, 0x409)
        font["OS/2"].usWeightClass = weight
        font["OS/2"].fsSelection &= ~((1 << 5) | (1 << 6))
        font["OS/2"].fsSelection |= (1 << 5) if weight == 700 else (1 << 6)
        font["head"].macStyle = (font["head"].macStyle | 1) if weight == 700 else (font["head"].macStyle & ~1)
        output = destination / f"NotoSansKR-{style}.ttf"
        font.save(output)
        font.close()
        print(output.name, output.stat().st_size)
    print("Source SHA256:", hashlib.sha256(args.source.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
