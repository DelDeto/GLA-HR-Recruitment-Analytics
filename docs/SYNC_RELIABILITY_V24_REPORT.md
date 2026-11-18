# GLA HR V2.4 — Kiểm chứng và triển khai ngày 18/11/2026

## FULL DRY RUN trước khi ghi

FULL DRY RUN trực tiếp đã hoàn tất lúc **15:25:36 ngày 18/11/2026, giờ Việt Nam**. Kết quả **PARTIAL, chưa đạt nghiệm thu toàn bộ**, ghi production **0**. Không bật thưởng NHÁP hoặc sửa các fact lịch sử xung đột.

Bằng chứng: [full run 44265174021](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/44265174021), mã `fb676c401591571a214a6656d93805ecba076a82`, run nội bộ `f6acd1cb3ac3c87508fa5af46b7adce1c0d24d5f5d4dd0d264ed7267d26d513b`. Lần FULL DRY RUN trước dùng bộ đọc chậm đã hủy khi bản tối ưu thay thế; không tính lần hủy là nghiệm thu.

## Kết quả trên dữ liệu thật

- Đọc đủ **16/16 file, 182 tab**; toàn bộ schema có hợp đồng đã rà soát. Tab mới hoặc đổi header phải được kiểm tra lại.
- Meta Marketing API trực tiếp: **3 tài khoản, 3.838 dòng**, kỳ 01/01–18/11/2026.
- **2.043 ô lỗi công thức nguồn**: 5 lỗi trường Lead tiêu thụ được cách ly; 2.038 lỗi thuộc phạm vi loại trừ đã kiểm chứng. Cách ly 3.197 dòng Lead; Sales legacy còn 1.663 dòng thiếu ngày và 25 dòng cần đối soát. Không tự suy diễn ngày hoặc định danh.
- Cả A/B không có lỗi công thức native tại lần đọc cuối. **A có thay đổi bên ngoài trong khi kiểm thử**: 474.233 → 474.746 ô có giá trị nhập, hash giá trị nhập và vùng bảo vệ không khớp. **B không thay đổi**, 458.153 ô. Đích thay đổi sẽ bị giữ khi áp dụng.

| Nhánh | Kế hoạch mỗi file | Quyết định toàn bộ |
|---|---:|---|
| Lead | 122 dòng / 663 ô | PARTIAL; giữ 10 dòng đích cần xét giảm lịch sử và nguồn cách ly |
| PV/OB | 7 dòng / 56 ô | PARTIAL; giữ 102 nhóm định danh/alias cần đối soát |
| Công, phí thực tế | 23 dòng / 457 ô | PARTIAL; giữ 270 fact lịch sử xung đột |
| Dự báo | 553 dòng / 576 ô kỹ thuật | Chưa ghi vì nguồn phụ thuộc PARTIAL |
| Thưởng | 0 được ghi | Thiếu ca nghiệm thu chính sách xác nhận; giữ nguyên NHÁP và nhật ký |
| Meta full-year | Chỉ đọc đối soát | Native chưa bằng snapshot API; không coi đồng bộ 8 ngày là khôi phục đủ năm |

Đối soát độc lập **tháng 9** PASS: 420 Lead, 66 PV/OB, 566 fact công ngày, 14 fact kỳ; dự báo cùng phạm vi 9 dòng tháng × nhà máy khớp phép tính độc lập. Bộ lọc A và B khác kỳ được giữ nguyên. Cache native tổng thể còn `NATIVE_CROSS_FILE_MISMATCH`; kết quả tháng 9 không chứng minh toàn năm hoặc tháng hiện tại đã bằng nhau.

## Môi trường và credentials

Không cần người dùng cung cấp token trong chat hoặc cài runner trên máy cá nhân. GitHub Actions hiện có dùng trực tiếp repository secrets Google/Meta. Sáu chương trình private được lấy từ đúng ô kho mã hiện hữu, kiểm tra SHA256 rồi mới chạy trong thư mục tạm quyền riêng tư. Đã bổ sung dependency `lxml`. Public repo không chứa nội dung các chương trình private, nhân sự, manifest tài nguyên hoặc credentials.

