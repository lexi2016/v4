"""Strict validator for the bounded announcement output schema vocabulary.

This is not a general JSON Schema implementation. Unsupported schema constructs
fail closed. It covers object/array/primitives/required/enums/extra-field denial.
"""
from __future__ import annotations
import math

ALLOWED = {"type","properties","required","additionalProperties","items","enum","const","description","title",
           "minItems","maxItems","minLength","maxLength"}


def validate_output(value, schema):
    if not isinstance(schema,dict) or set(schema)-ALLOWED:
        raise ValueError("OUTPUT_SCHEMA_VOCABULARY_UNSUPPORTED")
    kind=schema.get("type")
    valid={"object":isinstance(value,dict),"array":isinstance(value,list),"string":isinstance(value,str),
           "boolean":type(value) is bool,"integer":type(value) is int,
           "number":type(value) in (int,float) and math.isfinite(value),"null":value is None}
    if kind not in valid or not valid[kind]: raise ValueError("OUTPUT_SCHEMA_TYPE_INVALID")
    if "enum" in schema and not any(type(value)==type(x) and value==x for x in schema["enum"]):
        raise ValueError("OUTPUT_SCHEMA_ENUM_INVALID")
    if "const" in schema and (type(value)!=type(schema["const"]) or value!=schema["const"]):
        raise ValueError("OUTPUT_SCHEMA_CONST_INVALID")
    if kind=="object":
        properties=schema.get("properties",{})
        if not isinstance(properties,dict) or not set(schema.get("required",[])).issubset(value):
            raise ValueError("OUTPUT_SCHEMA_REQUIRED_MISSING")
        unknown=set(value)-set(properties)
        if unknown and schema.get("additionalProperties") is False:
            raise ValueError("OUTPUT_SCHEMA_EXTRA_FIELD")
        if isinstance(schema.get("additionalProperties"),dict):
            for key in unknown: validate_output(value[key],schema["additionalProperties"])
        for key in set(value)&set(properties): validate_output(value[key],properties[key])
    elif kind=="array":
        if "items" not in schema: raise ValueError("OUTPUT_SCHEMA_ITEMS_REQUIRED")
        for item in value: validate_output(item,schema["items"])
        if len(value)<schema.get("minItems",0) or len(value)>schema.get("maxItems",len(value)):
            raise ValueError("OUTPUT_SCHEMA_ARRAY_LENGTH")
    elif kind=="string":
        if len(value)<schema.get("minLength",0) or len(value)>schema.get("maxLength",len(value)):
            raise ValueError("OUTPUT_SCHEMA_STRING_LENGTH")
