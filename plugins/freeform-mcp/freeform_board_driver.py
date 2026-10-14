"""Build a compact Freeform reference board for the desktop-restyle plan.

Run directly from this directory while a Freeform board is open:
    python3 freeform_board_driver.py

The module calls the v8 background engine directly, so Freeform remains in
the background throughout. Source screenshots are copied as 250px-wide PNG
thumbnails into /tmp; the board keeps its embedded copies after the temporary
files are removed by the operating system.
"""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

import freeform_mcp_server as freeform


SOURCE = Path("/Users/macpro/Desktop/example")
THUMBNAIL_SIZE = (250, 156)
COLS = 7
X_POSITIONS = (-900, -600, -300, 0, 300, 600, 900)
Y_POSITIONS = (-390, -165, 60, 285, 510)

# The order mirrors the phase plan. Phases without a screenshot are captured
# in the board title rather than represented by a misleading placeholder.
ITEMS = [
    ("02–03", "Yeni sohbet", "yeni-sohbet.png"),
    ("04", "Ekle modalı", "Modal/Ekle.png"),
    ("05", "Pazaryeri", "Pazaryaeri/Pazaryeri.png"),
    ("05", "Pazaryeri 2", "Pazaryaeri/Pazaryeri 2.png"),
    ("05", "Pazaryeri 3", "Pazaryaeri/Pazaryeri 3.png"),
    ("05", "Beceriler", "Pazaryaeri/Beceriler.png"),
    ("07", "Genel", "Ayarlar/Kişisel/Genel.png"),
    ("07", "Genel 2", "Ayarlar/Kişisel/Genel 2.png"),
    ("07", "Genel 3", "Ayarlar/Kişisel/Genel 3.png"),
    ("07", "Görünüm", "Ayarlar/Kişisel/Görünüm.png"),
    ("07", "Profil", "Ayarlar/Kişisel/Profil.png"),
    ("07", "Yapılandırma", "Ayarlar/Kişisel/Yapılandıırma.png"),
    ("07", "Yapılandırma 2", "Ayarlar/Kişisel/Yapılandırma 2.png"),
    ("07", "Kişiselleştirme", "Ayarlar/Kişisel/Kişiselleştirme.png"),
    ("07", "Analizler", "Ayarlar/Kişisel/Analizler.png"),
    ("07", "İçe aktar", "Ayarlar/Kişisel/İçe Aktar.png"),
    ("07", "Kullanım ve faturalama", "Ayarlar/Kişisel/Kullanım ve Faturalama.png"),
    ("08", "Git", "Ayarlar/Kodlama/Git.png"),
    ("08", "Git 2", "Ayarlar/Kodlama/Git 2.png"),
    ("08", "Bağlantılar", "Ayarlar/Kodlama/Bağlantılar.png"),
    ("08", "Ortamlar", "Ayarlar/Kodlama/Ortamlar.png"),
    ("08", "Hook'lar", "Ayarlar/Kodlama/Hook'lar (Kancalar).png"),
    ("08", "Çalışma ağaçları", "Ayarlar/Kodlama/Çalışma Ağaçları.png"),
    ("09", "Tarayıcı", "Ayarlar/Entegrasyonlar/Tarayıcı.png"),
    ("09", "Tarayıcı 2", "Ayarlar/Entegrasyonlar/Tarayıcı 2.png"),
    ("09", "Tarayıcı 3", "Ayarlar/Entegrasyonlar/Tarayıcı 3.png"),
    ("09", "Uygulamalar", "Ayarlar/Entegrasyonlar/Uygulamalar.png"),
    ("09", "Bilgisayar kullanımı", "Ayarlar/Entegrasyonlar/Bilgisayar Kullanımı.png"),
    ("09", "Uygulama görüntüleri", "Ayarlar/Entegrasyonlar/Uygulama Görüntüleri.png"),
    ("09", "Eklentiler", "Ayarlar/Entegrasyonlar/Eklentiler/Eklentiler.png"),
    ("09", "Eklentiler: MCP", "Ayarlar/Entegrasyonlar/Eklentiler/MCP'ler.png"),
    ("09", "Eklentiler: Pazaryeri", "Ayarlar/Entegrasyonlar/Eklentiler/Pazaryeri.png"),
    ("09", "Eklentiler: Beceriler", "Ayarlar/Entegrasyonlar/Eklentiler/Beceriler.png"),
    ("09", "Arşiv", "Ayarlar/Arşiv/Arşivlenmiş Sohbetler.png"),
]


