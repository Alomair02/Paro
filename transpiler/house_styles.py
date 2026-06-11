"""House styles: curated native themes for template-less users.

A student, an engineer, or an analyst without a corporate template still
deserves a designed deck. Each style is a complete theme — twelve color
slots, a font pair from the measurement-supported set, and its own type
scale — selectable with <deck theme="boardroom"> or a design profile's
theme.house_style. Voices:

  boardroom  consulting/corporate default: ink navy, confident blue, cool panels
  academic   lectures and defenses: warm paper, serif headings, burgundy
  ledger     IB/finance: near-black, banker green, dense dashboard type
  chalk      minimal/startup: off-white, one electric accent, oversized titles
"""

from __future__ import annotations


def _scale(entries: dict[str, tuple]) -> dict[str, dict]:
    scale = {}
    for role, (size, min_size, weight, space_after, line_spacing) in entries.items():
        scale[role] = {
            "size": size,
            "minSize": min_size,
            "weight": weight,
            "spaceAfter": space_after,
            "lineSpacing": line_spacing,
        }
    return scale


HOUSE_STYLES: dict[str, dict] = {
    "boardroom": {
        "name": "boardroom",
        "colors": {
            "dk1": "1C2B39",
            "lt1": "FFFFFF",
            "dk2": "5B6B7A",
            "lt2": "EDF1F5",
            "accent1": "155E9C",
            "accent2": "17807A",
            "accent3": "B5803B",
            "accent4": "64748B",
            "accent5": "8C3B4A",
            "accent6": "3E5C76",
            "hlink": "155E9C",
            "folHlink": "5B6B7A",
        },
        "fonts": {"heading": "Calibri", "body": "Calibri"},
        "typeScale": _scale({
            "title": (36, 32, "bold", "10pt", 1.05),
            "heading": (22, 20, "bold", "6pt", 1.1),
            "subheading": (18, 16, "normal", "5pt", 1.12),
            "body": (16, 14, "normal", "4pt", 1.18),
            "bodySmall": (13, 11.5, "normal", "3pt", 1.15),
            "caption": (10.5, 9.5, "normal", "2pt", 1.1),
        }),
    },
    "academic": {
        "name": "academic",
        "colors": {
            "dk1": "2B2722",
            "lt1": "FFFFFF",
            "dk2": "6B645C",
            "lt2": "F4F1EA",
            "accent1": "7C2D2D",
            "accent2": "31572C",
            "accent3": "1F4E79",
            "accent4": "8A6D3B",
            "accent5": "4A5859",
            "accent6": "70587C",
            "hlink": "1F4E79",
            "folHlink": "6B645C",
        },
        "fonts": {"heading": "Georgia", "body": "Calibri"},
        "typeScale": _scale({
            "title": (40, 36, "bold", "12pt", 1.08),
            "heading": (26, 23, "bold", "7pt", 1.12),
            "subheading": (21, 19, "normal", "6pt", 1.15),
            "body": (18, 16, "normal", "5pt", 1.25),
            "bodySmall": (14, 12.5, "normal", "3pt", 1.2),
            "caption": (11.5, 10.5, "normal", "2pt", 1.1),
        }),
    },
    "ledger": {
        "name": "ledger",
        "colors": {
            "dk1": "14181D",
            "lt1": "FFFFFF",
            "dk2": "555B63",
            "lt2": "EDEFF1",
            "accent1": "175E54",
            "accent2": "1F4E79",
            "accent3": "8A6D3B",
            "accent4": "6E7780",
            "accent5": "7C2D2D",
            "accent6": "35506B",
            "hlink": "1F4E79",
            "folHlink": "555B63",
        },
        "fonts": {"heading": "Arial", "body": "Arial"},
        "typeScale": _scale({
            "title": (30, 27, "bold", "8pt", 1.05),
            "heading": (18, 16, "bold", "5pt", 1.08),
            "subheading": (15, 13.5, "normal", "4pt", 1.1),
            "body": (12.5, 11, "normal", "3pt", 1.15),
            "bodySmall": (10.5, 9.5, "normal", "2pt", 1.12),
            "caption": (9, 8, "normal", "2pt", 1.08),
        }),
    },
    "chalk": {
        "name": "chalk",
        "colors": {
            "dk1": "17181C",
            "lt1": "FFFFFF",
            "dk2": "6F7177",
            "lt2": "F4F4F2",
            "accent1": "3D52F3",
            "accent2": "0FA07A",
            "accent3": "F0A03C",
            "accent4": "9CA0A6",
            "accent5": "74A7D8",
            "accent6": "23B0BE",
            "hlink": "3D52F3",
            "folHlink": "6F7177",
        },
        "fonts": {"heading": "Trebuchet MS", "body": "Trebuchet MS"},
        "typeScale": _scale({
            "title": (44, 38, "bold", "12pt", 1.02),
            "heading": (26, 23, "bold", "7pt", 1.08),
            "subheading": (20, 18, "normal", "6pt", 1.12),
            "body": (16, 14, "normal", "5pt", 1.25),
            "bodySmall": (13, 11.5, "normal", "3pt", 1.2),
            "caption": (11, 10, "normal", "2pt", 1.1),
        }),
    },
}
