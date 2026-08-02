from datetime import date

from datetime import datetime
from zoneinfo import ZoneInfo

from facebook_newsletter import LOCAL_PDF_START, dom_image_count, extract_posts, filter_date_for_week, ordered_photo_images, parse_cookie_header, parse_relative_time, unscaled_url, week_range


def test_parser():
    doc = {
        "data": {
            "node": {
                "id": "post-1",
                "creation_time": 1721000000,
                "actors": [{"name": "Raceland GmbH"}],
                "message": {"text": "Hier ist das Raceland Newsletter Magazine!"},
                "attachments": [
                    {
                        "all_subattachments": {"count": 13, "nodes": []},
                        "media": {"image": {"uri": "https://scontent.xx.fbcdn.net/a.jpg?stp=p720", "width": 720, "height": 480}},
                    }
                ],
            }
        }
    }
    posts = extract_posts(doc)
    assert posts[0]["id"] == "post-1" and len(posts[0]["images"]) == 1
    assert posts[0]["image_count"] == 13
    assert "stp=" not in unscaled_url(posts[0]["images"][0]["url"])
    doc["data"]["node"]["message"]["text"] = "普通图片帖子"
    assert extract_posts(doc) == []
    start, end, label = week_range("2026-W29")
    assert (start, end, label) == (date(2026, 7, 13), date(2026, 7, 20), "2026-W29")
    cookies = parse_cookie_header("Cookie: c_user=123; xs=abc=def; wd=1920x1080")
    assert {cookie["name"] for cookie in cookies} == {"c_user", "xs", "wd"}
    now = datetime(2026, 7, 18, 16, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    assert parse_relative_time("19小时", now).date() == date(2026, 7, 17)
    assert parse_relative_time("8月22日", now, default_year=2025).date() == date(2025, 8, 22)
    links = [
        "https://facebook.com/photo/?fbid=1&set=pcb.99",
        "https://facebook.com/photo/?fbid=2&set=pcb.99",
        "https://facebook.com/photo/?fbid=3&set=pcb.99",
        "https://facebook.com/photo/?fbid=avatar",
    ]
    assert dom_image_count(links, ["+11"]) == 13
    assert filter_date_for_week(date.fromisocalendar(2025, 14, 1)) == date(2025, 4, 4)
    assert filter_date_for_week(date.fromisocalendar(2026, 28, 1)) == LOCAL_PDF_START
    viewer = {"b": {"photo_id": "b", "url": "b"}, "a": {"photo_id": "a", "url": "a"}}
    assert [image["photo_id"] for image in ordered_photo_images(viewer, ["a", "b"])] == ["a", "b"]


if __name__ == "__main__":
    test_parser()
    print("ok")
