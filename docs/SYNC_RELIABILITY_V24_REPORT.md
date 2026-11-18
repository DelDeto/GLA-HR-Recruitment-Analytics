# GLA HR V2.4 — Quyết định triển khai ngày 18/11/2026

**Giữ trạng thái production hiện tại.** Lead và PV/OB đã có kế hoạch riêng cho các dòng đủ căn cứ trên snapshot. Hai nhánh này là ứng viên triển khai trước, sau khi cùng kế hoạch đó được xác minh bằng FULL DRY RUN trực tiếp và được duyệt ghi. Số dòng được phép ghi ngay hiện tại là **0 trên A và 0 trên B**.

Mã triển khai `87cf3f0141bb71466f4f27ba8969a34961651b3b` thuộc PR #3. `--apply`, lịch và các trigger hiện tại giữ nguyên trạng thái. CTECH nằm ngoài phạm vi theo xác nhận của người dùng.

## Quyết định theo nhánh và file

Số dòng bên dưới là số dòng vật lý dự kiến thay đổi trong snapshot, tính riêng cho mỗi file. Chúng chưa phải số ghi được xác minh với Google Sheets hiện tại.

| Nhánh | A | B | Quyết định |
|---|---:|---:|---|
| Lead | 113 dòng, 609 ô | 113 dòng, 609 ô | PARTIAL. Ưu tiên phần đã lập kế hoạch. Giữ 7 dòng đề xuất giảm số lịch sử trên mỗi file và cách ly bản ghi thiếu căn cứ. |
| PV/OB | 6 dòng, 48 ô | 6 dòng, 48 ô | PARTIAL. Ưu tiên 6 sự kiện bổ sung. Giữ 105 mục đối soát mỗi file gồm khóa, định danh và hồ sơ thiếu mã. Giữ ghi chú và nguồn của sự kiện lịch sử. |
| Công và phí thực tế | 0 | 0 | Giữ nguyên. PV/OB còn PARTIAL. Giữ 270 dòng khác biệt lịch sử mỗi file, gồm 135 khác biệt nguồn hoặc ghi chú và 135 đề xuất đổi phí hoặc điều kiện của Quanta. |
| Forecast V2.2 | 0 được xét ghi | 0 được xét ghi | Giữ nguyên. Có kế hoạch kỹ thuật 2.549 dòng trên mỗi file nhưng phụ thuộc công và PV/OB. Đối soát theo bộ lọc hiện tại chưa đạt. |
| Thưởng V19 | 0 | 0 | Giữ nguyên 12 chính sách NHÁP và nhật ký. Thiếu ca nghiệm thu đã xác nhận và phụ thuộc công chưa đạt. |
| Meta | 0 | 0 | Chỉ đọc để đối soát. API đã PASS trong job trước. Cần snapshot trực tiếp trong cùng lần chạy và đối chiếu native A/B. Giữ các tổng đã chốt. |

Nếu một nguồn thiếu toàn bộ dữ liệu cần thiết, nhánh tiêu thụ nguồn đó báo PARTIAL và giữ last-good. Runner giữ riêng kế hoạch và checkpoint của từng nhánh trên mỗi file. Phần hợp lệ của kế hoạch PARTIAL có thể được duyệt bằng hash tương ứng khi có phê duyệt ghi riêng. Việc ghi phần đó giữ nguyên last-good và không mở khóa các nhánh phụ thuộc. Bản ghi cách ly vẫn nằm trong đầu vào private và không được tự sửa hoặc tự điền.

## Bằng chứng và giới hạn

