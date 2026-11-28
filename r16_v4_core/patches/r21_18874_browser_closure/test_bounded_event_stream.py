from datetime import date

from fastapi import FastAPI
from starlette.testclient import TestClient

from content_projection.bounded_event_stream import BoundedIsolationEvents
from v4_core.api.routes_sse import EventBus, build_sse_router


def test_finite_http_replay_and_resume():
    bus = EventBus()
    source_day = date(2026, 11, 27).isoformat()
    another_day = date(2026, 11, 26).isoformat()
    old = bus.publish("workbench_completed", {"source_date": source_day})
    another = bus.publish("workbench_completed", {"source_date": another_day})
    new = bus.publish("a_share_daily_completed", {"source_date": source_day})

    app = FastAPI()
    app.include_router(build_sse_router(bus))

    @app.get("/untouched")
    def untouched():
        return {"status": "ready"}

    with TestClient(BoundedIsolationEvents(app, bus)) as client:
        day_endpoint = f"/api/v4/research/workbench/days/{source_day}/events"
        response = client.get(day_endpoint)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert int(response.headers["content-length"]) == len(response.content)
        assert response.text.startswith("retry: 5000\n\n")
        assert response.text.index(old["id"]) < response.text.index(new["id"])
        assert another["id"] not in response.text
        assert bus._subscribers == []

        resume = client.get(day_endpoint, headers={"Last-Event-ID": old["id"]})
        assert old["id"] not in resume.text and new["id"] in resume.text
        quiet = client.get(day_endpoint, headers={"Last-Event-ID": new["id"]})
        assert "id: " not in quiet.text
        assert quiet.text.endswith(f": connected source_date={source_day}\n\n")

        global_endpoint = "/api/v4/research/events"
        represented = client.get(global_endpoint, params={"since": old["id"]})
        assert old["id"] not in represented.text
        assert another["id"] in represented.text and new["id"] in represented.text
        header_priority = client.get(
            global_endpoint,
            headers={"Last-Event-ID": new["id"]},
            params={"daily_since": old["id"]},
        )
        assert "id: " not in header_priority.text
        diagnostic = client.get(day_endpoint, params={"once": "true"})
        assert old["id"] in diagnostic.text and new["id"] not in diagnostic.text
        assert "retry: " not in diagnostic.text
        assert client.get(day_endpoint, params={"once": "invalid"}).status_code == 422
        assert client.get("/untouched").json() == {"status": "ready"}


if __name__ == "__main__":
    test_finite_http_replay_and_resume()
    print("PASS finite complete/empty replay, date scope, Last-Event-ID, global cursors, native once and unrelated routes")
