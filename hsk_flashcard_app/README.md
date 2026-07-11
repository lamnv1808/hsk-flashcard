# Flashcard tiếng Trung HSK1–HSK4

## Chạy nhanh
Cách ổn định nhất:

```bash
python -m http.server 8000
```

Sau đó mở: http://localhost:8000/hsk_flashcard_app/

Hoặc upload toàn bộ thư mục lên Render Static Site, Netlify, Vercel hoặc GitHub Pages.

## Có sẵn
- 1.194 thẻ HSK1–HSK4
- Học theo từng cấp độ
- Lật thẻ
- Chấm Again / Hard / Good / Easy
- Lịch ôn đơn giản theo spaced repetition
- Lưu tiến độ bằng localStorage
- Dark mode
- PWA/offline cache cơ bản
- Mobile responsive

## Lưu ý
Phiên bản này lưu tiến độ riêng trên từng trình duyệt. Chưa có tài khoản và đồng bộ cloud.


## V2
- Chọn nhiều cấp HSK cùng lúc
- Chọn số thẻ mỗi phiên
- Nút Next để bỏ qua chấm điểm
- Giải thích rõ logic Chưa nhớ / Khó / Nhớ được / Rất dễ
- Khoảng cách ôn tăng dần theo lịch sử học

## V3 — Audio (SpeechSynthesis)
- Nút loa đọc **từ vựng** và **câu ví dụ** (tiếng Trung, giọng zh-CN).
- Nút **Đọc tất cả**: từ (zh-CN) → nghỉ 500ms → câu ví dụ (zh-CN). **Không đọc pinyin, không đọc tiếng Việt** (đọc tiếng Việt để dành làm tùy chọn tương lai).
- Cài đặt âm thanh: tốc độ 0.7x / 0.85x / 1x, tự đọc từ khi hiện thẻ mới, tự đọc ví dụ sau khi lật, nút **Dừng**.
- Ưu tiên giọng Google/Microsoft, fallback về bất kỳ giọng zh-CN / vi-VN có sẵn.
- Dùng SpeechSynthesis của trình duyệt, không cần backend. Giọng phụ thuộc vào từng máy/OS:
  - Chrome desktop: đầy đủ giọng Google.
  - Android Chrome: giọng hệ thống (Mandarin có thể báo là `cmn-*`, đã xử lý).
  - iOS Safari: cần chạm để phát lần đầu; có thể thiếu giọng vi-VN.

## V3.1 — UX / usability polish
- **Bấm vào chữ Hán** (từ hoặc câu ví dụ) để nghe phát âm — không lật thẻ.
- **Chỉ báo đang đọc**: chữ đang được đọc sẽ nhấp nháy + hiển thị "Đang đọc".
- Tự dừng audio khi chuyển thẻ.
- **Phím tắt** (khi đang học): `Space` = Lật · `1/2/3/4` = Chưa nhớ/Khó/Nhớ được/Rất dễ · `N` = Bỏ qua · `S` = Nghe (mặt trước đọc từ, mặt sau đọc ví dụ) · `Esc` = Thoát.
- **Mobile**: nút bấm to hơn, khoảng cách thoáng hơn, không cuộn ngang.
- **PWA**: icon mới (192/512/maskable + apple-touch), splash tốt hơn, nút **Cài đặt** khi trình duyệt hỗ trợ, offline fallback về app shell.
- **Accessibility**: `aria-label`, vùng `aria-live` thông báo thẻ/trạng thái đọc, focus bàn phím hiển thị rõ, điều hướng hoàn toàn bằng bàn phím.

## V4 — Premium study experience (swipe + one-screen)
- **Vuốt / kéo thẻ để chuyển**: vuốt TRÁI = thẻ kế tiếp (như Next/Skip, **không** chấm điểm), vuốt PHẢI = thẻ trước đó trong phiên. Ngưỡng ~80px, bỏ qua nếu kéo dọc nhiều hơn, snap về nếu chưa đủ ngưỡng. Desktop kéo chuột (con trỏ grab/grabbing). Chạm/click thường vẫn lật thẻ.
- **An toàn lịch ôn**: quay lại thẻ trước là điều hướng thuần — không đụng SRS, không nhân đôi lượt/tiến độ. Chấm lại một thẻ đã xem sẽ **ghi đè** (revert + áp dụng lại) chứ không cộng dồn. Ở thẻ đầu, vuốt phải không làm gì; ở thẻ cuối, vuốt trái kết thúc phiên như cũ.
- **Học trong một màn hình (mobile)**: header, tiến độ, thẻ, audio và nút chấm điểm hiển thị cùng lúc, **không cuộn dọc**. Dùng chiều cao thật của viewport (`--app-h`, thay cho `100dvh` không ổn định trên iOS), tôn trọng safe-area, chiều cao thẻ co giãn theo màn hình, audio & chấm điểm dạng lưới 2×2 (≥44/48px).
- Giải thích mức độ nhớ chuyển thành **bottom sheet** (không chiếm chỗ cố định).
- Đổi thẻ luôn: dừng đọc, về mặt trước, giữ nguyên tính toàn vẹn của phiên.
- Desktop giữ nguyên như trước.
