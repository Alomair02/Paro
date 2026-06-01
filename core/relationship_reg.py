#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: relationshipreg.py
Author: Abdulaziz Alomair
Date: 2026-06-01 (YYYY-MM-DD)
Version: 1.0
Description: a dictionary keyed by part path. Each entry is a list of relationships that part declares. Every time one part needs to reference another, you call add() and get back an rId string to write into your XML attribute.
"""
import os
from xml.sax.saxutils import quoteattr

class RelationshipRegistry:
    PACKAGE_ROOT = ""

    # Relationship type URIs
    OFFICE_DOC    = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    SLIDE         = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
    SLIDE_LAYOUT  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
    SLIDE_MASTER  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster"
    THEME         = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme"
    IMAGE         = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    HYPERLINK     = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    PRES_PROPS    = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps"
    VIEW_PROPS    = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps"
    TABLE_STYLES  = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles"

    def __init__(self):
        self.registry = {}


    @staticmethod
    def _generate_rid(existing_rels):
        """
        Generate a new rId string that is not already in existing_rels.
        """
        existing_ids = {rel['rId'] for rel in existing_rels}
        i = 1
        while True:
            new_id = f"rId{i}"
            if new_id not in existing_ids:
                return new_id
            i += 1

    @staticmethod
    def rels_path(part_path: str) -> str:
        # "ppt/slides/slide1.xml" → "ppt/slides/_rels/slide1.xml.rels"
        part_path = RelationshipRegistry._normalize_path(part_path)
        if part_path == RelationshipRegistry.PACKAGE_ROOT:
            return "_rels/.rels"

        folder, filename = os.path.split(part_path)
        return os.path.join(folder, "_rels", filename + ".rels").replace("\\", "/")

    @staticmethod
    def _normalize_path(path):
        """
        Normalize the part path to ensure consistent registry keys.
        """
        if path == RelationshipRegistry.PACKAGE_ROOT:
            return RelationshipRegistry.PACKAGE_ROOT

        return os.path.normpath(path).replace("\\", "/").lstrip("/")

    @staticmethod
    def _validate_target_mode(target_mode):
        """
        Validate the optional OPC relationship target mode.
        """
        if target_mode not in (None, "External"):
            raise ValueError(f"Invalid target mode: {target_mode}")

    @staticmethod
    def _validate_relationship_type(rel_type):
        """
        Validate that the relationship type is one of the known types.
        """
        valid_types = {
            RelationshipRegistry.OFFICE_DOC,
            RelationshipRegistry.SLIDE,
            RelationshipRegistry.SLIDE_LAYOUT,
            RelationshipRegistry.SLIDE_MASTER,
            RelationshipRegistry.THEME,
            RelationshipRegistry.IMAGE,
            RelationshipRegistry.HYPERLINK,
            RelationshipRegistry.PRES_PROPS,
            RelationshipRegistry.VIEW_PROPS,
            RelationshipRegistry.TABLE_STYLES
        }
        if rel_type not in valid_types:
            raise ValueError(f"Invalid relationship type: {rel_type}")
        
        
    def add(cls, part_path, target_path, rel_type, target_mode=None):
        """
        Add a relationship from part_path to target_path of type rel_type.
        target_path must already be the target URI to write into the .rels file.
        Returns the rId string to use in the XML.
        """
        cls._validate_relationship_type(rel_type)
        cls._validate_target_mode(target_mode)
        part_path = cls._normalize_path(part_path)

        if part_path not in cls.registry:
            cls.registry[part_path] = []
        
        existing_rels = cls.registry[part_path]
        
        # Check if this relationship already exists
        for rel in existing_rels:
            if (
                rel['target'] == target_path
                and rel['type'] == rel_type
                and rel.get('target_mode') == target_mode
            ):
                return rel['rId']
        
        # Create new relationship
        new_rid = cls._generate_rid(existing_rels)
        new_rel = {
            'rId': new_rid,
            'type': rel_type,
            'target': target_path,
            'target_mode': target_mode
        }
        existing_rels.append(new_rel)
        return new_rid

    
    def render(cls, part_path):
        """
        Takes a part_path and return the .rels XML string for
        that specific part.
        """
        part_path = cls._normalize_path(part_path)
        if part_path not in cls.registry:
            return ""  # No relationships for this part

        rels = cls.registry[part_path]
        rels_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
        
        for rel in rels:
            attrs = [
                f'Id={quoteattr(rel["rId"])}',
                f'Type={quoteattr(rel["type"])}',
                f'Target={quoteattr(rel["target"])}',
            ]
            if rel.get("target_mode"):
                attrs.append(f'TargetMode={quoteattr(rel["target_mode"])}')
            rels_xml.append(f'  <Relationship {" ".join(attrs)} />')
        
        rels_xml.append('</Relationships>')
        return "\n".join(rels_xml)
    
if __name__ == "__main__":

    # Example usage
    registry = RelationshipRegistry()
    rId1 = registry.add("ppt/slides/slide1.xml", "ppt/slides/slide2.xml", RelationshipRegistry.SLIDE)
    rId2 = registry.add("ppt/slides/slide1.xml", "ppt/slides/slide3.xml", RelationshipRegistry.SLIDE)
    rId3 = registry.add("ppt/slides/slide1.xml", "ppt/slides/slide2.xml", RelationshipRegistry.SLIDE)  # Should return same r
    print(rId1)  # rId1
    print(rId2)  # rId2
    print(rId3)  # rId1 (same as first relationship)
    print(registry.render("ppt/slides/slide1.xml"))
