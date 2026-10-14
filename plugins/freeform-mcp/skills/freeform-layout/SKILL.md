---
name: freeform-layout
description: Apple Freeform için çakışmasız metin, görsel ve sticky not yerleşim planı üretir. Kullanıcı bir pano düzeni, ızgara, zaman çizelgesi, zihin haritası veya koordinat planı istediğinde kullanın.
---

# Freeform Yerleşim Planı

Önce `debug_info` ile yakalama boyutunu alın. Koordinatları sabit ekran
çözünürlüğüne göre değil, dönen `capture_size` değerine göre hesaplayın.

## Planlama kuralları

1. Başlık, içerik ve açıklama için ayrı yatay bantlar ayırın.
2. Nesne boyutları bilinmiyorsa, komşu merkezler arasında en az 80 yakalama
   pikseli boşluk bırakın.
3. Kenarları araç çubuğu, zoom denetimleri ve kaydırma çubuklarından uzak
   tutun; kullanılabilir alan için `content_roi` değerini kullanın.
4. Birden çok nesneyi satır/sütun ızgarasına dağıtın; planı önce listeleyin.
5. Plan onay gerektiriyorsa kullanıcı onayı almadan mutasyon yapmayın.

## Uygulama

Yerleştirme için `freeform-board` iş akışını kullanın. Her nesneyi tek tek
doğrulayın; başarısız bir nesne yüzünden daha önce doğrulanan nesneleri
yeniden eklemeyin.
