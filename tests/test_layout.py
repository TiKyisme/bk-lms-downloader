from bklms_downloader.layout import (
    bucket_name_for_section,
    context_prefix,
)


def test_lab_sections_are_grouped():
    assert bucket_name_for_section("Lab 1_ Introduction to Networking") == "03_Lab"
    assert bucket_name_for_section("Lab 8_ Wireless Network") == "03_Lab"
    assert bucket_name_for_section("Thực hành tuần 4") == "03_Lab"


def test_assignment_sections_are_grouped():
    assert bucket_name_for_section("Assignment 1_ Building a network") == "04_Bài tập"
    assert bucket_name_for_section("Bài tập lớn") == "04_Bài tập"
    assert bucket_name_for_section("Assignment Reports") == "04_Bài tập"


def test_common_course_buckets():
    assert bucket_name_for_section("Announcements") == "01_Thông tin môn học"
    assert bucket_name_for_section("Chapter 3 - Transport Layer") == "02_Bài giảng"
    assert bucket_name_for_section("Textbook") == "05_Tài liệu tham khảo"
    assert bucket_name_for_section("Anything else") == "06_Khác"


def test_context_prefix_is_readable():
    assert context_prefix("Lab 1", "Packet Tracer") == "Lab 1 - Packet Tracer - "
    assert context_prefix("Lab 1", "Lab 1") == "Lab 1 - "
