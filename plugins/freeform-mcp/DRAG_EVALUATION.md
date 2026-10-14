# Arka Plan Sürükleme Değerlendirmesi

## Sonuç

Bu macOS/Freeform ortamında, Freeform ön plana alınmadan güvenilir bir
nesne sürüklemesi yapılamıyor. Yön tuşlarıyla taşıma korunmalıdır.

## Kanıt

Süreç hedefli (`CGEventPostToPid`) fare akışı, seçili bir metin nesnesine
uygulandı:

1. Sol tuş basılı (`kCGEventLeftMouseDown`)
2. Dört ara `kCGEventLeftMouseDragged` olayı
3. Sol tuş bırakma (`kCGEventLeftMouseUp`)

Olayların her biri hedef Freeform PID'sine, pencere kimliği damgasıyla ve
arka plan girişinin kabul ettiği Command bayrağıyla gönderildi. Ön ve son
ekran görüntülerinin piksel farkı `None` oldu; nesne hareket etmedi. Ön
planda Freeform değil, başka uygulamalar kaldı.

İkinci canlı denemede Freeform, aynı 1242×683 pt / 2484×1366 px boyutunda
fakat `(1256,302)` konumundaydı. Seçili `DRAG-CONTROL` metninin merkezi
yakalamadan ölçüldü; 320×160 yakalama pikseli hedefli sekiz ara sürükleme
olayı gönderildi. Son karede metin aynı konumdaydı; yalnızca seçim
çerçevesi kalkmıştı. Ön plan `ChatGPT` olarak kaldı.

Bu, normal bir macOS fare sürüklemesinin, pencere sunucusunun imleç/etkin
uygulama durumuna bağlı olmasından kaynaklanır. Klavye olayları hedef sürece
ulaşırken, fare yakalama ve sürükleme dizisi arka plan hedefinde
başlatılamıyor.

## 0,5 px konum farkı

Bu fark fiziksel bir hareket hatası değildir: Retina yakalama 2x çözünürlüklü
olduğu için bir Freeform nesnesinin kapsayan piksel kutusu, tek sayıda piksel
genişliğinde/yüksekliğinde olabilir. Kutunun geometrik merkezi bu durumda
`.5` ile biter. Ayrıca mevcut nudge birimi 2 yakalama pikselidir (1 mantıksal
nokta); 0,5 yakalama pikseli yön tuşuyla temsil edilemez.

Konum sözleşmesi şu olmalıdır:

- Yerleştirme toleransı `<= 0.5` yakalama pikseli ise, hedef mantıksal
  noktada kabul edilir.
- Kesin piksel kenarı yerine nesnenin mantıksal merkez noktası esas alınır.
- Daha küçük bir sayı raporlamak için koordinatı yuvarlamak doğru değildir;
  ölçüm hassasiyetini gizler.

## Sürükleme ne zaman mümkün olur?

Yalnızca Freeform'u etkinleştirme/ön plana alma izni verilirse, gerçek ekran
imleciyle yapılan sürükleme yeniden değerlendirilebilir. Bu, v8'in "ekranı
çalma" gereksinimiyle bağdaşmaz ve ayrı bir kullanıcı onayı gerektirir.
