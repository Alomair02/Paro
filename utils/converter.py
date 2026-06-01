#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Filename: converter.py
Author: Abdulaziz Alomair
Date: 2026-06-01 (YYYY-MM-DD)
Version: 1.0
Description: This is a utility class to convert between human units (like inches, cm, mm, pt, etc.) and EMU (English Metric Units) which is the unit used in OOXML for measurements. This class will be used throughout the codebase whenever we need to convert between these units.
"""
import re

class UnitConverter:
    """
    A class to convert between human units and EMU OOXML units.
    """
    
    CONVERSION_FACTORS = {
        'inch': 914400, 'in': 914400,
        'cm': 360000,
        'mm': 36000,
        'pt': 12700,
        'pica': 152400,
        'pixel': 9525, 'px': 9525,
        'emu': 1,
        'twip': 635,
        'dxa': 635,
        'dya': 635,
        'twentieth_of_a_point': 635
    }

    @staticmethod
    def parse(value: str) -> tuple[float, str]:
        """
        Parses strings like "1in", "-2.5 cm", "100px" into a magnitude and unit.
        """
        match = re.match(r"^([+-]?\d*\.?\d+)\s*([a-zA-Z_]+)$", str(value).strip())
        if not match:
            raise ValueError(f"Invalid value format: {value}")
        
        return float(match.group(1)), match.group(2).lower()
    
    @classmethod
    def to_emu(cls, value: str | int | float, unit: str = None) -> int:
        """
        Convert a value from a specified unit to EMU.
        """
        if isinstance(value, str):
            magnitude, unit = cls.parse(value)
        else:
            magnitude = value

        if not unit or unit not in cls.CONVERSION_FACTORS:
            raise ValueError(f"Unsupported or missing unit: {unit}")
            
        return int(round(magnitude * cls.CONVERSION_FACTORS[unit]))

    @classmethod
    def from_emu(cls, value: int | float, unit: str) -> float:
        """
        Convert a value from EMU to a specified unit.
        """
        unit = unit.lower()
        if unit not in cls.CONVERSION_FACTORS:
            raise ValueError(f"Unsupported unit: {unit}")
            
        return value / cls.CONVERSION_FACTORS[unit]

    @staticmethod
    def degrees_to_ooxml_angle(degrees: int | float) -> int:
        """
        Convert degrees to OOXML angle units.
        OOXML stores rotation in 60,000ths of a degree.
        """
        return int(round(degrees * 60000))
    

if __name__ == "__main__":
    
    print(UnitConverter.to_emu(1, 'inch'))       # 914400
    print(UnitConverter.to_emu("2.5 cm"))        # 900000 (handles spaces)
    print(UnitConverter.to_emu("-100px"))        # -952500 (handles negatives & aliases)
    print(UnitConverter.from_emu(914400, 'in'))  # 1.0
