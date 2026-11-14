"""Add / reject / reorder / delete sidebar links on a throwaway DB. Run: python tests/smoke_links.py"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.dirname(HERE))

from streamlit.testing.v1 import AppTest  # noqa: E402

from core import db, links  # noqa: E402

eng = db.get_engine(os.environ["DATABASE_URL"])


def saved():
    return links.get_links(db.load_all(eng, "local@dev")["settings"])


def page():
    at = AppTest.from_file(os.path.join(HERE, "harness.py"), default_timeout=120)
    at.session_state["_view"] = "settings.py"
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


def add(name, url):
    at = page()
    [t for t in at.text_input if t.label == "Name"][0].input(name)
    [t for t in at.text_input if t.label == "Link (URL)"][0].input(url)
    [b for b in at.button if b.label == "Add link"][0].click().run()
    assert not at.exception, [e.message for e in at.exception]
    return at


assert links.clean_url("javascript:alert(1)") is None and links.clean_url("ftp://x.com") is None
assert links.clean_url("myapp.streamlit.app") == "https://myapp.streamlit.app"
assert [l["name"] for l in saved()] == ["Market breadth tracker"]
print("ok   default list has the breadth tracker")

add("Screener", "screener-demo.streamlit.app")
assert saved()[-1] == {"name": "Screener", "url": "https://screener-demo.streamlit.app"}, saved()
print("ok   link added (https:// filled in)")

at = add("Bad", "not a url")
assert len(saved()) == 2 and any("valid web address" in e.value for e in at.error)
at = add("Dup", "https://screener-demo.streamlit.app/")
assert len(saved()) == 2 and any("already" in e.value for e in at.error)
print("ok   invalid and duplicate links rejected")

at = page()
at.button(key="lk_up_1").click().run()
assert [l["name"] for l in saved()] == ["Screener", "Market breadth tracker"]
print("ok   reorder works")

at = page()
at.button(key="lk_del_0").click().run()
at = page()
at.button(key="lk_del_0").click().run()
assert saved() == []
print("ok   links deleted; empty list stays empty (default not re-added)")
