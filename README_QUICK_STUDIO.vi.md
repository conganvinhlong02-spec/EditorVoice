# VieNeu Quick Studio

Giao diện test nhanh cho VieNeu‑TTS v3 Turbo, ưu tiên độ trễ thấp trên Windows.

## Chạy ứng dụng

Nhấp đúp `start_quick_studio.bat`. Script sẽ tự tạo môi trường riêng, cài thư viện và mở trình duyệt tại `http://127.0.0.1:7860`.

Lần chạy đầu cần Internet để tải thư viện và model. Các lần sau dùng lại model đã lưu trên máy nên khởi động nhanh hơn.

## Luồng sử dụng

1. Chờ trạng thái trên góc phải chuyển sang “Sẵn sàng”.
2. Chọn nguồn giọng:
   - **Giọng có sẵn**: danh sách 14 giọng hiện ngay trong một panel riêng. Mỗi giọng có nút **Nghe** bên cạnh; nghe thử không làm thay đổi giọng đang chọn.
   - **Clone giọng của bạn**: chọn đoạn WAV/MP3/FLAC/M4A/OGG có lời nói rõ từ 3–8 giây, đặt tên rồi bấm **Thêm giọng**. Ứng dụng tự lọc nhiễu và học giọng trong vài giây.
3. Chọn phong cách tự nhiên, tin tức hoặc kể chuyện.
4. Chọn một trong hai chế độ:
   - **Phát trực tiếp**: âm thanh bắt đầu phát ngay khi model tạo được đoạn đầu tiên.
   - **Render hoàn chỉnh**: ứng dụng tạo xong toàn bộ WAV rồi mới phát.
5. Nhập nội dung và bấm nút tạo giọng.
6. Sau khi hoàn tất có thể tải file WAV 48 kHz.

Mỗi bản render hoàn chỉnh được lưu vào **Lịch sử tạo giọng** trên máy để có thể
nghe lại, tải WAV hoặc xóa riêng từng bản. EditorVoice chỉ nhận WAV PCM hợp lệ,
tự đọc thời lượng từ tệp và giới hạn mỗi bản ở 64 MB để tránh dữ liệu lỗi làm đầy
bộ nhớ. Tối đa 20 bản gần nhất được giữ lại.

Các thẻ `[cười]`, `[thở dài]`, `[hắng giọng]` là tính năng thử nghiệm của v3 Turbo.

Khi bật **Lưu để lần sau dùng lại**, dấu giọng đã trích xuất được lưu cục bộ trong `.quick-studio-data/cloned_voices`. Lần sau mở ứng dụng, chọn lại giọng trong mục **Giọng đã lưu trên máy** mà không cần tải audio mẫu. Mỗi giọng đã lưu có nút **Nghe** để tạo và phát một câu thử bằng chính giọng clone đó; thao tác nghe thử không làm đổi giọng đang chọn. Nút xóa ở cạnh từng giọng yêu cầu bấm xác nhận lần hai để tránh xóa nhầm. Audio gốc không được lưu và không được gửi lên dịch vụ TTS bên ngoài. Chỉ sử dụng giọng của bạn hoặc giọng bạn được phép sử dụng.

## Cấu hình

- Mặc định: ONNX INT8 trên CPU, không cần GPU.
- Lần clone đầu tiên tải thêm speaker encoder khoảng 28 MB; các lần sau dùng lại bản đã lưu trên máy.
- Đổi cổng: đặt biến môi trường `VIENEU_PORT` trước khi chạy.
- Chỉnh số luồng CPU: đặt biến `VIENEU_THREADS` (mặc định engine tự chọn).
- Không tự mở trình duyệt: đặt `VIENEU_NO_BROWSER=1`.

Ứng dụng này sử dụng mã nguồn [pnnbao97/VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), giấy phép Apache‑2.0.
