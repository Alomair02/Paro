"""Builder for ppt/slideMasters/slideMaster1.xml."""

from lxml import etree

from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import make_solid_fill, qn, to_xml_string

from builders.common import (
    REFERENCE,
    make_placeholder_shape,
    make_root,
    make_sp_tree,
    package_path,
    relationship_target,
)


class MasterBuilder:
    """Build a slide master part."""

    DEFAULT_PART_PATH = package_path("slideMaster", 1)
    DEFAULT_THEME_PART_PATH = package_path("theme", 1)

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships: RelationshipRegistry,
    ):
        self.content_types = content_types
        self.relationships = relationships

    def build(
        self,
        layouts: list,
        theme_part_path: str = DEFAULT_THEME_PART_PATH,
        part_path: str = DEFAULT_PART_PATH,
    ) -> str:
        """Build the master and register layout/theme relationships."""
        self.content_types.add_override(part_path, ContentTypeRegistry.SLIDE_MASTER)

        root = make_root("p", "sldMaster")

        c_sld = etree.SubElement(root, qn("p", "cSld"))
        sp_tree = make_sp_tree()
        c_sld.append(sp_tree)
        self._append_master_placeholders(sp_tree)

        root.append(self._make_color_map())
        root.append(self._make_slide_layout_id_list(part_path, layouts))
        root.append(self._make_text_styles())

        self.relationships.add(
            part_path,
            relationship_target(part_path, theme_part_path),
            RelationshipRegistry.THEME,
        )

        return to_xml_string(root)

    def _append_master_placeholders(self, sp_tree: etree._Element):
        placeholders = REFERENCE["placeholder_coordinates_16x9"]["titleBody"][
            "placeholders"
        ]
        shape_id = REFERENCE["constraints"]["shape_id_start"]
        for placeholder in placeholders:
            sp_tree.append(
                make_placeholder_shape(
                    placeholder,
                    shape_id,
                    name_prefix="Master Placeholder",
                )
            )
            shape_id += 1

    def _make_color_map(self) -> etree._Element:
        clr_map = etree.Element(qn("p", "clrMap"))
        for key, value in REFERENCE["color_map_default"].items():
            if key != "_note":
                clr_map.set(key, value)
        return clr_map

    def _make_slide_layout_id_list(
        self,
        part_path: str,
        layouts: list,
    ) -> etree._Element:
        layout_id_lst = etree.Element(qn("p", "sldLayoutIdLst"))
        for index, layout in enumerate(layouts, start=1):
            layout_part_path = layout["part_path"] if isinstance(layout, dict) else layout
            layout_id = (
                layout.get("id")
                if isinstance(layout, dict) and layout.get("id") is not None
                else 2147483648 + index
            )
            rid = self.relationships.add(
                part_path,
                relationship_target(part_path, layout_part_path),
                RelationshipRegistry.SLIDE_LAYOUT,
            )

            layout_id_el = etree.SubElement(layout_id_lst, qn("p", "sldLayoutId"))
            layout_id_el.set("id", str(layout_id))
            layout_id_el.set(qn("r", "id"), rid)

        return layout_id_lst

    def _make_text_styles(self) -> etree._Element:
        tx_styles = etree.Element(qn("p", "txStyles"))

        title_style = etree.SubElement(tx_styles, qn("p", "titleStyle"))
        title_style.append(self._make_level_style(1, 4400, "+mj-lt", "tx1"))

        body_style = etree.SubElement(tx_styles, qn("p", "bodyStyle"))
        for level in range(1, 10):
            size = max(1800, 3200 - ((level - 1) * 200))
            body_style.append(self._make_level_style(level, size, "+mn-lt", "tx1"))

        other_style = etree.SubElement(tx_styles, qn("p", "otherStyle"))
        other_style.append(self._make_level_style(1, 2400, "+mn-lt", "tx1"))

        return tx_styles

    def _make_level_style(
        self,
        level: int,
        size: int,
        latin_typeface: str,
        color: str,
    ) -> etree._Element:
        p_pr = etree.Element(qn("a", f"lvl{level}pPr"))
        p_pr.set("algn", "l")
        p_pr.set("marL", str((level - 1) * 457200))
        p_pr.set("indent", "0")
        etree.SubElement(p_pr, qn("a", "buNone"))

        def_r_pr = etree.SubElement(p_pr, qn("a", "defRPr"))
        def_r_pr.set("sz", str(size))
        def_r_pr.append(make_solid_fill(color))
        latin = etree.SubElement(def_r_pr, qn("a", "latin"))
        latin.set("typeface", latin_typeface)
        ea = etree.SubElement(def_r_pr, qn("a", "ea"))
        ea.set("typeface", "")
        cs = etree.SubElement(def_r_pr, qn("a", "cs"))
        cs.set("typeface", "")

        return p_pr
