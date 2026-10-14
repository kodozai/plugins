---
name: freeform-audit-inspector
description: Apple Freeform tahtasını Apple Vision OCR ile tarar, mevcut metin ve nesneleri analiz eder, semantik arama ile öğeleri bulur ve seçer. Kullanıcı tahtada ne olduğunu sorduğunda, belirli bir kartı/metni bulmak veya düzenlemek istediğinde kullanın.
---

# Freeform Tahta Denetimi ve Arama (Audit & Inspector)

Bu beceri, tahtadaki mevcut nesneleri körlemesine tahmin etmek yerine yerleşik Apple Vision OCR ile tam koordinatlarıyla denetler ve doğrudan etkileşime girer.

## Temel Araçlar

- `board_scan()`: Tuvaldeki tüm metin bloklarını, güven skorlarını ve tuval merkezine göre (x, y) offset koordinatlarını çıkarır.
- `board_find_and_select(query, select=True)`: Aranan metni en yüksek benzerlikle tespit eder; `select=True` olduğunda nesneyi doğrudan tıklar ve seçili hale getirir.

## İş Akışı

### 1. Tahta İçerik Taraması ("Tahtada ne var?")
1. `debug_info` ile Freeform durumunu ve `capture_size` değerini alın.
2. `board_scan` çağırın. Dönen `texts` listesindeki öğeleri gruplayarak kullanıcıya düzenli bir özet sunun:
   - Başlıklar ve kart etiketleri
   - Tahtadaki tahmini bölgeler (Sol üst, Merkez, Sağ alt)
   - Toplam tespit edilen metin sayısı (`total_texts`)

### 2. Semantik Nesne Bulma ve Seçme ("X kartını seç / taşı / sil")
1. Kullanıcının aradığı anahtar kelimeyi `board_find_and_select(query="...")` ile arayın.
2. `found: true` dönerse:
   - Nesne otomatik olarak tıklanmış ve seçili hale gelmiştir.
   - Taşıma için `object_move(dx, dy)` çağırabilirsiniz.
   - Silmek için `object_delete()` çağırabilirsiniz.
   - Çoğaltmak için `object_duplicate()` çağırabilirsiniz.
3. `found: false` dönerse, `board_scan()` ile alternatif adayları inceleyin veya kullanıcıdan tam ifadeyi isteyin.

## Kurallar ve İpuçları

- Taramadan önce tahta zoom seviyesinin %100 (`board_zoom("100")`) olduğundan emin olun; koordinat hassasiyeti için bu zorunludur.
- Freeform arka planda çalışırken ekran görüntüsü ve OCR ön plandaki uygulamayı kesintiye uğratmaz.
