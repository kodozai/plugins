---
name: freeform-export
description: Apple Freeform tahtasını yüksek çözünürlüklü PDF, PNG ekran görüntüsü veya Vision OCR analiz verisiyle birlikte dışa aktarır ve paketler. Kullanıcı tahtayı kaydetmek, PDF almak, paylaşmak veya çıktı üretmek istediğinde kullanın.
---

# Freeform Dışa Aktarma Becerisi (Export & Delivery)

Bu beceri, tamamlanan veya üzerinde çalışılan Freeform tahtasını paylaşılabilir ve arşivlenebilir formatlarda dışa aktarır.

## Kullanılabilir Araçlar

1. `board_export_pdf(output_path, dpi=144)`:
   - %100 Arka Plan Garantili: Asla sistem kaydetme penceresi (Save Dialog) açmaz, klavye kullanımını engellemez.
   - Doğrudan tuval içeriğinden 144 DPI yüksek çözünürlüklü vektör/raster PDF üretir.
2. `board_screenshot()`:
   - Pencere gölgelerinden arındırılmış, çerçevesiz PNG görüntüsü (base64) üretir.
3. `board_export_pack(output_dir)`:
   - Belirtilen klasöre aynı anda hem `board.pdf`, hem `board.png`, hem de tahtadaki tüm metin ve koordinatların dökümünü içeren `board_metadata.json` dosyasını kaydeder.

## İş Akışı

1. **Hazırlık:**
   - Dışa aktarma öncesinde `board_zoom("fit")` çağırarak tüm içeriğin kadraja girdiğinden emin olun veya %100 detaylı görünüm için `board_zoom("100")` kullanın.
   - Tahtayı kaydetmek için `board_save()` çağırın.
2. **Tekil PDF İsteği:**
   - Kullanıcı sadece PDF istediyse: `board_export_pdf("~/Desktop/tahta.pdf")`.
3. **Kapsamlı Arşiv / Teslim Paketi İsteği:**
   - Kullanıcı tahtanın tam dökümünü veya teslimatını istediyse: `board_export_pack("~/Desktop/Pano_Paketi")`.
   - Kullanıcıya oluşturulan PDF boyutu, PNG yolu ve taranan metin sayısını raporlayın.
