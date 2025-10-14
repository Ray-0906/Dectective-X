from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import networkx as nx
from networkx.readwrite import json_graph

from src.config import GRAPH_PATH


class GraphStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or GRAPH_PATH
        self.graph = nx.MultiDiGraph()

    def add_person(self, contact_id: int, name: str | None, phone: str | None) -> None:
        self.graph.add_node(
            ("Person", contact_id),
            label=name or phone or f"Contact {contact_id}",
            phone=phone,
        )

    def add_message(
        self,
        message_id: int,
        sender_contact_id: int,
        receiver_contact_id: int | None,
        timestamp: str,
        content: str,
        keywords: Iterable[str],
    ) -> None:
        message_node = ("Message", message_id)
        self.graph.add_node(message_node, label=f"Msg {message_id}", timestamp=timestamp, content=content)
        self.graph.add_edge(("Person", sender_contact_id), message_node, relation="SENT")
        if receiver_contact_id is not None:
            self.graph.add_edge(message_node, ("Person", receiver_contact_id), relation="TO")
        for keyword in keywords:
            keyword_node = ("Keyword", keyword.lower())
            self.graph.add_node(keyword_node, label=keyword.lower())
            self.graph.add_edge(message_node, keyword_node, relation="MENTIONS")

    def add_call(
        self,
        call_id: int,
        caller_contact_id: int,
        callee_contact_id: int,
        start_time: str,
        duration_seconds: int,
    ) -> None:
        call_node = ("Call", call_id)
        self.graph.add_node(call_node, label=f"Call {call_id}", start_time=start_time, duration=duration_seconds)
        self.graph.add_edge(("Person", caller_contact_id), call_node, relation="ORIGINATED")
        self.graph.add_edge(call_node, ("Person", callee_contact_id), relation="TARGET")

    def add_location(
        self,
        location_id: int,
        contact_id: int,
        latitude: float,
        longitude: float,
        timestamp: str,
    ) -> None:
        location_node = ("Location", location_id)
        self.graph.add_node(location_node, label=f"Loc {location_id}", latitude=latitude, longitude=longitude, timestamp=timestamp)
        self.graph.add_edge(("Person", contact_id), location_node, relation="WAS_AT")

    def save(self) -> None:
        data = json_graph.node_link_data(self.graph)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def load(self) -> None:
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.graph = json_graph.node_link_graph(data, multigraph=True)

    def neighbors(self, node) -> list:
        return list(self.graph.neighbors(node))

    def edges(self, data: bool = False):
        return list(self.graph.edges(data=data, keys=True))
