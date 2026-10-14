# Freeform MCP

Apple Freeform için, pencereyi ön plana almadan çalışan macOS MCP sunucusu.
Freeform açık bir tahta içerdiğinde içerik ekler, seçimi yönetir ve pencere
ekran görüntüsü alır.

## Gereksinimler

- macOS ve Apple Freeform
- Python 3.10+
- OpenCode'u çalıştıran uygulama için **Erişilebilirlik** ve **Ekran Kaydı**
  izinleri

Kurulum:

```sh
python3 -m pip install -r requirements.txt
```

Çalışma kopyasının OpenCode yapılandırması [.mcp.json](.mcp.json) içindedir.
Başka bir konuma taşınırsa yalnızca bu dosyadaki Python dosyası yolu
güncellenmelidir.

## Kullanım

Freeform'da bir tahta açın, sonra örneğin şunları isteyin:

- “Ortaya Başlangıç metni ekle.”
- “Bu PNG dosyasını tahtaya yerleştir.”
- “Tahtanın ekran görüntüsünü al.”

Koordinatlar, pencere yakalamasının merkezi baz alınarak 2x Retina yakalama
pikseliyle verilir. Yerleştirme için zoom %100 olmalıdır.

## Araçlar

`board_new`, `board_open`, `board_save`, `board_undo`, `board_redo`,
`board_clear`, `board_screenshot`, `board_export_pdf`, `board_export_pack`, `board_zoom`,
`board_scan`, `board_find_and_select`, `board_align_to`, `board_create_grid`, `debug_info`,
`text_add`, `image_insert`, `shape_svg_insert`, `shape_insert_preset`, `sticky_add`,
`select_all`, `select_at`, `select_deselect`, `object_delete`, `object_duplicate`,
`object_move`, `object_group`, `object_ungroup`, `arrange` ve tanısal `object_drag`.

## Kararlılık davranışı

- Araç çağrıları seri çalışır; eşzamanlı çağrılar seçim veya pano durumunu
  paylaşmaz.
- Yanıtlar `operation_id`, `elapsed_ms`, `frontmost_before` ve
  `frontmost_after` alanlarını içerir.
- Yerleştirme ölçümleri Retina piksel kutusundan gelir. `0.5 px`, nesnenin
  tek sayılı piksel boyutundan kaynaklanan ölçüm belirsinliğidir; sonuçta
  `measurement_uncertainty_px` ve `logical_position_verified` ile bildirilir.
- Sürükleme doğrulanmış bir arka plan işlemi değildir. `object_move` kullanın.
  `FREEFORM_EXPERIMENTAL_DRAG=1` yalnızca tanısal `object_drag` yolunu açar.

## Sınırlar

Freeform'ın resmi programlama API'si yoktur. Yeni tahta veya dosya açmak
macOS tarafından kısa süreli etkinleştirme gerektirebilir. Tahta değiştirilir
veya zoom seviyesi işlem sırasında değişirse yerleştirme doğrulanamayabilir.
