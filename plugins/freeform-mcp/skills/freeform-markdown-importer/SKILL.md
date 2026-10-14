---
name: freeform-markdown-importer
description: Markdown metinlerini veya dosyalarını yapılandırarak Freeform panosuna aktarır. Kullanıcı bir README, not, döküman veya madde listesini Freeform'a dönüştürmek istediğinde kullanın.
---

# Freeform Markdown İçe Aktarıcı (Markdown Importer)

Bu beceri, standart Markdown yapılarını (başlıklar, madde işaretleri, kod blokları ve tablolar) semantik olarak Freeform tuval bileşenlerine dönüştürür.

## Eşleme Kuralları

| Markdown Yapısı | Freeform Temsili | Araç / Yöntem |
|---|---|---|
| `# Başlık (H1)` | Büyük Pano Başlığı | `text_add(..., bold=True, y=-550)` |
| `## Alt Başlık (H2)` | Bölüm Rozeti / Kartı | `shape_insert_preset("rounded_card", ...)` |
| `- Madde İşareti` | Yapışkan Not / Metin | `sticky_add` veya `text_add` |
| `[x] / [ ] Görev` | Onay/Bekleyen Not | `badge_check` / `badge_warning` + not |
| Resim `![alt](url/path)` | Tuval Görseli | `image_insert(file_path)` |

## İş Akışı

1. **Ayrıştırma (Parsing):**
   - Dokümandaki ana başlığı ve bölümleri tespit edin.
   - Her bölüm altındaki maddeleri gruplayın.
2. **Düzen Hesaplama:**
   - Kaç ana bölüm olduğuna göre sütun sayısını belirleyin (Örn: 2 ila 4 sütun).
   - `board_create_grid` formatında bir `items` listesi hazırlayın.
3. **Toplu Yerleştirme:**
   - Tek tek yerleştirme yerine `board_create_grid` aracını kullanarak tüm kartları ve başlıkları ızgara düzeninde tuvale yerleştirin.
4. **Son Kontrol:**
   - `board_scan` ile eklenen metinlerin okunaklılığını ve düzenini doğrulayın.
