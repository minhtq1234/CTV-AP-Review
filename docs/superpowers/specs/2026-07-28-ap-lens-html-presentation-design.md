# AP Lens HTML Presentation Design

**Date:** 2026-07-28  
**Status:** Approved interaction concept; pending written-spec review

## Goal

Create a concise Vietnamese HTML presentation that explains how the CTV AP
Review application works to a mixed audience of reviewers, managers, and other
stakeholders.

The presentation title is:

> **AP Lens — Soát hồ sơ CTV thông minh**

The story must communicate both the business value and the practical reviewer
workflow without exposing real names, identifiers, document images, or other
PII.

This work is confined to:

`/Users/lap16603/Documents/New project/work/CTV_APReview-v1`

The v2 checkout is out of scope. The presentation does not change the
application, backend, stored review data, or v1 ports.

## Deliverable

Create one standalone file:

`docs/presentations/ctv-ap-review-overview.html`

It must open directly in a modern desktop browser without a build step,
internet connection, external font, JavaScript package, or remote asset.
HTML, CSS, SVG, and JavaScript must be embedded in the file.

## Narrative Structure

The deck contains exactly five 16:9 slides.

### Slide 1 — AP Lens

Introduce the product with the title
`AP Lens — Soát hồ sơ CTV thông minh` and a short promise:

`Từ bộ chứng từ phức tạp đến quyết định rõ ràng.`

A simple visual flow connects input documents to a focused review screen and a
clear result. The slide establishes the application's purpose: help AP
reviewers locate evidence, compare it with roster data, and record exceptions.

### Slide 2 — Tải lên một lần, hệ thống chuẩn bị phần còn lại

Show three inputs:

- PDF hồ sơ;
- bảng kê Excel; and
- file ảnh CCCD Excel, marked as optional.

Visualize the local pipeline as:

`Tách gói → OCR → Ghép CTV → Định vị bằng chứng`

Explain that the application prepares one reviewable packet per collaborator.
The slide must not imply that OCR makes the final decision. Reviewer judgment
remains authoritative.

### Slide 3 — Một dashboard cho toàn bộ đợt hồ sơ

Present a synthetic packet dashboard with the four mutually exclusive
lifecycle states:

- `Chưa xem`;
- `Đang xem`;
- `Đã xong`; and
- `Flagged`.

Show system attention as a separate amber `!`, plus the
`Cần chú ý trước` sorting control. Explain that filters and counts help the
reviewer plan work while attention highlights packets that deserve an early
look.

### Slide 4 — Xem tổng quan, rồi kiểm tra từng trường

Use a split-screen illustration matching the application:

- left: `Tổng quan` followed by review fields;
- right: a clean two-page document viewer at 100%.

Show the reviewer journey:

1. scan all documents in Overview;
2. select a field;
3. inspect the automatically located evidence and compare it with the roster;
4. mark a field or reject the whole packet when necessary.

The illustration must make clear that the document remains the source of truth
and that cards and packets stay reopenable.

### Slide 5 — Tập trung vào ngoại lệ, xuất kết quả rõ ràng

Close the story with three outcomes:

- trạng thái và tiến độ cập nhật tự động;
- vấn đề được tổng hợp theo từng gói; and
- báo cáo sẵn sàng gửi lại để chỉnh sửa.

End with the value statement:

`Nhanh hơn để rà soát. Dễ hơn để giải trình. Chắc hơn khi quyết định.`

## Visual Direction

Use a polished internal-product aesthetic:

- deep navy background with soft blue radial accents;
- white and pale-slate content surfaces;
- restrained semantic colors matching the application: gray, blue, green,
  pink/red, and amber;
- large sans-serif type, generous whitespace, rounded cards, and subtle
  shadows;
- simple inline SVG icons and schematic UI illustrations rather than product
  screenshots.

Every slide must remain understandable at a glance. Body copy should be short,
and no slide should resemble a dense document page.

All names, values, packet counts, document labels, and identifiers in
illustrations must be synthetic. No real screenshots are embedded.

## Interaction

The deck supports:

- Previous/next buttons;
- Arrow Left/Arrow Right, Page Up/Page Down, Space, and Home/End;
- clickable progress dots;
- a visible `N / 5` position indicator;
- a fullscreen button using the browser Fullscreen API; and
- touch swipe navigation where supported.

Only one slide is active and exposed to assistive technology at a time.
Navigation does not modify the URL or require a router. Direct file opening
must work.

## Responsive and Accessibility Behavior

- Preserve the 16:9 composition on normal desktop and projector dimensions.
- Scale the slide canvas to fit the viewport without horizontal page overflow.
- At narrow widths, keep controls usable and allow complex illustration
  columns to stack inside the scaled composition when necessary.
- Provide visible keyboard focus, semantic buttons, meaningful labels, and
  adequate color contrast.
- Respect `prefers-reduced-motion` by disabling nonessential transitions.
- Use text and icons in addition to color for every status.

## Technical Boundaries

- Do not add a dependency, build script, route, backend endpoint, or application
  component.
- Do not import production case data or assets.
- Do not alter existing v1 behavior or styles.
- Do not touch or copy files from the v2 checkout.
- Do not push unless the user explicitly requests it after the deck is complete.

## Verification

Automated checks will confirm:

- the file is valid enough to parse as HTML;
- exactly five slide elements exist;
- every required slide title and workflow label is present;
- navigation controls and keyboard handlers are present;
- no `http://` or `https://` external asset reference exists;
- no known real PII from the application fixtures is copied into the deck.

Browser QA will confirm:

- direct file loading;
- first-slide presentation;
- button, dot, and keyboard navigation;
- Home/End behavior;
- fullscreen control availability;
- desktop and narrower responsive layouts;
- no horizontal page overflow; and
- zero console errors.

