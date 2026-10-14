---
name: freeform-mindmap
description: Apple Freeform üzerinde zihin haritaları (mind map), akış şemaları ve mimari diyagramlar oluşturur. Kullanıcı zihin haritası, mimari şema, flowchart, karar ağacı veya sistem tasarımı istediğinde kullanın.
---

# Freeform Zihin Haritası ve Mimari Şema Becerisi

Bu beceri, parametrik vektörel bileşenleri (`shape_insert_preset`) ve metinleri kullanarak Freeform üzerinde ilişkisel akış şemaları ve zihin haritaları kurar.

## Kullanılabilir Şekil Presetleri

- **Bağlantı Okları:** `arrow_right`, `arrow_left`, `arrow_down`, `arrow_up`
- **Diyagram Düğümleri:**
  - `rounded_card`: Temel servis/modül kartı
  - `database`: Veritabanı ve depolama katmanı
  - `cloud`: Harici API, bulut altyapısı ve ağ servisleri
  - `decision_diamond`: Karar / şart dallanma noktası
  - `badge_check`: Başarılı / onaylanmış durum
  - `badge_warning`: Uyarı veya dikkat noktası

## İş Akışı ve Düzen Kalıpları

### 1. Merkezcil (Radyal) Zihin Haritası
- **Merkez Düğüm:** `(0, 0)` koordinatında ana fikir kartı (`rounded_card` veya `text_add`).
- **Kuzey Dalı:** `y: -250` (Bağlantı: `arrow_up` `y: -130`)
- **Güney Dalı:** `y: +250` (Bağlantı: `arrow_down` `y: +130`)
- **Doğu Dalı:** `x: +380` (Bağlantı: `arrow_right` `x: +190`)
- **Batı Dalı:** `x: -380` (Bağlantı: `arrow_left` `x: -190`)

### 2. Yatay Mimari Akış (Pipeline)
1. **İstemci / Web UI:** `x: -450, y: 0` (`rounded_card`, `label="Web Client"`)
2. **Yön Oku:** `x: -270, y: 0` (`arrow_right`)
3. **Backend API Servisi:** `x: -90, y: 0` (`cloud`, `label="FastAPI Gateway"`)
4. **Yön Oku:** `x: +90, y: 0` (`arrow_right`)
5. **Veritabanı Katmanı:** `x: +270, y: 0` (`database`, `label="PostgreSQL"`)

### 3. Doğrulama ve Dışa Aktarma
Şema tamamlandığında `board_screenshot()` ile görseli teyit edin, ardından kullanıcıya sunmak üzere `board_export_pdf()` veya `board_export_pack()` çağırın.
