"""Builder for ppt/theme/themeN.xml parts."""

from lxml import etree

from core.content_type_reg import ContentTypeRegistry
from core.xml_builder import make_ln, make_solid_fill, qn, to_xml_string

from builders.common import (
    REFERENCE,
    clean_hex,
    make_root,
    package_path,
)


class ThemeBuilder:
    """Build DrawingML theme parts."""

    DEFAULT_PART_PATH = package_path("theme", 1)

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships=None,
    ):
        self.content_types = content_types
        self.relationships = relationships

    def build(self, theme: dict, part_path: str = DEFAULT_PART_PATH) -> str:
        """Build a theme part and register its content type."""
        self.content_types.add_override(part_path, ContentTypeRegistry.THEME)

        root = make_root("a", "theme")
        root.set("name", theme["name"])

        theme_elements = etree.SubElement(root, qn("a", "themeElements"))
        theme_elements.append(self._make_color_scheme(theme))
        theme_elements.append(self._make_font_scheme(theme))
        theme_elements.append(self._make_format_scheme(theme))

        etree.SubElement(root, qn("a", "objectDefaults"))
        etree.SubElement(root, qn("a", "extraClrSchemeLst"))

        return to_xml_string(root)

    def _make_color_scheme(self, theme: dict) -> etree._Element:
        clr_scheme = etree.Element(qn("a", "clrScheme"))
        clr_scheme.set("name", theme.get("colorSchemeName", theme["name"]))

        colors = theme["colors"]
        sysclr_slots = REFERENCE["color_scheme_slots"]["sysclr_slots"]
        # PowerPoint resolves a:sysClr from the LIVE system color (windowText
        # -> black, window -> white); lastClr is only a cache hint. Emitting a
        # custom dk1/lt1 as sysClr silently locks it to black/white, so only
        # slots that actually ARE the system default may use sysClr.
        sysclr_defaults = {"windowText": "000000", "window": "FFFFFF"}
        for slot in REFERENCE["color_scheme_slots"]["order"]:
            slot_el = etree.SubElement(clr_scheme, qn("a", slot))
            value = clean_hex(colors[slot])
            sys_val = sysclr_slots.get(slot)
            if sys_val and value.upper() == sysclr_defaults[sys_val]:
                clr = etree.SubElement(slot_el, qn("a", "sysClr"))
                clr.set("val", sys_val)
                clr.set("lastClr", value)
            else:
                clr = etree.SubElement(slot_el, qn("a", "srgbClr"))
                clr.set("val", value)

        return clr_scheme

    def _make_font_scheme(self, theme: dict) -> etree._Element:
        font_scheme = etree.Element(qn("a", "fontScheme"))
        font_scheme.set("name", theme.get("fontSchemeName", theme["name"]))

        fonts = theme["fonts"]
        font_scheme.append(self._make_font_collection("majorFont", fonts["heading"]))
        font_scheme.append(self._make_font_collection("minorFont", fonts["body"]))
        return font_scheme

    def _make_font_collection(self, tag: str, latin_typeface: str) -> etree._Element:
        collection = etree.Element(qn("a", tag))
        latin = etree.SubElement(collection, qn("a", "latin"))
        latin.set("typeface", latin_typeface)
        ea = etree.SubElement(collection, qn("a", "ea"))
        ea.set("typeface", "")
        cs = etree.SubElement(collection, qn("a", "cs"))
        cs.set("typeface", "")
        return collection

    def _make_format_scheme(self, theme: dict) -> etree._Element:
        fmt_scheme = etree.Element(qn("a", "fmtScheme"))
        fmt_scheme.set("name", theme.get("formatSchemeName", theme["name"]))

        fmt_scheme.append(self._make_fill_style_list())
        fmt_scheme.append(self._make_line_style_list())
        fmt_scheme.append(self._make_effect_style_list())
        fmt_scheme.append(self._make_bg_fill_style_list())
        return fmt_scheme

    def _make_fill_style_list(self) -> etree._Element:
        fill_lst = etree.Element(qn("a", "fillStyleLst"))
        for color in ("phClr", "accent1", "accent2"):
            fill_lst.append(make_solid_fill(color))
        return fill_lst

    def _make_line_style_list(self) -> etree._Element:
        line_lst = etree.Element(qn("a", "lnStyleLst"))
        for width in (9525, 25400, 38100):
            ln = make_ln(width, "phClr")
            etree.SubElement(ln, qn("a", "prstDash")).set("val", "solid")
            line_lst.append(ln)
        return line_lst

    def _make_effect_style_list(self) -> etree._Element:
        effect_lst = etree.Element(qn("a", "effectStyleLst"))
        for _ in range(3):
            effect_style = etree.SubElement(effect_lst, qn("a", "effectStyle"))
            etree.SubElement(effect_style, qn("a", "effectLst"))
        return effect_lst

    def _make_bg_fill_style_list(self) -> etree._Element:
        bg_fill_lst = etree.Element(qn("a", "bgFillStyleLst"))
        for color in ("lt1", "dk1", "phClr"):
            bg_fill_lst.append(make_solid_fill(color))
        return bg_fill_lst
