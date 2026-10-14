---
name: freeform-reference-board
description: PNG/JPG referanslarını ve plan belgelerini Apple Freeform üzerinde kompakt bir referans panosuna dönüştürür. Kullanıcı görsel referans panosu, ekran görüntüsü ızgarası veya plan-görsel eşlemesi istediğinde kullanın.
---

# Freeform Referans Panosu

Kaynak dosyaları önce okuyun ve eksik dosyaları bildirin. Büyük ekran
görüntülerini özgün boyutuyla yerleştirmeyin; küçük kopyalar kullanın.

## İş akışı

1. Kaynakları kategori/faz sırasına göre eşleyin.
2. Her görsel için thumbnail üretin; orijinal kaynakları değiştirmeyin.
3. `freeform-layout` ile ızgara koordinatlarını oluşturun.
4. Her thumbnail'i `image_insert`, açıklamasını `text_add` ile yerleştirin.
5. Kesintiden sonra yalnızca tamamlanmamış öğelerle devam edin; var olan
   öğeleri körlemesine yeniden eklemeyin.
6. Son kareyi `board_screenshot` ile doğrulayın; kullanıcı isterse kaydedin.

`freeform_board_driver.py` yalnızca kullanıcı tüm referans panosunu açıkça
istediğinde çalıştırılmalıdır.