Generic full runner vẫn có `deployment_approved=false` và `single_writer_private_volume=false`. Job GitHub-hosted tạm thời không được nhận là private volume bền vững.

## Chế độ chạy độc lập có giới hạn

`src.sync_daily` bổ sung chế độ đồng bộ Meta A/B và sao chép các phần fact độc lập đã kiểm chứng. Đây **không phải** nghiệm thu hoặc mở khóa full V2.4:

- Meta: lập kế hoạch chỉ đọc cho **cả A và B trước khi ghi file nào**, giữ cửa sổ cập nhật 8 ngày và cơ chế bù gián đoạn hiện hữu. Khóa theo account/date/campaign, không nhân đôi khi retry. Đọc lại giá trị native trước khi ghi checkpoint SUCCESS. Tên chiến dịch được ép literal, không thực thi công thức từ tên Meta.
- Lead/PV/công: chỉ dùng normalization VALIDATED và phần kế hoạch có lý do cách ly được allowlist. Kiểm tra hash trước/sau DRY RUN; trước mỗi lần ghi kiểm tra native stable key, preimage, quyền sở hữu vùng; sau ghi đọc lại từng ô và quét vùng bảo vệ/công thức.
- Công/phí chỉ được bổ sung khi episode tương ứng có đúng một định danh nguồn và có parent OB khớp native theo nhà máy, mã, tên, ngày vào; giữ nguyên hàng con nếu parent chưa đạt.
- Không nâng watermark/last-good từ phần nguồn PARTIAL. Không đổi công/phí lịch sử xung đột, không ghi forecast và thưởng. Nếu A thất bại, B có thể hoàn tất phần an toàn và lần sau lấy lại preimage mới; không replay mù kế hoạch cũ.
- Một concurrency group `gla-meta-ads-daily-sync` dùng chung primary, watchdog và chẩn đoán có credentials. Chỉ môi trường Actions/repository định danh đã duyệt và job có coordinator mới được dùng scoped copy.

**185 tests PASS** tại workspace sau bổ sung scoped-copy; bao gồm mất coordinator, thiếu proof, thay preimage, nguồn chưa validation, lý do giữ không biết, đọc lại sai, parent OB thiếu/xung đột và retry không nhân đôi.

## Kiểm thử Meta hai file

[Run 44269885851](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/44269885851), hoàn tất 15:46:55 ngày 18/11/2026: **PASS**, 175 unit tests và Meta A/B DRY RUN trực tiếp cùng snapshot. Đọc 111 dòng trong cửa sổ cập nhật; A dự kiến cập nhật 20 dòng, B cập nhật 95 dòng (70 bổ sung), B thêm 3 mapping chiến dịch. Production writes = 0.

## Cấu hình lịch dự kiến triển khai

Tái sử dụng workflow primary hiện hữu, thay các lượt 07:15/07:25/07:45/08:15 bằng **08:00, 13:00, 18:00 giờ Việt Nam** (`0 1,6,11 * * *` UTC). Cả ba lượt phải refresh, không skip vì checkpoint cùng ngày. Watchdog hiện hữu chỉ bù khi thiếu checkpoint, dùng cùng khóa và kiểm tra riêng A/B. Không tạo workflow lịch ghi thứ hai; tác vụ ChatGPT cũ giữ tạm dừng.

Trạng thái triển khai thực tế, SHA cố định và lần chạy ghi đầu tiên phải được ghi bổ sung sau khi GitHub xác nhận; đoạn cấu hình dự kiến này chưa chứng minh lịch mới đã bật. GitHub cron có thể chạy trễ so với phút cấu hình.


## Triển khai thực tế và lượt ghi đầu tiên

Đã triển khai lên `main` qua commits `b60bc2614bab5821085144eaafa76fc83bdb7f14` (primary) và `5ae7f4758845c76402174aff8ff3b6e3c9077b33` (watchdog). Hai workflow checkout cố định runtime đã qua 185 tests `1f0bf388a2eb16436d3ddf70b8ee3bd888dba325`. Đã đọc lại nội dung workflow để xác minh cron **08:00/13:00/18:00 giờ Việt Nam**, cùng một khóa, không skip lượt chính vì đã có checkpoint hôm nay. Watchdog hiện hữu 09:10/12:10 chỉ phục hồi Meta khi thiếu checkpoint trên từng file. Tác vụ ChatGPT cũ giữ **disabled**; không tạo một lịch writer mới.