def _thumbnail(source: Path, destination: Path) -> None:
    with Image.open(source) as image:
        image.convert("RGB").resize(THUMBNAIL_SIZE, Image.Resampling.LANCZOS).save(destination)


def _require_verified(result: dict, description: str) -> None:
    if not result.get("verified", False):
        raise RuntimeError(f"{description} yerleştirilemedi: {result}")


def main(start: int = 0, count: int | None = None, clear: bool = True) -> None:
    if len(ITEMS) != 34:
        raise RuntimeError(f"34 görsel bekleniyordu, {len(ITEMS)} tanımlı")
    if any(not (SOURCE / path).is_file() for _, _, path in ITEMS):
        missing = [path for _, _, path in ITEMS if not (SOURCE / path).is_file()]
        raise FileNotFoundError(", ".join(missing))

    info = freeform.debug_info()
    if info.get("status") != "ok":
        raise RuntimeError(f"Freeform board erişilemiyor: {info}")
    if freeform._frontmost() == "Freeform":
        raise RuntimeError("Freeform ön planda; arka plan garantisi için önce başka bir uygulamaya geçin")

    if not 0 <= start < len(ITEMS):
        raise ValueError(f"start 0 ile {len(ITEMS) - 1} arasında olmalı")
    if clear:
        if start != 0:
            raise ValueError("--clear yalnızca --start 0 ile kullanılabilir")
        freeform.board_clear()
        freeform.board_zoom("100")
        _require_verified(
            freeform.text_add("Desktop Restyle — Faz 01–10 | Referanslar: 34 PNG | 06 kabuk, 10 QA: görselsiz", 0, -625),
            "tahta başlığı",
        )
    end = len(ITEMS) if count is None else min(start + count, len(ITEMS))

    with TemporaryDirectory(prefix="freeform-board-") as temp:
        tmp = Path(temp)
        for index in range(start, end):
            phase, caption, relative_path = ITEMS[index]
            col, row = index % COLS, index // COLS
            x, y = X_POSITIONS[col], Y_POSITIONS[row]
            thumb = tmp / f"{index:02d}.png"
            _thumbnail(SOURCE / relative_path, thumb)
            _require_verified(freeform.image_insert(str(thumb), x, y), relative_path)
            _require_verified(freeform.text_add(f"{phase} · {caption}", x, y + 104), caption)
            print(f"[{index + 1:02d}/{len(ITEMS)}] {phase} · {caption}", flush=True)

    freeform.board_save()
    final = freeform.debug_info()
    if final.get("frontmost") == "Freeform":
        raise RuntimeError("Freeform işlem sonunda ön plana geçti")
    if end == len(ITEMS):
        print(f"Tamamlandı: {len(ITEMS)} görsel; ön plan: {final.get('frontmost')}")
    else:
        print(
            f"Parça tamamlandı: {start + 1}–{end}/{len(ITEMS)}; "
            f"ön plan: {final.get('frontmost')}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0, help="0 tabanlı ilk görsel indeksi")
    parser.add_argument("--count", type=int, help="yerleştirilecek görsel sayısı")
    parser.add_argument("--resume", action="store_true", help="tahtayı silmeden devam et")
    args = parser.parse_args()
    main(args.start, args.count, clear=not args.resume)
