"""Print the privacy graph as a Mermaid diagram, generated from the real code.

Usage: make graph
"""
from privacy.graph import build_privacy_graph
from privacy.detectors import PatternDetector
from privacy.photo_store import InMemoryPhotoStore

# Fakes only: the diagram needs neither the model nor Supabase, so nothing is loaded.
graph = build_privacy_graph([PatternDetector()], InMemoryPhotoStore())
print(graph.get_graph().draw_mermaid())
