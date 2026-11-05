"""Suggested next questions, chosen from what the answer just covered."""

from __future__ import annotations

EN = {
    "fee": ["Camping fees in {park}", "What does a vehicle pay to enter {park}?", "Do I need a visa?"],
    "planning": ["How much are park fees for my group?", "What wildlife will I see in {park}?", "Best time to visit {park}"],
    "park_fact": ["Entry fees for {park}", "What can I do in {park}?", "How do I contact {park}?"],
    "wildlife": ["Entry fees for {park}", "Best time to visit {park}", "Where can I stay in {park}?"],
    "activity": ["Entry fees for {park}", "Where can I stay in {park}?", "Which parks suit a first safari?"],
    "visa": ["Which parks suit a first safari?", "Serengeti entry fees", "What is the best season for wildlife?"],
    "accommodation": ["Entry fees for {park}", "Special campsite fees in {park}", "What can I do in {park}?"],
    "contact": ["Entry fees for {park}", "What can I do in {park}?"],
    "scope": ["Serengeti entry fees", "Plan 4 days in Tarangire and Lake Manyara", "Which parks are near Arusha?"],
    "default": ["Which parks suit a first safari?", "Serengeti entry fees", "Do I need a visa?"],
}
SW = {
    "fee": ["Ada ya kambi {park}", "Gari linalipa kiasi gani {park}?", "Ninahitaji viza?"],
    "planning": ["Ada za hifadhi kwa kundi langu ni kiasi gani?", "Wanyama gani nitaona {park}?", "Wakati mzuri kutembelea {park}"],
    "default": ["Hifadhi zipi zinafaa safari ya kwanza?", "Ada ya kuingia Serengeti", "Ninahitaji viza?"],
}


def follow_ups(intent: str, park_name: str | None, language: str, abstained: bool) -> list[str]:
    table = SW if language == "sw" else EN
    options = table.get(intent) or table["default"]
    if not park_name:
        options = [item for item in options if "{park}" not in item] or table["default"]
    short = (park_name or "").replace(" National Park", "")
    return [item.format(park=short) for item in options][:3]
