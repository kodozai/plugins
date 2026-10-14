---
name: freeform-board
description: Apple Freeform tahtalarında arka planda içerik ekleme, düzenleme, kaydetme ve doğrulama yapar. Kullanıcı Freeform tahtası, sticky not, metin, görsel, pano veya diyagram istediğinde kullanın.
---

# Freeform Tahta İş Akışı

Freeform MCP araçlarını kullanmadan önce `debug_info` çağırın. Hata dönerse
işlemi durdurun; tahmin ederek devam etmeyin.

## Ön koşullar

1. Aktif tahtanın varlığını ve `frontmost` uygulamasını doğrulayın.
2. Konumlandırma yapılacaksa `board_zoom("100")` çağırın.
3. Kullanıcı açıkça istemedikçe `board_clear` çağırmayın.
4. Freeform'u ön plana getirmeyin. Araç sonucundaki `frontmost_before` ve
   `frontmost_after` alanlarını karşılaştırın.

## Yerleştirme

- Koordinatlar, pencere merkezinden itibaren 2x Retina yakalama pikselidir.
- Metin için `text_add`, görsel için `image_insert`, not için `sticky_add`
  kullanın.
- Her mutasyondan sonra `verified` alanını inceleyin.
- `verified: false` sonucunda aynı ekleme çağrısını tekrarlamayın; önce
  `freeform-recovery` iş akışını uygulayın.
- `error_px` içindeki en fazla 0,5 px fark, Retina ölçüm belirsinliğidir.
  `logical_position_verified: true` ise konumu doğru kabul edin.

## Tamamlama

İstenen değişiklikler tamamlanınca `board_screenshot` ile sonucu doğrulayın.
Kullanıcı kalıcılık istediyse `board_save` çağırın ve yalnız doğrulanmış
sonuçları raporlayın.