- **Kiểm chứng quyền và vận chuyển dữ liệu trực tiếp** trong run `44219333231`, job `134516998914`. Service account canEdit trên A/B, đọc đủ 16/16 file và 182 tab. Meta Marketing API trả 3.837 dòng từ 3 tài khoản qua 18/11. Lần này ghi nhận 2.045 ô lỗi công thức nguồn. Số lỗi này cần phân loại bằng consumer trong lần FULL DRY RUN hiện tại.
- **Chạy lại đủ nhánh trên snapshot private 17/11** với run `44e43ec531ef4aa591015ce864b31f1f07604dbff593147edf397acf43c18742`. Đọc 16 file và 182 tab với mỗi file đọc một lần. Đối chiếu quyền sở hữu vùng ghi, khóa và giá trị trước ghi của từng dòng dự kiến. Hash vùng bảo vệ và hash giá trị nhập trước/sau giữ nguyên trên cả hai file. Quét toàn bộ ô snapshot của A/B thấy 0 lỗi công thức. Đọc lại vùng dự kiến chạy trên bản snapshot. Xác minh đọc lại qua API và công thức sau thay đổi cần lần chạy trực tiếp.
- **Phân loại lỗi ở snapshot 17/11**. Trong 574 ô lỗi đã phân loại, 572 thuộc trường không được dùng hoặc có định danh thay thế kiểm chứng được. Hai hồ sơ CRM có lỗi định danh tiêu thụ được giữ cách ly. Cơ chế mới cách ly 3.185 dòng Lead theo trường thực tế gồm 3.038 thiếu ngày, 145 thiếu định danh và 2 lỗi công thức trường tiêu thụ. Các tab Sales bổ sung còn 1.657 dòng chưa có ngày và 25 dòng cần định danh. Các con số này thuộc snapshot 17/11. Phạm vi 2.045 ô lỗi ngày 18/11 chưa được phân loại.
- **Đối soát A/B trên snapshot**. Cùng kỳ 01/09–17/11, nhóm LĐPT và tất cả nhà máy, các fact Lead, PV/OB và phí thực tế khớp. Dự báo quy về 36 dòng tháng × nhà máy khớp với kết quả tính độc lập. Cache hiển thị native chưa khớp (`NATIVE_CROSS_FILE_MISMATCH`). Bộ lọc của từng file giữ nguyên.
- **FULL DRY RUN trực tiếp** dừng trước bước đọc tại attempt `1f6340c86f4545c09d9c42c388bb4cf6` do `GOOGLE_SERVICE_ACCOUNT_JSON_MISSING`. Workspace chứa manifest private và chương trình đã pin SHA, còn credential đã PASS chỉ được cấp vào job chẩn đoán hiện có. Số ghi production và số checkpoint được nâng đều bằng 0. A/B vẫn PARTIAL trong replay và BLOCKED đối với quyết định ghi.
- **153 kiểm thử PASS** tại CI run `44223809572` và workspace. Run CI này kiểm tra mã triển khai. Job chẩn đoán truy cập trước đó cung cấp bằng chứng quyền riêng.

## Việc cần quyết định hoặc cung cấp

1. **Môi trường FULL DRY RUN.** Cho phép runner private hiện có nhận credential Google và Meta đang dùng từ kho bí mật của tổ chức, hoặc cung cấp vị trí runtime private đã nhận các biến đó. Quyền chia sẻ Google của service account hiện tại đã PASS. Lệnh chạy dùng bản manifest `round6-deployment-decision/production-manifest.json` và state directory chỉ chủ sở hữu truy cập. Chạy `python -m src.sync_runner --config PRIVATE_MANIFEST --state-dir PRIVATE_STATE` trong runtime đó. Runner đọc lại A/B và toàn bộ nguồn, chụp Meta trong cùng runtime, xác minh các chương trình với vị trí SHA còn hiện hành và xuất kế hoạch theo file/nhánh.
2. **Phê duyệt ghi từng phần sau kết quả trực tiếp.** Duyệt đúng số dòng và hash kế hoạch Lead và PV/OB trên từng file. Các dòng đang giữ được tách khỏi lần phê duyệt này. Giữ last-good cho các nhánh PARTIAL.
3. **Chỉ xác nhận các ngoại lệ khi cần đưa chúng vào dữ liệu.** Bổ sung ngày hoặc định danh có căn cứ cho Lead, xác nhận 7 dòng giảm số lịch sử nếu có đính chính, xác minh hồ sơ và khóa PV/OB khi bổ sung. Phí Quanta yêu cầu bảng công và ngày nghỉ có chứng từ trước khi đổi điều kiện. Thưởng yêu cầu một chính sách thực tế đã xác nhận cùng ca nghiệm thu. Các ngoại lệ này có thể tiếp tục cách ly trong khi duyệt các dòng độc lập đủ căn cứ.

Bản ghi người lao động, nội dung manifest, nguồn riêng và chứng cứ chi tiết được giữ trong các thư mục private. Không merge, thay workflow, bật lịch, tạo trigger hay ghi Sheets trong lần này.


## Tiếp nhận trực tiếp trong Work Mode — 18/11/2026

### Kiểm chứng tại môi trường tiếp nhận

- Đã checkout đúng PR #3 tại `10f0c91e3ddbe6394057ac571ae232060f1f0f41`, cài dependencies và chạy `python -m pytest -q`: **153 passed**. Đây là kiểm thử mã, không phải nghiệm thu toàn bộ dữ liệu thật.
- Đã đọc metadata trực tiếp của A/B và các vùng checkpoint `META_SYNC_HEALTH!A1:I12`, `QL_PIPELINE!A1:T8`. Checkpoint SUCCESS cuối cùng quan sát được của Meta trên A là **17/11/2026**, trên B là **13/11/2026**. Hai file chưa có cùng mốc cập nhật Meta. Không suy ra dữ liệu đầy đủ chỉ từ checkpoint.
- Đã xác minh tác vụ hiện có “Đồng bộ GLA HR — 2 file (chờ runner)” có lịch 08:00, 13:00, 18:00 theo Asia/Ho_Chi_Minh nhưng đang **tạm dừng**. Lần chạy được ghi nhận gần nhất ngày 17/11 là failed; kết quả chỉ có thông báo lỗi chung, không đủ căn cứ quy lỗi cho token hay dữ liệu. Không tạo hoặc bật tác vụ khác.
- Đã kiểm tra workflow Meta và watchdog trên `main`: đây là các lịch riêng cho Meta, không phải lịch đồng bộ sáu nhánh A/B. `src.meta_sync.Settings.from_env` hiện nhận **một** `GOOGLE_SHEET_ID`. Workflow xanh không chứng minh B hay các nhánh Lead/PV/OB/công/doanh thu/thưởng đã được cập nhật.
- Workspace tiếp nhận không có các biến Google/Meta cần thiết, không có private production manifest và bundle chương trình được pin SHA. Chạy canary tại đây dừng an toàn với `GOOGLE_SERVICE_ACCOUNT_JSON_MISSING`; production_writes=0. Hai launcher shell được lưu trước đây chỉ kiểm tra và gọi runner, không chứa manifest hay bộ chương trình private.
- Kết nối Google Drive của Work Mode đọc được A/B, nhưng không cấp credential cho tiến trình Python. GitHub connector cũng không xuất giá trị Actions Secrets. Không đưa secrets ra log, file báo cáo hoặc chat.

