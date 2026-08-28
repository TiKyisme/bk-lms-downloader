from __future__ import annotations

from types import SimpleNamespace

from bklms_downloader.gui import App
from bklms_downloader.scroll_routing import WheelBindingRegistry, choose_scroll_route


class Node:
    def __init__(self, master=None):
        self.master = master


def routes(main: Node, courses: Node, activity: Node, modal: Node | None = None):
    values = [
        ("courses", (courses,)),
        ("activity", (activity,)),
    ]
    if modal is not None:
        values.append(("modal", (modal,)))
    values.append(("main", (main,)))
    return values


def test_courses_descendant_has_exclusive_wheel_owner():
    main = Node()
    courses = Node(main)
    course_label = Node(courses)

    route = choose_scroll_route(course_label, routes(main, courses, Node(main)))

    assert route.owner == "courses"
    assert route.consume


def test_activity_descendant_has_exclusive_wheel_owner():
    main = Node()
    activity = Node(main)
    text = Node(activity)

    route = choose_scroll_route(text, routes(main, Node(main), activity))

    assert route.owner == "activity"
    assert route.consume


def test_normal_main_page_area_routes_to_main():
    main = Node()
    normal_area = Node(main)

    route = choose_scroll_route(normal_area, routes(main, Node(main), Node(main)))

    assert route.owner == "main"
    assert route.consume


def test_child_owns_wheel_at_both_boundaries_without_scroll_chaining():
    main = Node()
    courses = Node(main)

    top = choose_scroll_route(courses, routes(main, courses, Node(main)))
    bottom = choose_scroll_route(courses, routes(main, courses, Node(main)))

    assert (top.owner, top.consume) == ("courses", True)
    assert (bottom.owner, bottom.consume) == ("courses", True)


def test_modal_scroll_region_is_preferred_over_main_page():
    main = Node()
    modal = Node()
    modal_row = Node(modal)

    route = choose_scroll_route(modal_row, routes(main, Node(main), Node(main), modal))

    assert route.owner == "modal"
    assert route.consume


class FakeToplevel:
    def __init__(self):
        self.calls = []

    def bind_all(self, sequence, callback, add=False):
        self.calls.append((sequence, callback, add))


def test_wheel_bindings_are_installed_once_not_on_refresh():
    registry = WheelBindingRegistry()
    toplevel = FakeToplevel()
    callback = lambda _event: "break"

    assert registry.install_once(toplevel, callback)
    assert not registry.install_once(toplevel, callback)
    assert registry.installed
    assert [call[0] for call in toplevel.calls] == [
        "<MouseWheel>",
        "<Button-4>",
        "<Button-5>",
    ]
    assert all(call[2] is False for call in toplevel.calls)


class BoundaryTarget:
    def __init__(self):
        self.calls = []

    def yview_scroll(self, units, mode):
        self.calls.append((units, mode))


def test_gui_router_consumes_a_child_event_even_when_target_cannot_move():
    app = App.__new__(App)
    target = BoundaryTarget()
    app._scroll_regions = {"courses": target}
    app._wheel_remainders = {}
    app._activity_text_widget = None
    event = SimpleNamespace(widget=Node(), delta=-120, num=None)

    assert App._route_wheel(app, event, forced_owner="courses") == "break"
    assert target.calls == [(20, "units")]


def test_windows_precision_wheel_deltas_accumulate_smoothly():
    app = App.__new__(App)
    app._wheel_remainders = {}
    event = SimpleNamespace(delta=1, num=None)

    assert [App._wheel_units(app, "courses", event) for _ in range(6)] == [0, 0, 0, 0, 0, -1]