[Run production 44270592980](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/44270592980), attempt 1, hoàn tất **16:05:46 ngày 18/11/2026**:

| Phạm vi | A | B |
|---|---|---|
| Meta cửa sổ 8 ngày | SUCCESS; 20 dòng thay đổi | SUCCESS; 95 dòng thay đổi, 70 bổ sung, 3 mapping mới |
| Lead | HELD, đích thay đổi trong lúc DRY RUN | 123 dòng / 669 ô đã ghi và đọc lại |
| PV/OB | HELD cùng lý do | 7 dòng / 56 ô đã ghi và đọc lại |
| Công/phí bổ sung | HELD | 0 ghi; 23 dòng chưa khớp parent OB nên giữ |
| Forecast / thưởng | HELD | HELD |

Có 2 batch ghi nguồn trên B; không nâng watermark/last-good từ nguồn PARTIAL. Meta có checkpoint native A lúc 15:51:59 và B lúc 15:52:03, chỉ ghi SUCCESS sau đọc lại. Hash vùng bảo vệ sau scoped copy B khớp; 0 lỗi công thức native. A tăng 474.746 → 474.852 ô có giá trị nhập khi đang kiểm thử, nên không ghi nguồn vào A. Lịch sử revision Google ghi nhận sửa từ tài khoản người dùng lúc 15:52:45; không khẳng định đây là trigger hoặc thao tác tay. Không có job GitHub khác đang chạy tại lúc kiểm tra, các tác vụ ChatGPT GLA tìm thấy đều disabled.

Full scan lần này vẫn đủ 16 file/182 tab, Meta 3 tài khoản/3.838 dòng. Lỗi công thức nguồn hiện là 2.045 (5 trường tiêu thụ cách ly, 2.040 loại trừ đã kiểm chứng). Đối soát cùng kỳ tháng 9 vẫn PASS; cache tổng thể vẫn chưa bằng nhau. Trạng thái job failure/exit 2 phản ánh A bị giữ, không phải tuyên bố toàn bộ dữ liệu đã đồng bộ.

Đã yêu cầu **rerun đúng job cũ**, attempt 2, trên snapshot mới để thử lại A. Không replay kế hoạch cũ và không thêm lịch. Kết quả attempt 2 chưa được xác nhận tại thời điểm cập nhật đoạn này.


### Khôi phục tự động khi đích thay đổi trước ghi

Runtime mới `3fc7bdca0f67ba31cbf170cef80cb109dd9fd4cf` bổ sung tối đa một lần thử lại bằng thư mục private, nguồn, snapshot đích và kế hoạch hoàn toàn mới khi phát hiện `NATIVE_TARGET_CHANGED_DURING_DRY_RUN` hoặc `SCOPED_COPY_PROTECTED_PREIMAGE_CHANGED`. Không replay stage cũ, không nới quyền vùng ghi, không nâng watermark, không thử lại lỗi đọc lại không rõ nguyên nhân. Sau hai lần vẫn xung đột thì giữ trạng thái HELD. Dry-run không tự chuyển sang apply.

**194 tests PASS** tại CI push [44273631080](https://github.com/DelDeto/GLA-HR-Recruitment-Analytics/actions/runs/44273631080), gồm state directory mới cho từng lượt, giới hạn số lần thử, cộng số batch được xác nhận, giữ lỗi sau lần thử cuối và không retry lỗi readback. Primary/watchdog trên main đã pin runtime mới qua `6bbed679ce027d505d79a0dbe0f378ed0372f8ea` và `7210426aab316e06acf223e9e8707bd031875106`; đã đọc lại để xác minh. Lượt retry production đang chạy vẫn dùng runtime cũ được pin theo commit của run; cơ chế mới áp dụng cho lượt được tạo sau cập nhật này.

Native Meta trong attempt 2 đã xác minh SUCCESS A lúc **16:08:07**, B lúc **16:08:11**. Mỗi file fetched 111, changed 13, appended 0, new campaigns 0; đây là cập nhật lại các khóa hiện hữu, không bổ sung dòng trùng.
