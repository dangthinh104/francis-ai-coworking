---
name: ui-copy
description: How to write the words a user reads in the product - labels, buttons, toasts, errors, empty states, emails - so they sound like a person wrote them in the user's language. Use whenever you add or change a user-facing string or a locale file, and when reviewing a screen.
---

# Words on the screen

A message is written for the person looking at the screen, in their words, about their task. It is not a report from the code.

Where a message appears (toast, dialog, banner, inline) follows the project's own pattern when it has one; these rules then govern the words in it. Where the project's wording rules are stricter, they win.

Read the project's voice file first: `docs/VOICE.md` (who we talk to, how we address them, the words this product uses). No file: create it from `${CLAUDE_SKILL_DIR}/templates/VOICE.md` with the user before writing strings. Do not pick a form of address yourself.

## Rules

1. **Say what happened in the user's terms.** Name the thing they see, not the table, model, field or status code. "Phiếu đã gửi cho anh Minh", not "Tạo bản ghi thành công".
2. **An error says what to do next.** What went wrong, in plain words, then the one thing the user can do. If there is nothing they can do, say what we are doing or whom to contact. Never only "Đã xảy ra lỗi".
3. **Write it in the language, do not translate it.** Draft each language from the meaning. Vietnamese: active voice; no passive "được/bị" where an active verb reads better ("Hóa đơn đã được tạo" becomes "Đã tạo hóa đơn"), while "được" for ability stays ("chưa lưu được"); no "thực hiện/tiến hành + noun" where a verb will do; no "vui lòng" on every line. Vietnamese often drops the subject: "Đã lưu", not "Bạn đã lưu thành công".
4. **One form of address, everywhere.** The one in `VOICE.md`. Never mix "bạn", "anh/chị", "quý khách" in one product.
5. **Short.** A toast confirms one finished action in a few words. A button is a verb, the same verb the confirmation uses ("Gửi phiếu" then "Đã gửi phiếu"). No exclamation marks, no "thành công" tacked on, no apology unless we did damage.
6. **The right place.** Toast: an action just finished and nothing more is needed. Next to the field: what is wrong with this field. Banner or dialog: something that blocks the user or cannot be undone. An error does not go in a toast unless it will stay until fixed (for example, offline).
7. **Use the product's words.** The glossary in `VOICE.md` is the only name for each thing. A new term is added there first.
8. **No internal detail.** No ids, codes, stack traces, English enum values or key names on screen. Log them; show a sentence.

## Examples

| Instead of | Write |
|---|---|
| Thao tác thành công! | Đã lưu |
| Đã xảy ra lỗi. Vui lòng thử lại sau. | Mất mạng nên chưa lưu được. Anh/chị thử lại nhé. |
| Dữ liệu không hợp lệ | Số điện thoại phải có 10 chữ số |
| Bạn không có quyền thực hiện hành động này | Chỉ quản trị viên mới duyệt được kỳ này |
| Xóa bản ghi thành công | Đã xóa phòng 203 |
| Lưu thất bại | Chưa lưu được. Kiểm tra lại ô đang báo đỏ. |
| Bạn có chắc chắn muốn thực hiện hành động này? | Chốt sổ tháng 11? Sau đó không sửa được hóa đơn. |
| Không tìm thấy dữ liệu | Chưa có hóa đơn nào trong tháng 11 |
| Are you sure you want to delete? | Delete room 203? This cannot be undone. |

The right-hand side uses the address and terms of one example product. Take the pattern, not the words.

## Check

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/copy_audit.py" <locale file or directory> [...]
python3 "${CLAUDE_SKILL_DIR}/scripts/copy_audit.py" --strict <path>     # exit 1 when anything is flagged
python3 "${CLAUDE_SKILL_DIR}/scripts/copy_audit.py" --display media --display home.hero <path>
```

`--display` names key prefixes whose text is a picture, not a control: a heading set in capitals, a venue's registered name, a greeting composed onto a generated image. The tone rules (`stock`, `shout`) are not applied there; an internal name that leaks is still flagged. The prefixes are the project's, listed under "Display copy" in `docs/VOICE.md`, so every run uses the same ones. A single word is treated as a label unless its key says it is the whole message (`toast`, `error`, `message`).

The script flags short strings built on a stock phrase, internal detail, shouting, and overlong toasts, buttons and labels, and counts how often "vui lòng" or "please" appears. It cannot tell whether a sentence sounds natural: for that, a person who speaks the language reads a sample. When you add more than a handful of strings, list them in the pull request as a table (key, text per language) so they can be read without opening the app.

## When the user corrects a string

Add the corrected wording to the glossary or the examples in `docs/VOICE.md`, so the next string is written that way.
