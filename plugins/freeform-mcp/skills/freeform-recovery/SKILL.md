---
name: freeform-recovery
description: Apple Freeform MCP araçları `verified: false`, ekran yakalama hatası, zaman aşımı veya beklenmeyen seçim durumu döndürdüğünde güvenli teşhis ve kurtarma uygular. Freeform işlemi başarısız olduğunda kullanın.
---

# Freeform Kurtarma

Başarısız bir mutasyonu otomatik olarak tekrarlamayın; kısmi etki oluşmuş
olabilir.

## Teşhis

1. `debug_info` ve `board_screenshot` çağırın.
2. `operation_id`, `error_px`, `elapsed_ms`, `frontmost_before` ve
   `frontmost_after` alanlarını kaydedin.
3. Freeform ön plana geçmişse yeni mutasyon yapmadan kullanıcıya bildirin.
4. Zoom %100 değilse `board_zoom("100")` ile düzeltin.

## Kurtarma

- Nesne görünür fakat konumu yanlışsa aynı nesneyi yeniden eklemek yerine
  seçip `object_move` ile düzeltin.
- Nesne yoksa, ancak ekran görüntüsü bunu doğruladıktan sonra tek bir yeniden
  ekleme deneyin.
- Tahta temizleme, geri alma veya uygulamayı açma/kapatma işlemleri için
  kullanıcıdan açık talimat yoksa bunları yapmayın.
- Arka plan sürüklemesi kullanmayın; `object_drag` yalnız tanısal amaçlıdır.

Kurtarma sonucunu doğrulanmış, kısmi veya başarısız olarak açıkça raporlayın.