### Sửa chẩn đoán credentials trong PR

Tại workspace mới, canary trước đây trả lỗi Meta chung khi biến account chưa được cấp vì gọi bộ phân tích account trước khi kiểm tra biến. Đã sửa thứ tự kiểm tra và chuyển lỗi cấu hình account về mã an toàn `META_RUNTIME_TOKEN_OR_AUTHORIZED_ACCOUNT_SCOPE_MISSING`. Sáu ca kiểm thử chứng minh cấu hình thiếu/sai/phạm vi account không được phép đều dừng trước khi tạo API client; không in token/account sai. Sau sửa: **159 kiểm thử PASS**. Thay đổi chỉ ở chẩn đoán chỉ đọc, không sửa writer hay workflow. Private bundle phải được kiểm tra/pin lại nếu bao gồm module thay đổi.

### Bước còn thiếu để FULL DRY RUN

Cần gắn vào phiên làm việc **runtime private đã giữ bundle V2.4 và `round6-deployment-decision/production-manifest.json`**, đồng thời cấp các biến Google/Meta qua kho bí mật của runtime. Nếu bundle còn ở môi trường cũ, đưa nguyên bundle và manifest sang runtime private được chọn; không đặt trong repository public hoặc workflow inputs. Không cần gửi token trong chat hoặc chia sẻ lại Google Sheets khi quyền hiện tại vẫn đạt.

Trong runtime đó, xác minh SHA theo mã PR đang chọn, cập nhật `as_of` đúng ngày Việt Nam, giữ `deployment_approved=false`, chạy launcher chỉ đọc hiện có. FULL DRY RUN cần đọc lại nguồn và A/B, chụp Meta trong cùng lần chạy, phân loại lỗi theo trường thực tế tiêu thụ, xuất kế hoạch/hash từng nhánh và file, kiểm tra vùng bảo vệ, so sánh cùng kỳ/nhóm và giữ last-good. Chưa có kết quả này thì không đề nghị ghi production.

Khi nghiệm thu đủ và được duyệt ghi riêng, dùng lại lịch hiện có; mọi thay đổi writer Meta phải đi kèm kiểm kê vùng sở hữu và chống chạy đồng thời. Không bật lịch chỉ để thử credentials. Giữ nguyên chính sách NHÁP, phí/override đã duyệt và dữ liệu lịch sử trong thời gian chờ.


### Kiểm chứng credentials trực tiếp sau tiếp nhận

Đã thực sự rerun **job chỉ đọc hiện có**, không dispatch workflow ghi Meta: run `44219333231`, attempt 2, job `134645977393`, hoàn tất **14:29:54 ngày 18/11/2026 (giờ Việt Nam)**. Canary dùng commit gốc `7522eea243a4282bc755d597cb34a8d6c89e4473`; do đó không được coi là FULL DRY RUN của commit mới. Kết quả:

- Canary PASS; service account đọc được các tài nguyên được duyệt, A/B đều canEdit.
- Đọc đủ **16/16 file, 182 tab**, lỗi vận chuyển `errors=[]`.
- Phát hiện **2.037 ô lỗi công thức nguồn**. Đây là số mới; không dùng số 2.045 của lần trước để kết luận hiện trạng. Chưa phân loại theo consumer của runner private trong lần này.
- Meta Marketing API trực tiếp: **3 tài khoản, 3.838 dòng**, kỳ 01/01–18/11/2026, snapshot SHA256 `5f187e0a1275ac413c30ee060de76c5db6f297a6a27cdbc8ca1a31fbd59b3968`.
- `production_writes=0`, `release_state=BLOCKED`, `full_v24_e2e=NOT_RUN_DATA_RELEASE_GATES_REMAIN`. Canary không giữ bản dữ liệu raw sau job; không phải bộ dữ liệu để giả lập một lần FULL DRY RUN mới.

Bản sửa `4693178ba26a086814504dc814da1050193066f9` có **159 tests PASS** tại workspace và CI push `44258957234`, PR `44258963991`. Hai CI mới không chạy bước canary và không thay thế bằng chứng kiểm thử trực tiếp ở trên.
