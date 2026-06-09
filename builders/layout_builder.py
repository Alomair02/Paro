"""Builder for ppt/slideLayouts/slideLayoutN.xml parts."""

from lxml import etree

from core.content_type_reg import ContentTypeRegistry
from core.relationship_reg import RelationshipRegistry
from core.xml_builder import qn, to_xml_string

from builders.common import (
    REFERENCE,
    make_placeholder_shape,
    make_root,
    make_sp_tree,
    package_path,
    relationship_target,
)


LAYOUT_DEFINITIONS = {
    "title": {
        "index": 1,
        "reference_key": "title",
        "name": "Title Slide",
    },
    "titleBody": {
        "index": 2,
        "reference_key": "titleBody",
        "name": "Title and Content",
    },
    "titleOnly": {
        "index": 5,
        "reference_key": "titleOnly",
        "name": "Title Only",
    },
    "twoContent": {
        "index": 6,
        "reference_key": "twoContent",
        "name": "Two Content",
    },
    "blank": {
        "index": 3,
        "reference_key": "blank",
        "name": "Blank",
    },
    "picture": {
        "index": 4,
        "reference_key": "picture",
        "name": "Picture",
    },
}

for _layout in LAYOUT_DEFINITIONS.values():
    _reference = REFERENCE["placeholder_coordinates_16x9"][_layout["reference_key"]]
    _layout["type"] = _reference["layout_type"]
    _layout["placeholders"] = _reference["placeholders"]
    _layout["part_path"] = package_path("slideLayout", _layout["index"])
    _layout["id"] = 2147483648 + _layout["index"]


class LayoutBuilder:
    """Build slide layout parts from data-table definitions."""

    DEFAULT_MASTER_PART_PATH = package_path("slideMaster", 1)

    def __init__(
        self,
        content_types: ContentTypeRegistry,
        relationships: RelationshipRegistry,
        layout_definitions: dict = None,
    ):
        self.content_types = content_types
        self.relationships = relationships
        self.layout_definitions = layout_definitions or LAYOUT_DEFINITIONS

    def build(
        self,
        layout_name: str,
        master_part_path: str = DEFAULT_MASTER_PART_PATH,
        part_path: str = None,
    ) -> str:
        """Build one supported slide layout part and register its metadata."""
        layout = self.layout_definitions[layout_name]
        part_path = part_path or layout["part_path"]

        self.content_types.add_override(part_path, ContentTypeRegistry.SLIDE_LAYOUT)
        self.relationships.add(
            part_path,
            relationship_target(part_path, master_part_path),
            RelationshipRegistry.SLIDE_MASTER,
        )

        root = make_root("p", "sldLayout")
        root.set("type", layout["type"])
        root.set("preserve", "1")

        c_sld = etree.SubElement(root, qn("p", "cSld"))
        c_sld.set("name", layout["name"])

        sp_tree = make_sp_tree()
        c_sld.append(sp_tree)

        shape_id = REFERENCE["constraints"]["shape_id_start"]
        for placeholder in layout["placeholders"]:
            sp_tree.append(
                make_placeholder_shape(
                    placeholder,
                    shape_id,
                    name_prefix=f"{layout['name']} Placeholder",
                )
            )
            shape_id += 1

        clr_map_ovr = etree.SubElement(root, qn("p", "clrMapOvr"))
        etree.SubElement(clr_map_ovr, qn("a", "masterClrMapping"))

        return to_xml_string(root)

    @classmethod
    def default_layout_records(cls) -> list[dict]:
        """Return master-builder records for the default layouts."""
        return [
            {
                "name": name,
                "part_path": layout["part_path"],
                "id": layout["id"],
            }
            for name, layout in LAYOUT_DEFINITIONS.items()
        ]
