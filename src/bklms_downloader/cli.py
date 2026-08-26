from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .auth import create_driver, make_session, wait_page
from .config import DEFAULT_OUTPUT, LMS_BASE
from .crawler import DeepDownloader
from .utils import is_course_url


def load_course_urls(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if is_course_url(line):
            urls.append(line)
        else:
            print(f"[WARN] Bỏ qua URL không hợp lệ: {line}")
    return urls


def ask_current_course(driver) -> str:
    print("\nTrong Chrome, mở đúng course BK-LMS cần tải.")
    print("URL: https://lms.hcmut.edu.vn/course/view.php?id=...")
    while True:
        input("Khi đã mở đúng course, nhấn Enter tại đây...")
        wait_page(driver)
        if is_course_url(driver.current_url):
            return driver.current_url
        print("Chưa phải URL course BK-LMS. Hãy mở course rồi thử lại.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bklms",
        description="Tải và sắp xếp tài liệu BK-LMS theo section/course.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Thư mục gốc để lưu")
    p.add_argument("--course-url", help="URL một course BK-LMS")
    p.add_argument("--courses-file", type=Path, help="TXT chứa nhiều course URL")
    p.add_argument("--force", action="store_true", help="Tải lại file đã tồn tại")
    p.add_argument("--max-depth", type=int, default=4, help="Độ sâu link Moodle, mặc định 4")
    p.add_argument("--archive", action="store_true", help="Complete archive: giữ HTML + shortcut ngoài")
    p.add_argument(
        "--no-follow-linked-courses", action="store_true",
        help="Không crawl course học liệu được liên kết từ course chính",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    driver = None
    try:
        print("Đang mở Chrome...")
        driver = create_driver()
        driver.get(LMS_BASE)
        wait_page(driver)

        print("\nĐăng nhập BK-LMS trực tiếp trong Chrome.")
        print("Tool không yêu cầu và không lưu mật khẩu của bạn.")
        input("Đăng nhập xong thì nhấn Enter tại đây...")
        wait_page(driver)
        session = make_session(driver)

        if args.courses_file:
            course_urls = load_course_urls(args.courses_file)
            if not course_urls:
                raise RuntimeError("File courses không có URL BK-LMS hợp lệ.")
        elif args.course_url:
            if not is_course_url(args.course_url):
                raise RuntimeError("--course-url không hợp lệ.")
            course_urls = [args.course_url]
        else:
            course_urls = [ask_current_course(driver)]
            session = make_session(driver)

        for i, course_url in enumerate(course_urls, start=1):
            if len(course_urls) > 1:
                print(f"\n******** COURSE {i}/{len(course_urls)} ********")
            downloader = DeepDownloader(
                session=session,
                output=output,
                force=args.force,
                max_depth=max(0, args.max_depth),
                follow_linked_courses=not args.no_follow_linked_courses,
                archive_mode=args.archive,
            )
            downloader.crawl_course(course_url, output, depth=0)
        return 0
    except KeyboardInterrupt:
        print("\nĐã dừng.")
        return 130
    except Exception as exc:
        print(f"\nLỖI: {exc}")
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
