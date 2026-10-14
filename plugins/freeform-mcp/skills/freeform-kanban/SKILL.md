---
name: freeform-kanban
description: Apple Freeform üzerinde çevik görev, sprint ve Kanban panoları oluşturur, sütunları yönetir ve görev kartlarını sütunlar arasında taşır. Kullanıcı Kanban, görev panosu, sprint veya todo board istediğinde kullanın.
---

# Freeform Kanban Panosu Becerisi

Bu beceri, Freeform üzerinde sütunlu (Yapılacaklar, Geliştirmede, Tamamlandı vb.) Kanban panolarını `board_create_grid`, `sticky_add` ve `shape_insert_preset` kullanarak organize eder.

## Standart Kanban Düzeni

Varsayılan 3 sütunlu düzen:
1. **Yapılacaklar (To Do):** `x: -450` (Mavi rozet / sarı notlar)
2. **Geliştirmede (In Progress):** `x: 0` (Turuncu rozet / sarı notlar)
3. **Tamamlandı (Done):** `x: +450` (Yeşil onay rozeti / sarı notlar)

Yatay aralık (`spacing_x`): 450 px
Dikey kart aralığı (`spacing_y`): 180 px

## İş Akışı

### 1. Yeni Kanban Panosu Oluşturma
1. `debug_info` ve `board_zoom("100")` ile hazırlık yapın.
2. Tahta başlığını ekleyin:
   `text_add("Proje Kanban Panosu", x=0, y=-520, bold=True)`
3. Sütun başlıklarını ve durum rozetlerini ekleyin:
   - `shape_insert_preset("badge_warning", x=-450, y=-420, label="Yapılacaklar")`
   - `shape_insert_preset("rounded_card", x=0, y=-420, color="#FF9800", label="Geliştirmede")`
   - `shape_insert_preset("badge_check", x=450, y=-420, label="Tamamlandı")`
4. Görev kartlarını (yapışkan notları) ilgili sütun x koordinatına alt alta yerleştirin:
   - Görev 1: `sticky_add("Görev A", x=-450, y=-240)`
   - Görev 2: `sticky_add("Görev B", x=-450, y=-60)`

### 2. Görevi Başka Sütuna Taşıma ("X görevini Tamamlandı'ya taşı")
1. `board_find_and_select(query="Görev A", select=True)` ile taşınacak görevi bulun ve seçin.
2. Hedef sütun ile mevcut x koordinatı arasındaki farkı (`dx`) hesaplayın:
   - Yapılacaklar'dan Tamamlandı'ya: `dx = +900`
   - Yapılacaklar'dan Geliştirmede'ye: `dx = +450`
   - Geliştirmede'den Tamamlandı'ya: `dx = +450`
3. `object_move(dx=dx, dy=0)` ile kartı yeni sütununa kaydırın.
4. `board_screenshot()` ile sonucun görsel doğrulamasını yapın.
